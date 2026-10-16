"""Runs ON THE NUC (playing the Jetson's role): captures the real camera,
offers it over WebRTC to the Flutter app, and streams *mock* AI analysis
samples (hip/knee angle, speed, spasm flag) over the WebRTC data channel —
everything downstream (mock_flutter_answer.py, the real Flutter app,
Django/telemetry) is unaware the analysis numbers are fake.

This follows the exact same signaling contract as mock_flutter_answer.py,
just from the other end (README_WebRTC.md #8-#14, API_REFERENCE.md #8-#13):

    1. Connect to ws/jetson/<JETSON_DEVICE_ID>/?token=<JETSON_AUTH_TOKEN>
    2. Wait for Django's {"type": "start_stream", "session_id": ...}
    3. Open the local camera, build an RTCPeerConnection with:
         - the camera video track
         - a "analysis" data channel (Jetson -> Flutter, never touches Django)
    4. Create a non-trickle SDP offer (wait for ICE gathering to finish,
       same convention as mock_flutter_answer.py) and send it
    5. Receive the sdp_answer, complete negotiation
    6. Once connected: send {"type": "webrtc_connected"}, and start pushing
       one mock analysis_data message per second on the data channel
    7. On {"type": "stop_stream"}: tear everything down and confirm with
       {"type": "stream_stopped"}

Camera capture uses aiortc's MediaPlayer, which opens the device straight
through ffmpeg/PyAV — no OpenCV dependency needed:
    Linux:   /dev/video0 via the v4l2 input format (default here)
    macOS:   0 via avfoundation           (--camera-format avfoundation --camera 0)
    Windows: a device name via dshow      (--camera-format dshow --camera "video=Integrated Camera")

By default `--camera` is "auto": every /dev/video* node is probed in order
(each one opened and required to actually deliver a frame, since some v4l2
nodes on a given board are metadata-only and never produce video) and the
first one that works wins. Pass an explicit device to skip probing.

Usage (local, outside Docker):
    python jetson_mock/nuc_capture_send.py                      # auto-detect the camera
    python jetson_mock/nuc_capture_send.py --camera /dev/video2 --width 1280 --height 720
    python jetson_mock/nuc_capture_send.py --host 192.168.1.50:8000

Requires the project venv (aiortc, websockets — see pyproject.toml):
    uv run python jetson_mock/nuc_capture_send.py

Running as its own container: see jetson_mock/Dockerfile +
docker-compose.jetson-mock.yml at the repo root — every flag below also
has a JETSON_MOCK_* environment variable fallback (env used when the flag
is omitted), and the webcam device (--camera) needs to be passed through
with `docker run --device=/dev/video0` (or the `devices:` mapping in that
compose file) since containers don't see the host's devices by default.

Every WebSocket connect (including the very first one, so the container
can be started before Django is up) retries with backoff instead of
exiting — logs "connect failed / retrying" and keeps going. Ctrl-C, or
`docker stop`, exits cleanly.
"""
import argparse
import asyncio
import glob
import json
import os
import random
import re
import sys

import websockets
from aiortc import RTCPeerConnection, RTCSessionDescription
from aiortc.contrib.media import MediaPlayer

HOST = os.environ.get("JETSON_MOCK_HOST", "127.0.0.1:8001")
DEVICE_ID = os.environ.get("JETSON_MOCK_DEVICE_ID", "JETSON001")
TOKEN = os.environ.get("JETSON_MOCK_TOKEN", "changeme-dev-token")
CAMERA = os.environ.get("JETSON_MOCK_VIDEO_DEVICE", "auto")
SSL = os.environ.get("JETSON_MOCK_SSL", "false").lower() in ("1", "true", "yes")

ANALYSIS_INTERVAL = 1.0 / 3  # seconds between mock analysis samples (3x the original 1.0s rate)
PROBE_TIMEOUT = 3.0  # seconds to wait for a first frame while probing a camera
RECONNECT_DELAY = 3.0  # seconds between WebSocket (re)connect attempts


def _video_device_candidates() -> list[str]:
    """/dev/video0, /dev/video1, ... in numeric order (Linux v4l2 nodes)."""
    devices = glob.glob("/dev/video*")

    def index(path: str) -> int:
        m = re.search(r"(\d+)$", path)
        return int(m.group(1)) if m else 0

    return sorted(devices, key=index)


def _try_open(camera: str, camera_format: str | None, width: int, height: int, framerate: int) -> MediaPlayer | None:
    options = {
        "video_size": f"{width}x{height}",
        "framerate": str(framerate),
    }
    try:
        player = MediaPlayer(camera, format=camera_format, options=options)
    except Exception as exc:  # noqa: BLE001 - ffmpeg/PyAV errors vary by platform
        print(f"   {camera}: could not open ({exc})")
        return None
    if player.video is None:
        print(f"   {camera}: opened but has no video track")
        return None
    return player


