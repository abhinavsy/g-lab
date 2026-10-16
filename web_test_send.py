"""Interactive WS test client — sends AND receives.

Usage:
  python web_test_send.py jetson    # connects as the Jetson device
  python web_test_send.py flutter   # connects as the Flutter app

Type a JSON message and hit enter to send it; incoming messages print
as they arrive on a background task.
"""
import asyncio
import json
import sys

import websockets

HOST = "127.0.0.1:8000"
DEVICE_ID = "JETSON001"
TOKEN = "changeme-dev-token"

ROLE = sys.argv[1] if len(sys.argv) > 1 else "flutter"
URL = (
    f"ws://{HOST}/ws/jetson/{DEVICE_ID}/?token={TOKEN}"
    if ROLE == "jetson"
    else f"ws://{HOST}/ws/app/?token={TOKEN}"
)


async def receiver(ws):
    async for raw in ws:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            print("<< non-JSON:", raw)
            continue
        print("\n<< " + json.dumps(msg))
        print(">> ", end="", flush=True)


async def main():
    print(f"Connecting as {ROLE} to {URL}")
    async with websockets.connect(URL) as ws:
        print("connected. Paste a JSON message and press enter (or blank line to skip).")
        asyncio.create_task(receiver(ws))
        loop = asyncio.get_event_loop()
        while True:
            line = await loop.run_in_executor(None, input, ">> ")
            line = line.strip()
            if not line:
                continue
            try:
                json.loads(line)  # validate it's JSON before sending
            except json.JSONDecodeError as e:
                print(f"not valid JSON: {e}")
                continue
            await ws.send(line)


asyncio.run(main())
