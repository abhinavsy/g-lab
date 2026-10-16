"""Passive dual-socket WS logger — always listening, no typing needed.

Connects as both the Jetson and the Flutter app and just prints every
message either side sends/receives, forever, auto-reconnecting if a socket
drops. Use this to leave running in a terminal (or `> log.txt &`) while you
drive the actual flow from elsewhere (mock_flutter_answer.py, jetson_mock,
the real Flutter app, curl against the REST API, ...).

Each line is labeled with who actually sent the message, not just which of
our two sockets it arrived on — an sdp_answer/sdp_offer/ice_candidate is
relayed through Django untouched, so it's tagged "flutter -> jetson" /
"jetson -> flutter"; everything else Django originates itself (start_stream,
session_status, error, ...) and is tagged "django -> jetson"/"django ->
flutter". For example:
    [12:00:01] [django -> jetson  ] {"type": "start_stream", "session_id": "SES..."}
    [12:00:01] [jetson -> flutter ] {"type": "sdp_offer", "session_id": "SES...", "sdp": "..."}
    [12:00:02] [flutter -> jetson ] {"type": "sdp_answer", "session_id": "SES...", "sdp": "..."}
    [12:00:02] [django -> flutter ] {"type": "session_status", "status": "ACTIVE"}

For sending messages yourself, use web_test_dual.py instead — this script
never writes to either socket.

Usage:
    python web_test_listen.py
    python web_test_listen.py > ws.log 2>&1 &   # log to file, run in background
"""
import asyncio
import datetime
import json
import sys

import websockets

HOST = "127.0.0.1:8001"
DEVICE_ID = "JETSON001"
TOKEN = "changeme-dev-token"

URLS = {
    "jetson": f"ws://{HOST}/ws/jetson/{DEVICE_ID}/?token={TOKEN}",
    "flutter": f"ws://{HOST}/ws/app/?token={TOKEN}",
}
print(URLS)
RECONNECT_DELAY = 2  # seconds

# Message types Django relays as-is between the two client roles (see
# streaming/consumers.py SIGNAL_PASSTHROUGH_TYPES) — a message of one of
# these types arriving on OUR jetson/flutter socket was actually sent by
# the *other* role, just passed through Django. Everything else arriving
# (start_stream, stop_stream, session_status, error, ...) originates from
# Django itself, not the other client.
FROM_FLUTTER_ON_JETSON_SOCKET = {"sdp_answer", "ice_candidate"}
FROM_JETSON_ON_FLUTTER_SOCKET = {"sdp_offer", "ice_candidate"}


def ts() -> str:
    return datetime.datetime.now().strftime("%H:%M:%S")


def origin_label(role: str, msg_type: str | None) -> str:
    """Who actually sent this, not just which socket it arrived on — e.g.
    an sdp_answer arriving on our jetson socket was relayed there by
    Django, but Flutter is the one that actually sent it."""
    if role == "jetson" and msg_type in FROM_FLUTTER_ON_JETSON_SOCKET:
        return "flutter -> jetson"
    if role == "flutter" and msg_type in FROM_JETSON_ON_FLUTTER_SOCKET:
        return "jetson -> flutter"
    return f"django -> {role}"


async def listen(role: str, url: str):
    while True:
        try:
            print(f"[{ts()}] [{role.upper():7}] connecting to {url}")
            async with websockets.connect(url) as ws:
                print(f"[{ts()}] [{role.upper():7}] connected")
                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                        printable = json.dumps(msg)
                        label = origin_label(role, msg.get("type"))
                    except json.JSONDecodeError:
                        printable = f"<non-JSON> {raw}"
                        label = f"? -> {role}"
                    print(f"[{ts()}] [{label:17}] {printable}")
            print(f"[{ts()}] [{role.upper():7}] connection closed, reconnecting in {RECONNECT_DELAY}s...")
        except (websockets.exceptions.WebSocketException, OSError) as exc:
            print(f"[{ts()}] [{role.upper():7}] connection error: {exc}; retrying in {RECONNECT_DELAY}s...")
        await asyncio.sleep(RECONNECT_DELAY)


async def main():
    await asyncio.gather(*(listen(role, url) for role, url in URLS.items()))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
