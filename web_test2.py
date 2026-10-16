import asyncio
import json
import websockets


HOST = "127.0.0.1:8000"
DEVICE_ID = "JETSON001"
TOKEN = "changeme-dev-token"

URL = f"ws://{HOST}/ws/jetson/{DEVICE_ID}/?token={TOKEN}"


async def read_messages():
    print(f"Connecting to: {URL}")

    async with websockets.connect(URL) as websocket:
        print("WebSocket connected")

        async for raw_message in websocket:
            try:
                message = json.loads(raw_message)
            except json.JSONDecodeError:
                print("Received non-JSON message:", raw_message)
                continue

            print("Received message:")
            print(json.dumps(message, indent=2))


asyncio.run(read_messages())