async def _verify_delivers_frames(player: MediaPlayer) -> bool:
    try:
        await asyncio.wait_for(player.video.recv(), timeout=PROBE_TIMEOUT)
        return True
    except Exception as exc:  # noqa: BLE001 - timeout, decode error, device busy, ...
        print(f"   no frame received ({exc})")
        return False


async def open_camera(camera: str, camera_format: str | None, width: int, height: int, framerate: int) -> MediaPlayer:
    """Opens the real camera and returns a MediaPlayer whose .video track is
    confirmed to actually deliver frames.

    camera="auto" probes every /dev/video* node in order and uses the first
    one that works; otherwise the given source is opened directly (no probe
    skip — a bad explicit --camera should fail loudly, not silently retry).
    """
    if camera != "auto":
        player = _try_open(camera, camera_format, width, height, framerate)
        if player is None or not await _verify_delivers_frames(player):
            raise RuntimeError(f"Camera {camera!r} (format={camera_format}) did not deliver a frame")
        print(f"-- using camera {camera}")
        return player

    candidates = _video_device_candidates()
    if not candidates:
        raise RuntimeError("No /dev/video* devices found; pass --camera explicitly")

    print(f"-- auto-detecting camera among {candidates}")
    for device in candidates:
        print(f"   probing {device}...")
        player = _try_open(device, camera_format or "v4l2", width, height, framerate)
        if player is None:
            continue
        if await _verify_delivers_frames(player):
            print(f"-- using camera {device}")
            return player
        if player.video:
            player.video.stop()

    raise RuntimeError(f"No working camera found among {candidates}")


def mock_analysis_sample(session_id: str) -> dict:
    """Fabricated AI output, same shape telemetry.AnalysisEvent expects
    (telemetry/models.py) — swap this out once real inference exists."""
    return {
        "type": "analysis_data",
        "session_id": session_id,
        "hip_angle_left": round(random.uniform(20.0, 60.0), 1),
        "hip_angle_right": round(random.uniform(20.0, 60.0), 1),
        "knee_angle_left": round(random.uniform(30.0, 90.0), 1),
        "knee_angle_right": round(random.uniform(30.0, 90.0), 1),
        "speed": round(random.uniform(0.5, 2.5), 2),
        "spasm_detected": random.random() < 0.05,
    }


class NucJetson:
    def __init__(self, ws, camera: str, camera_format: str | None, width: int, height: int, framerate: int):
        self.ws = ws
        self.camera = camera
        self.camera_format = camera_format
        self.width = width
        self.height = height
        self.framerate = framerate

        self.pc: RTCPeerConnection | None = None
        self.player: MediaPlayer | None = None
        self.channel = None
        self.session_id: str | None = None
        self._analysis_task: asyncio.Task | None = None
        self._webrtc_connected_sent = False

    async def send(self, message: dict):
        print(">> " + json.dumps(message))
        await self.ws.send(json.dumps(message))

    # -- start_stream: build the peer connection and offer it -------------
    async def handle_start_stream(self, content: dict):
        self.session_id = content.get("session_id")
        self._webrtc_connected_sent = False
        print(f"-- start_stream for session {self.session_id}")

        self.player = await open_camera(self.camera, self.camera_format, self.width, self.height, self.framerate)
        self.pc = RTCPeerConnection()
        self.pc.addTrack(self.player.video)

        # Analysis flows Jetson -> Flutter over this data channel, never
        # through Django (README_WebRTC.md #14).
        self.channel = self.pc.createDataChannel("analysis")

        @self.channel.on("open")
        def on_open():
            print("-- data channel open, starting mock analysis stream")
            self._analysis_task = asyncio.ensure_future(self._send_analysis_loop())

        @self.channel.on("close")
        def on_close():
            if self._analysis_task:
                self._analysis_task.cancel()

        @self.pc.on("iceconnectionstatechange")
        async def on_ice_state_change():
            print(f"-- ICE connection state: {self.pc.iceConnectionState}")
            # aiortc doesn't reliably pass through "connected" before
            # "completed" (sometimes goes checking -> completed directly),
            # so watch for either; _webrtc_connected_sent guards against
            # sending the notice twice if both fire.
            if self.pc.iceConnectionState in ("connected", "completed") and not self._webrtc_connected_sent:
                self._webrtc_connected_sent = True
                await self.send({"type": "webrtc_connected", "session_id": self.session_id})

        await self._create_and_send_offer()

    async def _create_and_send_offer(self):
        offer = await self.pc.createOffer()
        await self.pc.setLocalDescription(offer)

        # Non-trickle ICE, same convention as mock_flutter_answer.py: wait
        # for gathering to finish so the offer's SDP already has every
        # candidate baked in (API_REFERENCE.md #9).
        while self.pc.iceGatheringState != "complete":
            await asyncio.sleep(0.1)

        await self.send(
            {
                "type": "sdp_offer",
                "session_id": self.session_id,
                "sdp": self.pc.localDescription.sdp,
                "sdp_type": self.pc.localDescription.type,
            }
        )

    async def _send_analysis_loop(self):
        try:
            while True:
                sample = mock_analysis_sample(self.session_id)
                if self.channel and self.channel.readyState == "open":
                    self.channel.send(json.dumps(sample))
                    print(">> [data channel] " + json.dumps(sample))
                await asyncio.sleep(ANALYSIS_INTERVAL)
        except asyncio.CancelledError:
            pass

    # -- sdp_answer: complete negotiation ----------------------------------
    async def handle_sdp_answer(self, content: dict):
        if self.pc is None:
            print("!! sdp_answer received with no active peer connection, ignoring")
            return
        answer = RTCSessionDescription(sdp=content["sdp"], type="answer")
        await self.pc.setRemoteDescription(answer)
        print("-- remote description (answer) set, negotiation complete")

    # -- stop_stream: tear everything down ---------------------------------
    async def handle_stop_stream(self, content: dict):
        print(f"-- stop_stream for session {self.session_id}")
        failed = False
        try:
            await self._teardown()
        except Exception as exc:  # noqa: BLE001 - report failure, don't crash the client
            print(f"!! teardown error: {exc}")
            failed = True
        await self.send({"type": "stream_stopped", "session_id": self.session_id, "failed": failed})

    async def _teardown(self):
        if self._analysis_task:
            self._analysis_task.cancel()
            self._analysis_task = None
        if self.player:
            if self.player.video:
                self.player.video.stop()
            self.player = None
        if self.pc:
            await self.pc.close()
            self.pc = None
        self.channel = None


