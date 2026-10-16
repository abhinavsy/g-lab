# Django Backend — Jetson → Django → Flutter WebRTC Signaling

Implements the Django side of the architecture in [`../README_WebRTC.md`](../README_WebRTC.md):
REST API + auth, WebSocket session control, WebRTC signaling relay, and
persistence to PostgreSQL/MinIO. Django never sits in the actual video
path — it only relays SDP/ICE and forwards validated commands.

## Stack

- Django 5 + Django REST Framework (REST API, JWT auth)
- Django Channels + `channels_redis` (WebSocket signaling, ASGI via Daphne)
- PostgreSQL (structured data), MinIO/S3 via `django-storages` (recordings)

## Setup

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # edit as needed

docker compose up -d   # postgres + redis + minio

python manage.py migrate
python manage.py createsuperuser
python manage.py runserver 0.0.0.0:8000        # dev (HTTP only)
# or, for WebSocket support:
daphne -b 0.0.0.0 -p 8000 config.asgi:application
```

Register a patient from `/admin/` (or the REST API). There's no
device/camera registration step — see below.

### One Jetson, no Device/Camera model

This project targets exactly **one** Jetson. There's no `Device` or
`Camera` database model or CRUD API — the device's identity and shared
secret live in settings/`.env` instead (`JETSON_DEVICE_ID`,
`JETSON_AUTH_TOKEN`; see `.env.example`). The Jetson process uses
`JETSON_AUTH_TOKEN` to authenticate its one signaling WebSocket
(`ws/jetson/<JETSON_DEVICE_ID>/?token=<JETSON_AUTH_TOKEN>`), which it then
multiplexes across however many cameras it has — Django never tracks
individual cameras or picks one to start a session against; one session
always covers all of them, and `session_id` alone (never `camera_id`) is
what every command/stream message carries.

Online/offline status is tracked in the cache (Redis-backed — see
`CACHES` in `config/settings.py`), set when the Jetson's WebSocket
connects/disconnects, and readable via `GET /api/device/status/`.

## REST API

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/auth/login/` | POST | Flutter user login → JWT access/refresh |
| `/api/patients/` | GET/POST | Patient CRUD |
| `/api/device/status/` | GET | The one Jetson's `device_id` + online status + last-seen |
| `/api/sessions/` | GET | List/inspect sessions |
| `/api/sessions/start/` | POST | `{"patient_id"}` → creates session, sends `start_stream` to the Jetson (all its cameras). No `device_id` needed — there's only one device |
| `/api/sessions/{session_id}/stop/` | POST | Stops the session (`stop_stream` to device) |
| `/api/sessions/{session_id}/command/` | POST | `{"command","params"}` device command |
| `/api/sessions/{session_id}/analysis/` | GET | Saved analysis samples |
| `/api/sessions/{session_id}/alerts/` | GET | Saved alerts |
| `/api/sessions/{session_id}/recordings/` | GET | Signed MinIO URLs for recording/clips |
| `/api/sessions/{session_id}/recordings/` | POST | Jetson uploads a finished recording/clip (multipart `.mp4`, `Authorization: Device <token>`) — Django writes it through to MinIO |

## WebSocket endpoints

- `ws://<host>/ws/app/?token=<jwt access token>` — Flutter app
- `ws://<host>/ws/jetson/<JETSON_DEVICE_ID>/?token=<JETSON_AUTH_TOKEN>` — the Jetson

Both speak newline-free JSON frames. Message `type`s (see
`streaming/consumers.py` for the full state machine):

| type | Sent by | Purpose |
|---|---|---|
| `start_session` | Flutter | `{"patient_id"}` — README #6, no `device_id` needed |
| `session_started` / `session_status` | Django | ack + status changes |
| `stop_session` | Flutter | `{"session_id"}` — README #19 |
| `device_command` | Flutter | `{"session_id","command","params"}` — README #15 |
| `start_stream` / `stop_stream` | Django → Jetson | forwarded from the above |
| `sdp_offer` | Jetson | WebRTC offer (Jetson is always the offerer — README #11) |
| `sdp_answer` | Flutter | WebRTC answer |
| `ice_candidate` | both | ICE candidate exchange |
| `webrtc_connected` | both | negotiation complete → session becomes `ACTIVE` |
| `analysis_data` | Flutter | relays what it received over the WebRTC data channel, for persistence — README #14 |
| `alert` | Jetson | e.g. `SPASM_DETECTED` — README #16 |
| `stream_stopped` | Jetson | teardown confirmed → session becomes `COMPLETED`/`FAILED` |

Signaling and status messages are relayed through a per-session Channels
group (`session_<id>`); Django tags each with the sender's role so a
consumer never echoes a message back to whoever sent it.

## Notes / production hardening

- `CORS_ALLOW_ALL_ORIGINS` and the open `ALLOWED_HOSTS` default assume a
  trusted local LAN, per README_WebRTC.md #22-#23. Lock these down for any
  deployment beyond that.
- `JETSON_AUTH_TOKEN` is a static shared secret suitable for a closed LAN;
  rotate it via `.env` + redeploy, and consider short-lived tokens if the
  Jetson ever connects over an untrusted network.
- STUN/TURN is intentionally not configured (README #23) — add it only if
  Jetson/Flutter end up on different networks.
