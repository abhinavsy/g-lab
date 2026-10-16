"""End-to-end smoke test: drives one full session lifecycle and verifies
every leg of it actually happened, instead of eyeballing three terminals.

Plays the Flutter side for real (REST calls + a genuine aiortc answerer,
same as mock_flutter_answer.py) against whatever is currently connected as
the Jetson — jetson_mock/nuc_capture_send.py (locally or in its own
container, see docker-compose.jetson-mock.yml), or real hardware. Start
that first; this script errors out early if no device is online.

What it checks, in order (README_WebRTC.md #6-#19, API_REFERENCE.md):
  1.  GET  /api/device/status/         -> device must be online
  2.  POST /api/sessions/start/        -> session created (STARTING)
  3.  ws/app/ connect                   -> receives Django's start_stream-
                                           triggered sdp_offer relay
  4.  answers the offer with aiortc, waits for the peer connection to
      reach "connected" and for {"type": "session_status", "status":
      "ACTIVE"} on the socket
  5.  collects analysis_data samples arriving on the WebRTC data channel
      and relays each one to Django over ws/app/ (this is the one leg
      mock_flutter_answer.py doesn't do — real Flutter apps must, per
      README_WebRTC.md #14)
  6.  after --duration seconds, POST /api/sessions/{id}/stop/
  7.  waits for {"type": "session_status", "status": "COMPLETED"}
  8.  GET  /api/sessions/{id}/analysis/ -> asserts at least one relayed
      sample actually landed in Postgres

Usage:
    python test_full_flow.py                       # 8s session against PAT001
    python test_full_flow.py --duration 20 --patient-id PAT001
    python test_full_flow.py --host 192.168.1.50:8000
    python test_full_flow.py --record out.mp4       # also save incoming video

Requires the project venv (aiortc, requests, websockets):
    uv run python test_full_flow.py
"""
import argparse
import asyncio
import json
import sys

import requests
import websockets
from aiortc import RTCPeerConnection, RTCSessionDescription
from aiortc.contrib.media import MediaRecorder
from aiortc.sdp import candidate_from_sdp, candidate_to_sdp

HOST = "127.0.0.1:8001"
TOKEN = "changeme-dev-token"  # AUTH_DISABLED=True (default) accepts any non-empty token


def fail(message: str) -> "NoReturn":
    print(f"\nFAILED: {message}")
    sys.exit(1)


def ok(message: str) -> None:
    print(f"OK:     {message}")


