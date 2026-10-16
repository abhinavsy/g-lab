# API Reference — Full Call Sequence (1 → End)

Every API call in this project, in the order a real session actually makes
them — REST **and** WebSocket. Each entry says **why** it's called (where it
sits in the flow), the exact **request**, and the exact **response**. See
`README_WebRTC.md` for the architecture/diagrams this sequence implements,
and `README_FOLDER_STRUCTURE.md` for which app owns each endpoint.

**Base URL:** `http://<django-host>:8000` (same LAN, no TLS by default — see
`README_WebRTC.md`).
**Auth (REST):** `Authorization: Bearer <access_token>` header, except
login/refresh. Global default is `IsAuthenticated` (`config/settings.py`).
**Auth (WebSocket):** `?token=<jwt or JETSON_AUTH_TOKEN>` query param
(browsers can't set custom WS headers — see `streaming/auth.py`).

**No Device/Camera model.** This project targets exactly one Jetson — its
id/secret live in settings/`.env` (`JETSON_DEVICE_ID`, `JETSON_AUTH_TOKEN`;
see `streaming/services.py`), not a database row or CRUD API. There's no
`camera_id` anywhere either: a session always covers every camera the
Jetson has.

---

## Quick index

**Caller** = who actually makes this call. `Django (server)` means Django
itself sends it (over a group-send), not a client.

| # | Call | Transport | Caller | Why |
|---|---|---|---|---|
| 1 | `POST /api/auth/login/` | REST | Flutter (or any client) | Get a JWT to authenticate everything else |
| 2 | `POST /api/auth/refresh/` | REST | Flutter (or any client) | Renew an expired access token |
| 3 | `GET /api/patients/` | REST | Flutter | List patients to start a session for |
| 4 | `POST /api/patients/` | REST | Flutter | Register a new patient |
| 5 | `GET /api/device/status/` | REST | Flutter | See whether the Jetson is online before starting a session |
| 6 | `ws/app/` connect | WebSocket | Flutter | Open the live control channel |
| 7 | `{"type":"start_session"}` | WS (app) | Flutter | Start a session (or `POST /api/sessions/start/`) |
| 8 | `{"type":"start_stream"}` | WS (jetson, server→device) | Django (server) | Django tells Jetson to start streaming |
| 9 | `{"type":"sdp_offer"}` | WS (jetson→app, relayed) | Jetson | Jetson offers WebRTC video |
| 10 | `{"type":"sdp_answer"}` | WS (app→jetson, relayed) | Flutter | Flutter answers, negotiation completes |
| 11 | `{"type":"webrtc_connected"}` | WS (jetson→app, server-side) | Jetson | Jetson confirms media is flowing |
| 12 | `{"type":"analysis_data"}` | WS (app) | Flutter | Flutter relays live AI analysis to Django |
| 13 | `{"type":"alert"}` | WS (jetson) | Jetson | Jetson reports e.g. spasm detected |
| 14 | `{"type":"device_command"}` | WS (app) or `POST /api/sessions/{id}/command/` | Flutter | Flutter sends PAUSE/RESUME/SET_SPEED/... |
| 15 | `{"type":"stop_session"}` | WS (app) or `POST /api/sessions/{id}/stop/` | Flutter | End the session |
| 16 | `{"type":"stop_stream"}` → `{"type":"stream_stopped"}` | WS (jetson) | Django (server) → Jetson | Jetson tears down camera/AI/WebRTC |
| 17 | `GET /api/sessions/{id}/analysis/` | REST | Flutter or dashboard | Read back saved analysis history |
| 18 | `GET /api/sessions/{id}/alerts/` | REST | Flutter or dashboard | Read back saved alert history |
| 19 | `GET /api/sessions/{id}/recordings/` | REST | Flutter or dashboard | Get signed MinIO URLs for the recording/clips |
| 19a | `POST /api/sessions/{id}/recordings/` | REST | **Jetson** | Jetson uploads the finished recording/clip |
| 20 | `GET /api/sessions/`, `GET /api/sessions/{id}/` | REST | Flutter or dashboard | List/inspect sessions |
| 21 | `GET /api/dashboard/summary\|sessions\|alerts\|analysis/` | REST | Dashboard | Cross-session overview (not scoped to one session) |

---

## 1. `POST /api/auth/login/`

**Why:** First call, always. Every other REST call and both WebSocket
connections need the JWT this returns.

**Request**
```json
{"username": "admin", "password": "admin"}
```

**Response `200`**
```json
{"refresh": "<refresh-jwt>", "access": "<access-jwt>"}
```
`access` lives 8 hours, `refresh` 7 days (`SIMPLE_JWT` in `config/settings.py`).

---

## 2. `POST /api/auth/refresh/`

**Why:** Called once the 8-hour access token expires, instead of logging in
again.

**Request**
```json
{"refresh": "<refresh-jwt>"}
```

**Response `200`**
```json
{"access": "<new-access-jwt>"}
```

---

## 3-4. `GET /api/patients/`, `POST /api/patients/`

**Why:** Flutter needs a `patient_id` to start a session (#7). Full CRUD —
the only model exposed for direct create/edit via the API (there's no
device/camera model at all; see `jetson_mock/README.md` for how the Jetson
itself is configured).

Lives in the `patient` app (`patient/views.py`, `PatientViewSet`).

**`GET` response `200`**
```json
[
  {
    "id": 1, "patient_id": "PAT001", "name": "Jane Doe",
    "date_of_birth": "1990-05-14", "age": 36, "gender": "FEMALE",
    "phone": "", "email": "", "address": "", "diagnosis": "",
    "emergency_contact_name": "", "emergency_contact_phone": "",
    "notes": "", "is_active": true,
    "session_count": 92, "last_session_at": "2026-09-04T08:52:08Z",
    "created_at": "2026-08-17T10:00:00Z", "updated_at": "2026-10-16T05:39:36Z"
  }
]
```
`age`, `session_count`, `last_session_at`, `created_at`, `updated_at` are
read-only. `gender` is one of `MALE`, `FEMALE`, `OTHER`, `UNSPECIFIED`
(default).

**`POST` request** — only `patient_id` and `name` are required:
```json
{"patient_id": "PAT001", "name": "Jane Doe", "date_of_birth": "1990-05-14", "gender": "FEMALE", "notes": "optional"}
```
**Response `201`**: same shape as one list item.

Also available: `GET/PUT/PATCH/DELETE /api/patients/{patient_id}/` (standard
`ModelViewSet`, `lookup_field="patient_id"`). `DELETE` returns `409` while
the patient has sessions (`Session.patient` is `PROTECT`) — set
`is_active: false` instead.

### Session history: `GET /api/patients/{patient_id}/sessions/`

The patient's sessions, newest first, each with a summary of the values
received from the Jetson (relayed by Flutter as `analysis_data`, see #14).
Optional `?status=` filter (`STARTING`, `ACTIVE`, `STOPPING`, `COMPLETED`,
`FAILED`; anything else is `400`).

**Response `200`**
```json
[
  {
    "id": 34, "session_id": "SESAB48C22C", "patient_id": "PAT001",
    "device_id": "JETSON001", "status": "COMPLETED",
    "created_at": "2026-09-02T10:53:02Z", "started_at": "2026-09-02T10:53:02Z",
    "ended_at": "2026-09-02T10:53:06Z", "duration_seconds": 4.62,
    "sample_count": 5, "spasm_count": 1, "avg_speed": 1.58, "max_speed": 1.99,
    "alert_count": 0, "recording_count": 0
  }
]
```
`duration_seconds` is `null` until the session has both started and ended;
`avg_speed`/`max_speed` are `null` when no samples were received.

### Session detail: `GET /api/patients/{patient_id}/sessions/{session_id}/`

Same fields as one history row, plus every Jetson sample (in arrival
order), alerts and recordings. `404` if the session doesn't belong to the
patient. Each sample's `values` is the payload exactly as received, minus
the `type`/`session_id` envelope.

```json
{
  "session_id": "SESAB48C22C", "...": "summary fields as above",
  "samples": [
    {"id": 54, "recorded_at": "2026-09-02T10:53:02Z",
     "values": {"speed": 1.99, "hip_angle": 26.3, "knee_angle": 57.3, "spasm_detected": false}}
  ],
  "report": {"...": "the session report below, or null"},
  "alerts": [],
  "recordings": []
}
```

History rows also carry `has_report` (whether Flutter has saved a report).

### Session report: `/api/sessions/{session_id}/report/`

The "Report of individual session" data Flutter sends, saved as
`patient.SessionReport` (one per session, linked to the patient).

- `GET` — the saved report (`404` if none yet).
- `POST` / `PUT` / `PATCH` — create or update. Only the fields sent are
  changed, so `PATCH {"remarks": "..."}` is "Add Remark". `201` on create,
  `200` on update, `400` on a bad value (e.g. non-numeric `cadence`).
- Same thing over the Flutter WebSocket: `{"type": "session_report",
  "session_id": "SES...", ...fields}` → `{"type": "session_report_saved",
  "session_id": "SES...", "created": true}`.

All fields are optional. Anything not listed is still kept (merged into the
report's `raw_payload`).

```json
{
  "test_type": "Walking Test", "system_duration_seconds": 1800,
  "step_length": 0.62, "stride_length": 1.21, "step_width": 0.1,
  "foot_rotation_angle": 7.5, "walking_velocity": 1.1,
  "cadence": 104, "step_time": 0.58, "stride_time": 1.16,
  "stance_phase": 60.5, "swing_phase": 39.5,
  "hip_flexion": 32.5, "hip_extension": 10.2, "knee_flexion": 60.1,
  "knee_extension": 2.0, "ankle_dorsiflexion": 12.0, "ankle_plantarflexion": 18.0,
  "foot_pressure_average": {"left": [[0, 1], [2, 3]], "right": [[1, 1], [2, 2]]},
  "foot_pressure_maximum": {"left": [[...]], "right": [[...]]},
  "cop_data": {"left": [[x, y], ...], "right": [[x, y], ...]},
  "emg_tibialis_anterior": [0.1, 0.4, 0.2],
  "emg_medial_gastrocnemius": [0.2, 0.3, 0.1],
  "remarks": "Good symmetry"
}
```
Units: lengths/widths m, velocity m/s, cadence steps/min, times s,
stance/swing % of gait cycle, angles degrees. The JSON fields
(`foot_pressure_*`, `cop_data`, `emg_*`) are stored as sent — their shape
is up to the Flutter/Jetson side.

---

## 5. `GET /api/device/status/`

**Why:** To check the Jetson is online before starting a session —
`start_session` (#7) will reject the call if it isn't. No Device model: this
just reads the cache-backed online flag that `JetsonConsumer.connect`/
`disconnect` sets (`streaming/services.py` `mark_device_online`/
`mark_device_offline`/`is_device_online`), keyed off the one configured
`settings.JETSON_DEVICE_ID`.

**Response `200`**
```json
{"device_id": "JETSON001", "online": true, "last_seen_at": "2026-08-17T10:05:00Z"}
```
`last_seen_at` is the ISO timestamp of the most recent `connect`; `null` if
the Jetson has never connected (or the cache was cleared).

---

## 6. Connect `ws/app/?token=<access>`

**Why:** Session control, WebRTC signaling relay, and analysis relay all
happen over this one persistent socket — opened once, right after login,
kept open for the life of the Flutter session (`streaming/consumers.py`
`FlutterConsumer`).

No request/response — it's a connection. Server closes with code `4001` if
the token doesn't resolve to an authenticated user.

---

## 7. `{"type": "start_session"}` (over `ws/app/`)

**Why:** Kicks off the whole session lifecycle. (A REST equivalent exists —
`POST /api/sessions/start/`, same body/validation, used by e.g. a web
dashboard that isn't holding the socket open yet — but the WebSocket path is
what the real Flutter app uses, since it needs the socket open anyway for
signaling.)

**Send**
```json
{"type": "start_session", "patient_id": "PAT001"}
```
No `device_id` needed — there's only one Jetson, targeted by
`settings.JETSON_DEVICE_ID`. (A `device_id` field is still accepted for
forward-compat, but it must match that value or the call fails.)

**Receive** (success)
```json
{"type": "session_started", "session_id": "SES1A2B3C4D", "status": "STARTING"}
```

**Receive** (failure) — same shape used for every WS error
```json
{"type": "error", "detail": "Device online?"}
```

**Validation** (`streaming/services.py` `start_session`), in order: patient
must exist; the Jetson must be online (`is_device_online()`); no other
`STARTING`/`ACTIVE` session already running (there's only one device, so
this is a global check, not per-device). One session covers every camera
the Jetson has — there's no per-camera selection or concurrency here.

**REST equivalent:** `POST /api/sessions/start/` with the same body →
`201` with the full `Session` object (see #20), or `400 {"detail": "..."}`.

---

## 8. `{"type": "start_stream"}` (Django → Jetson, server-initiated)

**Why:** Django tells the actual/mock Jetson to start capturing — this is
what `start_session` (#7) triggers server-side, sent to the Jetson's
`ws/jetson/<JETSON_DEVICE_ID>/` socket. Not something a client calls
directly; listed here because it's the next thing that happens in the flow.

**Jetson receives**
```json
{"type": "start_stream", "session_id": "SES1A2B3C4D"}
```
No `camera_id` — the Jetson starts capturing on every camera it has for
this session.

---

## 9. `{"type": "sdp_offer"}` (Jetson → Django → Flutter, relayed)

**Why:** Jetson is the WebRTC media sender, so it creates the SDP offer
once it's ready to stream (README_WebRTC.md #11). Django relays this
untouched — it's one of `SIGNAL_PASSTHROUGH_TYPES` in
`streaming/consumers.py`, so the payload shape is defined by convention
between the two ends, not by Django.

**Jetson sends (on `ws/jetson/`)**
```json
{"type": "sdp_offer", "session_id": "SES1A2B3C4D", "sdp": "v=0...", "sdp_type": "offer"}
```
**Flutter receives the same payload on `ws/app/`.**

`jetson_mock`/`flutter_app_mock` use **non-trickle ICE**: this `sdp` string
already has ICE candidates baked in (both sides wait for gathering to
finish before sending), so no separate `ice_candidate` messages are needed
in this project's setup — though the type is still supported/relayed if
either side chooses trickle ICE instead.

---

## 10. `{"type": "sdp_answer"}` (Flutter → Django → Jetson, relayed)

**Why:** Flutter answers the offer, completing SDP negotiation
(README_WebRTC.md #11).

**Flutter sends (on `ws/app/`)**
```json
{"type": "sdp_answer", "session_id": "SES1A2B3C4D", "sdp": "v=0...", "sdp_type": "answer"}
```
**Jetson receives the same payload on `ws/jetson/`.**

---

## 11. `{"type": "webrtc_connected"}` (Jetson → Django)

**Why:** Once ICE/DTLS finish and the peer connection is actually
`connected`, Jetson tells Django so the session status flips
`STARTING` → `ACTIVE` (`streaming/services.py` `mark_session_active`).

**Jetson sends (on `ws/jetson/`)**
```json
{"type": "webrtc_connected", "session_id": "SES1A2B3C4D"}
```

**Django broadcasts to the session group (both Jetson and Flutter get this,
tagged so the sender doesn't echo it back to itself):**
```json
{"type": "session_status", "session_id": "SES1A2B3C4D", "status": "ACTIVE"}
```

From here, actual video flows **Jetson → Flutter directly over WebRTC** —
Django is out of the media path entirely.

---

## 12. `{"type": "analysis_data"}` (Flutter → Django)

**Why:** The one genuine **Flutter → Django data transfer** in this whole
system (see `telemetry/` app). Analysis (hip/knee angle, speed, spasm flag)
arrives at Flutter from Jetson over the WebRTC *data channel* — Django never
sees that leg — so Flutter relays it here to get it persisted.

**Flutter sends (on `ws/app/`)**
```json
{
  "type": "analysis_data",
  "session_id": "SES1A2B3C4D",
  "hip_angle_left": 32.5,
  "hip_angle_right": 31.0,
  "knee_angle_left": 45.2,
  "knee_angle_right": 44.0,
  "speed": 1.2,
  "spasm_detected": false
}
```
No response is sent back for this one — it's fire-and-forget (see
`telemetry/services.py` `record_analysis`, called from
`FlutterConsumer._handle_analysis_data`). Read it back later via #17.

---

## 13. `{"type": "alert"}` (Jetson → Django)

**Why:** Jetson-side detection event (e.g. spasm), unlike analysis this
comes to Django **directly from Jetson**, not relayed via Flutter.

**Jetson sends (on `ws/jetson/`)**
```json
{
  "type": "alert",
  "session_id": "SES1A2B3C4D",
  "alert_type": "SPASM_DETECTED",
  "message": "optional text",
  "payload": {"any": "extra json"}
}
```

**Django persists it, then broadcasts to the session group (Flutter
receives this live):**
```json
{"type": "alert", "alert_type": "SPASM_DETECTED", "message": "optional text", "payload": {}}
```
`alert_type` is one of `SPASM_DETECTED` / `DEVICE_OFFLINE` / `OTHER`.

---

## 14. `{"type": "device_command"}` (Flutter → Django → Jetson)

**Why:** All device control (pause the exercise, change speed/resistance,
etc.) is Flutter-initiated (README_WebRTC.md #15).

**Flutter sends (on `ws/app/`)**
```json
{"type": "device_command", "session_id": "SES1A2B3C4D", "command": "SET_SPEED", "params": {"value": 3}}
```
`command` ∈ `START, STOP, PAUSE, RESUME, SET_SPEED, SET_RESISTANCE, CHANGE_MODE`.

No ack over the socket — errors come back as `{"type": "error", "detail": "..."}`
(e.g. `"Session is not active."` if the session isn't `STARTING`/`ACTIVE`).

**Jetson receives (on `ws/jetson/`)**
```json
{"type": "device_command", "session_id": "SES1A2B3C4D", "command": "SET_SPEED", "params": {"value": 3}}
```

**REST equivalent:** `POST /api/sessions/{session_id}/command/`
```json
{"command": "SET_SPEED", "params": {"value": 3}}
```
→ `202 Accepted` (no body) or `400 {"detail": "..."}`.

---

## 15. `{"type": "stop_session"}` (over `ws/app/`)

**Why:** Ends the session — flips status to `STOPPING` and tells Jetson to
tear down.

**Send**
```json
{"type": "stop_session", "session_id": "SES1A2B3C4D"}
```

**Receive**
```json
{"type": "session_status", "session_id": "SES1A2B3C4D", "status": "STOPPING"}
```

**REST equivalent:** `POST /api/sessions/{session_id}/stop/` → `200` with
the full `Session` object, or `400 {"detail": "Session is not active (status=...)."}`.

---

## 16. `{"type": "stop_stream"}` → `{"type": "stream_stopped"}`

**Why:** Server tells Jetson to tear down (triggered by #15); Jetson
confirms once camera/AI/WebRTC + recording finalize are actually done
(README_WebRTC.md #19) — only then is the session really `COMPLETED`.

**Jetson receives (on `ws/jetson/`)**
```json
{"type": "stop_stream", "session_id": "SES1A2B3C4D"}
```

**Jetson sends back once torn down**
```json
{"type": "stream_stopped", "session_id": "SES1A2B3C4D", "failed": false}
```

**Django broadcasts to the session group (final status Flutter sees):**
```json
{"type": "session_status", "session_id": "SES1A2B3C4D", "status": "COMPLETED"}
```
(`"status": "FAILED"` if Jetson sent `"failed": true`.)

---

## 17. `GET /api/sessions/{session_id}/analysis/`

**Why:** Pull the analysis history saved via #12 — e.g. to show a chart
after the session ends, or to debug what got persisted. This is a plain
REST read; nothing here is pushed live over the socket after the fact (that
already happened in real time via #12's persistence + whatever `alert`/
`session_status` broadcasts occurred).

**Response `200`**
```json
[
  {"id": 1, "hip_angle_left": 32.5, "hip_angle_right": 31.0, "knee_angle_left": 45.2, "knee_angle_right": 44.0, "speed": 1.2, "spasm_detected": false, "raw_payload": {...}, "recorded_at": "2026-08-17T10:10:00Z"}
]
```
(`telemetry/views.py` `SessionAnalysisListView`.)

---

## 18. `GET /api/sessions/{session_id}/alerts/`

**Why:** Pull the alert history for one session (already-persisted, saved
via #13).

**Response `200`**
```json
[
  {"id": 1, "alert_type": "SPASM_DETECTED", "message": "...", "payload": {}, "created_at": "2026-08-17T10:11:00Z"}
]
```

---

## 19. `GET` / `POST` `/api/sessions/{session_id}/recordings/`

**Why:** `GET` — playable/downloadable URLs for the session's recording +
clips once it's finished. `POST` — how the file actually gets there: Jetson
uploads its finalized recording/clip through Django (README_WebRTC.md #17,
#19), and Django writes it through to MinIO (`Recording.file`, `S3Storage`
backend, `config/settings.py` `STORAGES`) rather than the device touching
MinIO itself.

### `GET` (caller: Flutter or dashboard)

**Response `200`**
```json
[
  {"id": 1, "clip_index": 0, "duration_seconds": 42.1, "created_at": "...", "url": "http://minio.../recordings/sessions/SES1A2B3C4D/clip0.mp4?X-Amz-...=..."}
]
```
`url` is a MinIO/S3 pre-signed URL, valid for `AWS_QUERYSTRING_EXPIRE`
(3600s / 1 hour — `config/settings.py`).

### `POST` (caller: **Jetson only**)

Sent once per finished clip, right after "Finalize Recording" in the
session-stop sequence (#16). Not something Flutter ever calls — Flutter
only ever has the live WebRTC stream, never the raw file.

**Auth:** `Authorization: Device <JETSON_AUTH_TOKEN>` — **not** the JWT
bearer token used everywhere else. No Device model/row — Jetson presents
the same settings-based shared secret it uses on `ws/jetson/`
(`streaming/authentication.py` `DeviceTokenAuthentication`, checked against
the session's own `device_id` by `streaming/permissions.py`
`IsAuthenticatedOrSessionDevice`).

**Request:** `multipart/form-data`
| field | type | required | notes |
|---|---|---|---|
| `file` | file | yes | the finished `.mp4` (H.264) from the Jetson's GStreamer pipeline — `recording.mp4` / `clip_001.mp4` / ... |
| `clip_index` | int | no (default `0`) | ordering within the session |
| `duration_seconds` | float | no | clip length |

**Response `201`** — same shape as one `GET` list item:
```json
{"id": 3, "clip_index": 0, "duration_seconds": 42.1, "created_at": "2026-08-18T10:20:00Z", "url": "http://minio.../..."}
```

**Why not over the WebSocket instead:** `JetsonConsumer`/`FlutterConsumer`
are JSON-only (`AsyncJsonWebsocketConsumer`) and that socket also carries
time-sensitive signaling — pushing a multi-MB/GB file through it would need
base64 (~33% size bloat) or a hand-rolled chunk protocol, and could block
control messages. A single multipart `POST` is the standard tool for a
large one-shot binary upload.

---

## 20. `GET /api/sessions/`, `GET /api/sessions/{session_id}/`

**Why:** List all sessions or inspect one — e.g. a history screen, or
polling status instead of/alongside the WebSocket. Read-only (sessions are
only created via #7, and only transitioned via #15 or the Jetson-driven
messages, never via a raw PATCH/PUT here).

**Response `200`** (list) / same single object (retrieve)
```json
{
  "id": 1,
  "session_id": "SES1A2B3C4D",
  "patient_id": "PAT001",
  "device_id": "JETSON001",
  "status": "ACTIVE",
  "created_at": "...",
  "started_at": "...",
  "ended_at": null
}
```
`status` ∈ `STARTING, ACTIVE, STOPPING, COMPLETED, FAILED`. `device_id` here
is a denormalized label recorded at start time (always
`settings.JETSON_DEVICE_ID` today), not a foreign key — there's no Device
model to join against.

---

## 21. `GET /api/dashboard/{summary|sessions|alerts|analysis}/`

**Why:** Everything above is either global-CRUD (#3-4) or scoped to one
session (#17-20). `dashboard/` adds the cross-session overview those don't
cover — e.g. an admin screen showing *all* recent alerts/analysis, not just
one session's.

**`GET /api/dashboard/summary/` → `200`**
```json
{
  "patients": 12,
  "monitored_patients": 11,
  "device": {"device_id": "JETSON001", "online": true},
  "sessions": {"total": 40, "this_week": 6, "active": 1}
}
```
`monitored_patients` = patients with `is_active: true` ("Total monitored
patients" tile). `sessions.this_week` = sessions created since Monday 00:00
of the current week, server time zone (UTC) ("Sessions tracked this week"
tile).

**`GET /api/dashboard/sessions/` → `200`**: same shape as #20's list, all
sessions, newest first.

**`GET /api/dashboard/alerts/` → `200`**: same shape as #18, but across
*all* sessions, newest first, capped at 200 rows.

**`GET /api/dashboard/analysis/` → `200`**: same shape as #17, but across
*all* sessions, newest first, capped at 200 rows.

---

## Error shape reference

| Transport | Shape | When |
|---|---|---|
| REST | `400 {"detail": "<message>"}` | Business-rule failure (`streaming.services.ValidationError`) |
| REST | `400 {"<field>": ["..."]}` | Serializer validation failure (bad/missing input) |
| REST | `401` | Missing/invalid/expired JWT |
| WebSocket | `{"type": "error", "detail": "<message>"}` | Any failure on `ws/app/` |
| WebSocket | connection closed, code `4001` | Bad/missing auth token on connect (either socket) |