async def _run_once(url: str, camera: str, camera_format: str | None, width: int, height: int, framerate: int):
    async with websockets.connect(url) as ws:
        print("Connected as Jetson. Waiting for start_stream...")
        client = NucJetson(ws, camera, camera_format, width, height, framerate)

        try:
            async for raw in ws:
                content = json.loads(raw)
                msg_type = content.get("type")
                print(f"<< {msg_type}: {json.dumps(content)[:200]}")

                if msg_type == "start_stream":
                    await client.handle_start_stream(content)
                elif msg_type == "sdp_answer":
                    await client.handle_sdp_answer(content)
                elif msg_type == "stop_stream":
                    await client.handle_stop_stream(content)
                elif msg_type == "error":
                    print(f"!! server error: {content.get('detail')}")
        finally:
            await client._teardown()


async def run(
    host: str,
    device_id: str,
    token: str,
    camera: str,
    camera_format: str | None,
    width: int,
    height: int,
    framerate: int,
    use_ssl: bool,
):
    """Connects and serves forever, reconnecting with backoff on any drop
    or failed connect attempt (Django not up yet, network blip, ...) —
    important when this runs as its own long-lived container instead of a
    one-shot local script."""
    scheme = "wss" if use_ssl else "ws"
    url = f"{scheme}://{host}/ws/jetson/{device_id}/?token={token}"
    while True:
        print(f"Connecting to {url}")
        try:
            await _run_once(url, camera, camera_format, width, height, framerate)
            print(f"Connection closed; reconnecting in {RECONNECT_DELAY}s...")
        except (websockets.exceptions.WebSocketException, OSError) as exc:
            print(f"Connect failed ({exc}); retrying in {RECONNECT_DELAY}s...")
        await asyncio.sleep(RECONNECT_DELAY)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default=HOST, help="Django host:port (env JETSON_MOCK_HOST)")
    parser.add_argument(
        "--device-id", default=DEVICE_ID, help="must match settings.JETSON_DEVICE_ID (env JETSON_MOCK_DEVICE_ID)"
    )
    parser.add_argument(
        "--token", default=TOKEN, help="must match settings.JETSON_AUTH_TOKEN (env JETSON_MOCK_TOKEN)"
    )
    parser.add_argument(
        "--camera",
        default=CAMERA,
        help="camera device/source, or 'auto' (default) to probe /dev/video* and pick the first working one "
        "(env JETSON_MOCK_VIDEO_DEVICE)",
    )
    parser.add_argument(
        "--camera-format",
        default="v4l2",
        help="ffmpeg input format: v4l2 (Linux, default), avfoundation (macOS), dshow (Windows)",
    )
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--framerate", type=int, default=15)
    parser.add_argument(
        "--ssl", dest="use_ssl", action="store_true", default=SSL, help="use wss:// instead of ws:// (env JETSON_MOCK_SSL)"
    )
    args = parser.parse_args()

    try:
        asyncio.run(
            run(
                args.host,
                args.device_id,
                args.token,
                args.camera,
                args.camera_format,
                args.width,
                args.height,
                args.framerate,
                args.use_ssl,
            )
        )
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
