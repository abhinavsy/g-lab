# jetson_mock

Stand-in for the real Jetson/NUC edge device. Not part of the Django
project — a separate runtime you point at a real camera to exercise the
full signaling + WebRTC + analysis path without real AI/inference hardware.

## nuc_capture_send.py

Run this **on the NUC** (or any Linux box with a webcam for local testing).
It:

1. connects to Django as the Jetson (`ws/jetson/<device_id>/`)
2. waits for `start_stream` (sent once someone starts a session from the
   app / `POST /api/sessions/start/`)
3. opens the real camera and offers it over WebRTC
4. once connected, streams **mock** analysis samples (hip/knee angle,
   speed, spasm flag) over the WebRTC data channel — replace
   `mock_analysis_sample()` with real inference output later, the wire
   format is already what `telemetry.AnalysisEvent` expects
5. tears down cleanly on `stop_stream`

```bash
uv run python jetson_mock/nuc_capture_send.py                 # auto-detects the camera
uv run python jetson_mock/nuc_capture_send.py --camera /dev/video2 --width 1280 --height 720
uv run python jetson_mock/nuc_capture_send.py --host 192.168.1.50:8000
```

`--camera` defaults to `auto`: it probes every `/dev/video*` node in order,
opens each one and requires it to actually deliver a frame (some v4l2 nodes
on a given board are metadata-only and never produce video), and uses the
first one that works. Pass an explicit `--camera /dev/videoN` to skip
probing.

Needs `JETSON_DEVICE_ID`/`JETSON_AUTH_TOKEN` (`--device-id`/`--token`) to
match the Django server's `.env`, and ffmpeg's v4l2 input available (any
recent ffmpeg build on Linux has it — aiortc's `MediaPlayer` uses it under
the hood, no extra install beyond the project's `aiortc` dependency).

To drive the other end of the exchange without a real Flutter build, pair
this with `mock_flutter_answer.py` at the repo root — it answers the offer,
optionally records the incoming video, and prints every analysis sample it
relays to Django.