class FlowTest:
    def __init__(self, host: str, record_path: str | None):
        self.host = host
        self.base = f"http://{host}"
        self.record_path = record_path

        self.pc = RTCPeerConnection()
        self.recorder = MediaRecorder(record_path) if record_path else None
        self.ws = None
        self.session_id = None

        self.connected_event = asyncio.Event()
        self.active_event = asyncio.Event()
        self.completed_event = asyncio.Event()
        self.analysis_relayed = 0

        @self.pc.on("track")
        def on_track(track):
            ok(f"video track received (kind={track.kind})")
            if self.recorder:
                self.recorder.addTrack(track)

        @self.pc.on("datachannel")
        def on_datachannel(channel):
            ok(f"data channel received: label={channel.label}")

            @channel.on("message")
            def on_message(message):
                asyncio.ensure_future(self._relay_analysis(message))

        @self.pc.on("iceconnectionstatechange")
        async def on_ice_state_change():
            print(f"-- ICE connection state: {self.pc.iceConnectionState}")
            if self.pc.iceConnectionState in ("connected", "completed"):
                self.connected_event.set()

    # -- step 1: device online ------------------------------------------
    def check_device_online(self):
        resp = requests.get(f"{self.base}/api/device/status/")
        resp.raise_for_status()
        data = resp.json()
        if not data.get("online"):
            fail(
                f"device {data.get('device_id')} is not online — start jetson_mock/nuc_capture_send.py "
                "(or the real device) first"
            )
        ok(f"device {data['device_id']} online")

    # -- step 2: start session --------------------------------------------
    def start_session(self, patient_id: str) -> str:
        resp = requests.post(f"{self.base}/api/sessions/start/", json={"patient_id": patient_id})
        if resp.status_code != 201:
            fail(f"POST /api/sessions/start/ -> {resp.status_code} {resp.text}")
        data = resp.json()
        self.session_id = data["session_id"]
        ok(f"session {self.session_id} started (status={data['status']})")
        return self.session_id

    # -- step 6: stop session ----------------------------------------------
    def stop_session(self):
        resp = requests.post(f"{self.base}/api/sessions/{self.session_id}/stop/")
        if resp.status_code != 200:
            fail(f"POST /api/sessions/{self.session_id}/stop/ -> {resp.status_code} {resp.text}")
        ok(f"stop requested (status={resp.json()['status']})")

    # -- step 8: verify analysis persisted --------------------------------
    def check_analysis_persisted(self):
        resp = requests.get(f"{self.base}/api/sessions/{self.session_id}/analysis/")
        resp.raise_for_status()
        rows = resp.json()
        if not rows:
            fail("no analysis rows persisted in Postgres despite relaying samples")
        ok(f"{len(rows)} analysis row(s) persisted (e.g. {rows[0]})")

    async def send(self, message: dict):
        await self.ws.send(json.dumps(message))

    async def _relay_analysis(self, raw_message: str):
        """Mirrors what a real Flutter app must do (README_WebRTC.md #14):
        forward each data-channel analysis sample to Django over ws/app/ so
        it gets persisted. mock_flutter_answer.py skips this step."""
        try:
            payload = json.loads(raw_message)
        except json.JSONDecodeError:
            print(f"<< [data channel] non-JSON: {raw_message}")
            return
        self.analysis_relayed += 1
        print(f"<< [data channel] analysis #{self.analysis_relayed}: {json.dumps(payload)}")
        payload.setdefault("session_id", self.session_id)
        await self.send(payload)

    async def _handle_offer(self, content: dict):
        offer = RTCSessionDescription(sdp=content["sdp"], type="offer")
        await self.pc.setRemoteDescription(offer)
        if self.recorder:
            await self.recorder.start()
        answer = await self.pc.createAnswer()
        await self.pc.setLocalDescription(answer)
        await self.send({"type": "sdp_answer", "session_id": content.get("session_id"), "sdp": self.pc.localDescription.sdp})
        ok("sdp_offer received and answered")

    async def _handle_ice_candidate(self, content: dict):
        sdp = content.get("candidate")
        if not sdp:
            return
        candidate = candidate_from_sdp(sdp)
        candidate.sdpMid = content.get("sdpMid")
        candidate.sdpMLineIndex = content.get("sdpMLineIndex")
        await self.pc.addIceCandidate(candidate)

    async def _listen(self):
        async for raw in self.ws:
            content = json.loads(raw)
            msg_type = content.get("type")

            if msg_type == "sdp_offer":
                await self._handle_offer(content)
            elif msg_type == "ice_candidate":
                await self._handle_ice_candidate(content)
            elif msg_type == "session_status":
                print(f"<< session_status: {content.get('status')}")
                if content.get("status") == "ACTIVE":
                    self.active_event.set()
                elif content.get("status") in ("COMPLETED", "FAILED"):
                    self.completed_event.set()
            elif msg_type == "error":
                fail(f"server error: {content.get('detail')}")

    async def run(self, patient_id: str, duration: float, timeout: float):
        self.check_device_online()

        url = f"ws://{self.host}/ws/app/?token={TOKEN}"
        async with websockets.connect(url) as ws:
            self.ws = ws
            listener = asyncio.ensure_future(self._listen())
            try:
                self.start_session(patient_id)

                await asyncio.wait_for(self.connected_event.wait(), timeout=timeout)
                ok("WebRTC peer connection reached 'connected'")
                await asyncio.wait_for(self.active_event.wait(), timeout=timeout)
                ok("session reached ACTIVE")

                print(f"-- session ACTIVE, collecting analysis for {duration}s...")
                await asyncio.sleep(duration)

                if self.analysis_relayed == 0:
                    fail("no analysis_data samples arrived on the data channel in that window")
                ok(f"{self.analysis_relayed} analysis sample(s) relayed to Django")

                self.stop_session()
                await asyncio.wait_for(self.completed_event.wait(), timeout=timeout)
                ok("session reached COMPLETED")

                self.check_analysis_persisted()
                print("\nFULL FLOW PASSED — start_stream through stop_stream all verified.")
            except asyncio.TimeoutError:
                fail(f"timed out waiting for the next step (>{timeout}s)")
            finally:
                listener.cancel()
                if self.recorder:
                    await self.recorder.stop()
                await self.pc.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--patient-id", default="PAT001")
    parser.add_argument("--duration", type=float, default=8.0, help="seconds to stay ACTIVE collecting analysis")
    parser.add_argument("--timeout", type=float, default=15.0, help="seconds to wait for each step before failing")
    parser.add_argument("--record", default=None, metavar="PATH", help="also save incoming video to this file")
    args = parser.parse_args()

    test = FlowTest(args.host, args.record)
    try:
        asyncio.run(test.run(args.patient_id, args.duration, args.timeout))
    except KeyboardInterrupt:
        sys.exit(1)


if __name__ == "__main__":
    main()
