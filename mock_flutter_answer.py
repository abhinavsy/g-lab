"""Mock Flutter WebRTC peer — connects to Django's ws/app/ signaling socket,
waits for the Jetson's SDP offer, and answers it for real using aiortc
(README_WebRTC.md #10-#12: Jetson offers, Flutter answers, ICE exchanged,
then media flows peer-to-peer and never touches Django again).

This isn't just an echo of the SDP text — aiortc stands up a real
RTCPeerConnection, negotiates codecs against the Jetson's offer, and (if
--record is given) writes the incoming video track to a file, proving the
P2P media path actually works end to end.

Usage:
    python mock_flutter_answer.py                     # login with USERNAME/PASSWORD below
    python mock_flutter_answer.py --token <jwt>        # skip login, use an existing JWT
    python mock_flutter_answer.py --record out.mp4     # also save incoming video to a file
    python mock_flutter_answer.py --start-session PAT001   # send start_session after connecting

Requires the same deps declared in pyproject.toml (aiortc, websockets) —
run it inside the project venv, e.g. `uv run python mock_flutter_answer.py`.
"""
import argparse
import asyncio
import json
import sys

import requests
import websockets
from aiortc import RTCPeerConnection, RTCSessionDescription
from aiortc.contrib.media import MediaRecorder
from aiortc.mediastreams import MediaStreamError
from aiortc.sdp import candidate_from_sdp, candidate_to_sdp

HOST = "127.0.0.1:8001"
USERNAME = "admin"
PASSWORD = "changeme"


def get_jwt(host: str, username: str, password: str) -> str:
    resp = requests.post(f"http://{host}/api/auth/login/", json={"username": username, "password": password})
    resp.raise_for_status()
    return resp.json()["access"]


class MockFlutter:
    def __init__(self, ws, record_path: str | None):
        self.ws = ws
        self.record_path = record_path
        # No RTCPeerConnection yet — one is built fresh per session in
        # _new_peer_connection(), called from handle_offer(). A single
        # long-lived pc can't be reused across sessions: once the Jetson
        # closes its side at the end of a session (streaming/services.py
        # stop_session -> nuc_capture_send.py's teardown), this side's pc
        # also settles into signalingState "closed", and reusing a closed
        # RTCPeerConnection for the next session's offer raises
        # InvalidStateError.
        self.pc: RTCPeerConnection | None = None
        self.recorder = MediaRecorder(record_path) if record_path else None
        self._video_task: asyncio.Task | None = None

    def _new_peer_connection(self) -> RTCPeerConnection:
        pc = RTCPeerConnection()

        @pc.on("track")
        def on_track(track):
            print(f"<< track received: kind={track.kind}")
            if self.recorder:
                # MediaRecorder consumes the track itself once started.
                self.recorder.addTrack(track)
            elif track.kind == "video":
                # No --record given — nothing else would ever call
                # track.recv(), so without this there's no visible proof
                # frames are actually arriving beyond the one negotiation
                # print above. Pull frames ourselves and report progress.
                self._video_task = asyncio.ensure_future(self._consume_video(track))

        @pc.on("datachannel")
        def on_datachannel(channel):
            print(f"<< data channel received: label={channel.label}")

            @channel.on("message")
            def on_message(message):
                print(f"<< data channel message: {message}")

        @pc.on("icecandidate")
        async def on_icecandidate(candidate):
            if candidate is None:
                return
            await self.send(
                {
                    "type": "ice_candidate",
                    "candidate": candidate_to_sdp(candidate),
                    "sdpMid": candidate.sdpMid,
                    "sdpMLineIndex": candidate.sdpMLineIndex,
                }
            )

        return pc

    async def _consume_video(self, track):
        frame_count = 0
        try:
            while True:
                frame = await track.recv()
                frame_count += 1
                if frame_count == 1 or frame_count % 30 == 0:
                    print(f"<< video: frame {frame_count}, {frame.width}x{frame.height}")
        except MediaStreamError:
            # Normal end-of-track, e.g. the Jetson stopped the stream.
            pass

    async def send(self, message: dict):
        print(">> " + json.dumps(message))
        await self.ws.send(json.dumps(message))

    async def handle_offer(self, content: dict):
        if self.pc is not None:
            # Previous session's pc, if somehow still open (e.g. an offer
            # arrives before we noticed the last one closed) — close it
            # before replacing, don't just leak it.
            await self.pc.close()
        if self._video_task is not None:
            self._video_task.cancel()
            self._video_task = None
        self.pc = self._new_peer_connection()

        offer = RTCSessionDescription(sdp=content["sdp"], type="offer")
        await self.pc.setRemoteDescription(offer)

        if self.recorder:
            await self.recorder.start()

        answer = await self.pc.createAnswer()
        await self.pc.setLocalDescription(answer)

        await self.send(
            {
                "type": "sdp_answer",
                "session_id": content.get("session_id"),
                "sdp": self.pc.localDescription.sdp,
            }
        )

    async def handle_ice_candidate(self, content: dict):
        if self.pc is None:
            print("!! ice_candidate received with no active peer connection, ignoring")
            return
        sdp = content.get("candidate")
        if not sdp:
            return
        candidate = candidate_from_sdp(sdp)
        candidate.sdpMid = content.get("sdpMid")
        candidate.sdpMLineIndex = content.get("sdpMLineIndex")
        await self.pc.addIceCandidate(candidate)

    async def close(self):
        if self._video_task is not None:
            self._video_task.cancel()
            self._video_task = None
        if self.recorder:
            await self.recorder.stop()
        if self.pc is not None:
            await self.pc.close()


async def run(host: str, token: str, record_path: str | None, start_session_patient: str | None):
    url = f"ws://{host}/ws/app/?token={token}"
    print(f"Connecting to {url}")
    async with websockets.connect(url) as ws:
        print("WebSocket connected, waiting for Jetson SDP offer...")
        flutter = MockFlutter(ws, record_path)

        if start_session_patient:
            await flutter.send({"type": "start_session", "patient_id": start_session_patient})

        try:
            async for raw in ws:
                content = json.loads(raw)
                msg_type = content.get("type")
                print(f"<< {msg_type}: {json.dumps(content)[:200]}")

                if msg_type == "sdp_offer":
                    await flutter.handle_offer(content)
                elif msg_type == "ice_candidate":
                    await flutter.handle_ice_candidate(content)
                elif msg_type == "error":
                    print(f"!! server error: {content.get('detail')}")
        finally:
            await flutter.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--token", default=None, help="existing JWT access token; skips login")
    parser.add_argument("--username", default=USERNAME)
    parser.add_argument("--password", default=PASSWORD)
    parser.add_argument("--record", default=None, metavar="PATH", help="save incoming video to this file")
    parser.add_argument("--start-session", default=None, metavar="PATIENT_ID", help="send start_session on connect")
    args = parser.parse_args()

    # settings.AUTH_DISABLED=True (the local/LAN-testing default, see
    # config/settings.py) accepts any ?token= value on ws/app/ and never
    # checks it — so no login call is made here at all. Pass --token
    # explicitly (a real JWT from /api/auth/login/, e.g. via get_jwt())
    # once AUTH_DISABLED=False is set for real auth.
    token = args.token or "no-auth-placeholder"

    try:
        asyncio.run(run(args.host, token, args.record, args.start_session))
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()


