"""Interactive WS test client — watches AND drives BOTH sockets at once.

Unlike web_test_send.py (one role per process), this connects as both the
Jetson and the Flutter app in a single process, so you can see every
message sent/received on either side in one terminal — useful for watching
a full signaling exchange (sdp_offer/sdp_answer/ice_candidate) without
juggling two terminal windows.

Usage:
    python web_test_dual.py

Then type a JSON message prefixed with which socket to send it on:
    jetson: {"type": "sdp_offer", "session_id": "SES123", "sdp": "..."}
    flutter: {"type": "start_session", "patient_id": "PAT001"}

Everything sent or received on either socket prints labeled, e.g.:
    [JETSON  >>] {...}   -- sent on the jetson socket
    [FLUTTER <<] {...}   -- received on the flutter socket
"""
import asyncio
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


def label(role: str, direction: str) -> str:
    return f"[{role.upper():7} {direction}]"


async def receiver(role: str, ws):
    async for raw in ws:
        try:
            msg = json.loads(raw)
            printable = json.dumps(msg)
        except json.JSONDecodeError:
            printable = f"<non-JSON> {raw}"
        print(f"\n{label(role, '<<')} {printable}\n> ", end="", flush=True)


async def input_loop(sockets: dict):
    loop = asyncio.get_event_loop()
    print("Type '<role>: <json>' to send, e.g.  flutter: {\"type\": \"start_session\", \"patient_id\": \"PAT001\"}")
    while True:
        line = await loop.run_in_executor(None, input, "> ")
        line = line.strip()
        if not line:
            continue
        if ":" not in line:
            print("format is '<role>: <json>' (role = jetson or flutter)")
            continue
        role, _, payload = line.partition(":")
        role = role.strip().lower()
        payload = payload.strip()
        if role not in sockets:
            print(f"unknown role '{role}', use 'jetson' or 'flutter'")
            continue
        try:
            json.loads(payload)  # validate before sending
        except json.JSONDecodeError as e:
            print(f"not valid JSON: {e}")
            continue
        print(f"{label(role, '>>')} {payload}")
        await sockets[role].send(payload)


async def main():
    print("Connecting as jetson to", URLS["jetson"])
    print("Connecting as flutter to", URLS["flutter"])
    async with websockets.connect(URLS["jetson"]) as jetson_ws, websockets.connect(URLS["flutter"]) as flutter_ws:
        print("Both sockets connected.\n")
        sockets = {"jetson": jetson_ws, "flutter": flutter_ws}
        asyncio.create_task(receiver("jetson", jetson_ws))
        asyncio.create_task(receiver("flutter", flutter_ws))
        await input_loop(sockets)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
