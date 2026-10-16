# Software Requirements Specification (SRS)

**Document ID:** SRS-GLAB-01 · **Project:** g-lab · **Status:** Draft v0.1
**Traces to:** [SDP-GLAB-01](01-software-development-plan.md) · **Traces forward to:** [SADD-GLAB-01](03-software-architectural-design.md), [SDD-GLAB-01](04-software-detailed-design.md)

---

## 1. Purpose and Scope

This SRS states what the Django backend (`config`, `streaming`, `telemetry`, `dashboard`) shall do, how fast, and how safely, as the coordinator between one NVIDIA Jetson edge device and a Flutter clinical app. It does not specify Jetson-side AI/inference behavior or Flutter UI behavior — only the interfaces and guarantees g-lab provides to them.

## 2. Definitions and Acronyms

| Term | Meaning |
|---|---|
| SDP (protocol) | Session Description Protocol — WebRTC offer/answer payload. Not to be confused with the *Software Development Plan* document. |
| Session | One stream/monitoring run, covering all of the Jetson's cameras, from `start_session` to `COMPLETED`/`FAILED`. |
| Device | The single Jetson edge unit; identified by `JETSON_DEVICE_ID`, authenticated by `JETSON_AUTH_TOKEN`. Not a database entity. |
| Control plane | Session lifecycle, commands, signaling, alerts — relayed through Django. |
| Media plane | The actual WebRTC video and the analysis data channel — Jetson → Flutter directly, never through Django. |
| Analysis event | A single AI-inference sample (hip angle, knee angle, speed, spasm flag) relayed Flutter → Django for persistence. |

## 3. System Context

```
        REST / WebSocket                 WebSocket (signaling, commands)
Flutter ─────────────────────► Django ─────────────────────────────────► Jetson
   ▲                              │                                        │
   │        WebRTC (video + data channel, direct, no Django)               │
   └────────────────────────────────────────────────────────────────────── ┘

Django ──► PostgreSQL (Patients, Sessions, Alerts, Recordings metadata, Analysis events)
Django ──► MinIO       (recording/clip files)
Django ──► Redis       (Channels layer, device online/offline cache)
```

Full flow reference: [README_WebRTC.md](../../README_WebRTC.md).

## 4. Functional Requirements

### 4.1 Authentication

| ID | Requirement |
|---|---|
| REQ-F-001 | The system shall authenticate Flutter users via `POST /api/auth/login/`, returning a JWT access/refresh token pair on valid credentials. |
| REQ-F-002 | The system shall require a valid JWT on `ws/app/?token=...` and reject the connection otherwise. |
| REQ-F-003 | The system shall authenticate the Jetson's signaling connection (`ws/jetson/<JETSON_DEVICE_ID>/?token=...`) against the configured `JETSON_AUTH_TOKEN`, independent of the Django user/JWT system. |
| REQ-F-004 | The system shall authenticate Jetson recording uploads via an `Authorization: Device <token>` header validated against `JETSON_AUTH_TOKEN`, not JWT. |

### 4.2 Patient Management

| ID | Requirement |
|---|---|
| REQ-F-010 | The system shall provide CRUD access to `Patient` records (`patient_id`, `name`, `notes`) via `/api/patients/`. |
| REQ-F-011 | The system shall enforce `patient_id` uniqueness. |
| REQ-F-012 | The system shall prevent deletion of a `Patient` referenced by any `Session` (`on_delete=PROTECT`). |

### 4.3 Device Status

| ID | Requirement |
|---|---|
| REQ-F-020 | The system shall expose the single device's `device_id`, online/offline status, and last-seen time via `GET /api/device/status/`. |
| REQ-F-021 | The system shall mark the device online when its signaling WebSocket connects and offline when it disconnects. |
| REQ-F-022 | The system shall not persist device online/offline status in PostgreSQL; it is runtime state only (cache-backed). |

### 4.4 Session Lifecycle

| ID | Requirement |
|---|---|
| REQ-F-030 | The system shall accept a session-start request (`POST /api/sessions/start/` or `start_session` over WebSocket) carrying only `patient_id`; `device_id` is optional and, if present, must equal the configured `JETSON_DEVICE_ID` or the request shall be rejected. |
| REQ-F-031 | Before creating a session, the system shall validate, in order: requester is authenticated, `patient_id` refers to an existing `Patient`, the device is online, and no other session is currently active — creating the session only if all hold. |
| REQ-F-032 | The system shall assign each session a unique, system-generated `session_id` (format `SES########`) and never accept a client-supplied one. |
| REQ-F-033 | The system shall drive session status through `STARTING → ACTIVE → STOPPING → COMPLETED`, with `FAILED` reachable from any non-terminal state. |
| REQ-F-034 | On session start, the system shall send a `start_stream` command to the Jetson carrying the new `session_id`. |
| REQ-F-035 | On session stop (`POST /api/sessions/{session_id}/stop/` or `stop_session` over WebSocket), the system shall send `stop_stream` to the Jetson and transition the session toward `COMPLETED`. |
| REQ-F-036 | The system shall provide session listing and single-session retrieval via `GET /api/sessions/`. |
| REQ-F-037 | A session shall cover all cameras on the device simultaneously; the protocol shall carry `session_id` only, never a per-camera identifier. |

### 4.5 Device Commands

| ID | Requirement |
|---|---|
| REQ-F-040 | The system shall accept device commands (`START`, `STOP`, `PAUSE`, `RESUME`, `SET_SPEED`, `SET_RESISTANCE`, `CHANGE_MODE`, ...) from Flutter via `POST /api/sessions/{session_id}/command/` or the `device_command` WebSocket message. |
| REQ-F-041 | The system shall validate that the target session exists and is active before forwarding a command to the Jetson. |
| REQ-F-042 | The system shall forward a validated command to the Jetson as a WebSocket message scoped to the session's Channels group. |

### 4.6 WebRTC Signaling Relay

| ID | Requirement |
|---|---|
| REQ-F-050 | The system shall relay `sdp_offer` from Jetson to Flutter, `sdp_answer` from Flutter to Jetson, and `ice_candidate` in both directions, without inspecting or modifying the payload. |
| REQ-F-051 | The system shall never originate an SDP offer or answer itself — it is a relay only. |
| REQ-F-052 | The system shall route every signaling and status message through a per-session Channels group (`session_<id>`) and shall not echo a message back to its sender. |
| REQ-F-053 | The system shall transition a session to `ACTIVE` on receipt of `webrtc_connected` from either party. |

### 4.7 Analysis Data

| ID | Requirement |
|---|---|
| REQ-F-060 | The system shall accept `analysis_data` messages from Flutter over `ws/app/`, relaying what Flutter received from the Jetson over the WebRTC data channel. |
| REQ-F-061 | The system shall persist each analysis sample as an `AnalysisEvent` (`hip_angle`, `knee_angle`, `speed`, `spasm_detected`, raw payload, timestamp) linked to its session. |
| REQ-F-062 | The system shall provide retrieval of a session's analysis samples via `GET /api/sessions/{session_id}/analysis/`. |
| REQ-F-063 | The system shall accept and persist an analysis sample even if optional numeric fields (`hip_angle`, `knee_angle`, `speed`) are absent. |

### 4.8 Alerts

| ID | Requirement |
|---|---|
| REQ-F-070 | The system shall accept `alert` messages sent directly by the Jetson (e.g. `SPASM_DETECTED`) over its signaling WebSocket. |
| REQ-F-071 | The system shall persist every alert as an `AlertEvent` (type, message, payload, timestamp) linked to its session before or concurrently with forwarding it. |
| REQ-F-072 | The system shall forward each alert to the Flutter client(s) in the same session's group in near-real-time. |
| REQ-F-073 | The system shall provide retrieval of a session's alerts via `GET /api/sessions/{session_id}/alerts/`. |

### 4.9 Recordings

| ID | Requirement |
|---|---|
| REQ-F-080 | The system shall accept a finished recording/clip from the Jetson via `POST /api/sessions/{session_id}/recordings/` as `multipart/form-data` (`file`, `clip_index`, optional `duration_seconds`), authenticated by device token. |
| REQ-F-081 | The system shall write the uploaded file through to MinIO and persist its metadata (`clip_index`, `duration_seconds`, storage path) as a `Recording` row linked to the session. |
| REQ-F-082 | The system shall provide signed, time-limited MinIO URLs for a session's recordings via `GET /api/sessions/{session_id}/recordings/`. |
| REQ-F-083 | The system shall accept multiple recordings (clips) per session, ordered by `clip_index`. |
| REQ-F-084 | The system shall reject a recording upload whose device token does not match `JETSON_AUTH_TOKEN`. |

### 4.10 Dashboard (Cross-Session)

| ID | Requirement |
|---|---|
| REQ-F-090 | The system shall provide a cross-session summary view (`GET /api/dashboard/summary/`). |
| REQ-F-091 | The system shall provide cross-session listing of sessions, alerts, and analysis samples (`GET /api/dashboard/sessions/`, `/alerts/`, `/analysis/`), independent of the per-session scoped endpoints in §4.7–4.8. |
| REQ-F-092 | `dashboard` shall not maintain its own persisted data; every dashboard response shall be derived from `streaming`/`telemetry` data at request time. |

## 5. Performance Requirements

| ID | Requirement |
|---|---|
| REQ-P-001 | The system shall relay a signaling message (`sdp_offer`/`sdp_answer`/`ice_candidate`) from receipt to forwarding within 200 ms under nominal LAN conditions, since this sits on the WebRTC negotiation critical path. |
| REQ-P-002 | The system shall forward an `alert` message to the relevant Flutter client(s) within 500 ms of receipt from the Jetson. |
| REQ-P-003 | The system shall sustain at least 10 `analysis_data` messages/second of ingestion and persistence for the single active session without dropping samples. |
| REQ-P-004 | REST endpoints under §4.2–4.10 (excluding file upload) shall respond within 300 ms server-side at p95 under single-session load. |
| REQ-P-005 | The system shall support exactly one concurrent active session (single-Jetson constraint, REQ-C-001); it need not be evaluated for multi-session concurrency. |
| REQ-P-006 | The Django process shall not be a bottleneck or intermediary for WebRTC media throughput — video bitrate and frame rate are outside Django's data path by design and impose no requirement on it. |

## 6. Safety Requirements

The Jetson's spasm-detection output is safety-relevant clinical signal; the requirements below constrain how the backend handles it and how it behaves when parts of the system fail, so that a clinician is never left unaware of a detected event or of a broken connection.

| ID | Requirement |
|---|---|
| REQ-SAFETY-001 | An `AlertEvent` shall be durably persisted (database write acknowledged) before, or atomically with, being forwarded to Flutter — an alert must never be deliverable-but-unrecorded. |
| REQ-SAFETY-002 | If forwarding an alert to Flutter fails (e.g. client disconnected), the persisted `AlertEvent` shall remain retrievable via `GET /api/sessions/{session_id}/alerts/` so no detected event is silently lost. |
| REQ-SAFETY-003 | The system shall mark the device offline immediately on unexpected WebSocket disconnect, and `GET /api/device/status/` shall reflect this within one polling interval, so a broken Jetson connection is never misreported as healthy. |
| REQ-SAFETY-004 | If the device goes offline while a session is `ACTIVE`, the system shall not silently continue the session as if monitoring were ongoing; the session shall be transitioned toward `FAILED` and this transition shall itself be observable to Flutter. |
| REQ-SAFETY-005 | The system shall refuse to start a new session while another session is active for the device, preventing two concurrent, conflicting monitoring contexts for the one Jetson. |
| REQ-SAFETY-006 | The system shall reject any device command or signaling message that does not carry a valid, matching `session_id`, preventing a stale or cross-session command from reaching the device. |
| REQ-SAFETY-007 | The system shall never accept an application-level command purporting to originate from the Jetson unless it arrives on the Jetson's authenticated signaling connection (REQ-F-003) — Flutter shall not be able to spoof device-originated alerts or status. |
| REQ-SAFETY-008 | Loss of the Flutter WebSocket connection shall not stop the Jetson's stream or clear session state server-side; only an explicit `stop_session`, an explicit device command, or the safety transition in REQ-SAFETY-004 shall end a session. |

## 7. Security Requirements

| ID | Requirement |
|---|---|
| REQ-SEC-001 | All Flutter-facing REST and WebSocket endpoints except login shall require a valid JWT. |
| REQ-SEC-002 | The Jetson's signaling connection and recording upload shall use the device shared secret exclusively — never a Django user JWT. |
| REQ-SEC-003 | `JETSON_AUTH_TOKEN` shall be stored only in environment/settings configuration, never in the database or in version control. |
| REQ-SEC-004 (deviation, tracked) | Current defaults (`CORS_ALLOW_ALL_ORIGINS = True`, open `ALLOWED_HOSTS`) assume a trusted local LAN and are **not** acceptable outside that environment; closing this is a release gate for any non-LAN deployment (see SDP-GLAB-01 §11). |
| REQ-SEC-005 | The system shall not implement or require STUN/TURN in the LAN-only deployment; adding it shall not require a change to the session/signaling protocol itself (transport-layer addition only). |

## 8. Interface Requirements

The full endpoint and message catalog is normative in [API_REFERENCE.md](../../API_REFERENCE.md) and [README.md](../../README.md) §REST API/§WebSocket endpoints; this SRS requires that catalog to stay synchronized with the requirements in §4 (a protocol change is a requirements change, per SDP-GLAB-01 §8).

| ID | Requirement |
|---|---|
| REQ-I-001 | Every WebSocket frame shall be a single newline-free JSON object carrying a `type` field from the closed set enumerated in README.md's WebSocket table. |
| REQ-I-002 | Every REST error response shall carry a machine-readable error code/detail body sufficient for the Flutter app to distinguish validation failure, auth failure, and not-found without string-matching a human message. |

## 9. Data Requirements

| ID | Requirement |
|---|---|
| REQ-D-001 | Structured data (`Patient`, `Session`, `AlertEvent`, `Recording` metadata, `AnalysisEvent`) shall be stored in PostgreSQL. |
| REQ-D-002 | Recording/clip binary files shall be stored in MinIO, never in PostgreSQL, and never written directly by the Jetson — only through the Django REST upload path (REQ-F-080). |
| REQ-D-003 | Device online/offline status shall be stored only in the Redis-backed cache, never in PostgreSQL. |
| REQ-D-004 | `AnalysisEvent` and `AlertEvent` retention shall follow the lifetime of their parent `Session` (cascade delete), while `Patient` and its historical sessions shall not be deletable together (REQ-F-012). |

## 10. Constraints

| ID | Constraint |
|---|---|
| REQ-C-001 | Exactly one Jetson device is supported per deployment; there is no `Device`/`Camera` model, and multi-device support is out of scope without a schema/protocol revision. |
| REQ-C-002 | Jetson, Django, and Flutter are assumed to be on the same local Wi-Fi/LAN with no internet dependency for the video path. |
| REQ-C-003 | A session always covers all cameras the device has; per-camera addressing does not exist. |

## 11. Traceability Matrix

| Requirement(s) | Software unit (SADD) | Detailed design (SDD) | Verification |
|---|---|---|---|
| REQ-F-001–004, REQ-SEC-001–003 | `streaming.auth`, `streaming.authentication`, `streaming.permissions` | SDD §3.4 | Postman auth folder; `jetson_mock` connect flow |
| REQ-F-010–012 | `streaming.models.Patient`, `streaming.views` | SDD §3.1, §3.5 | Postman patients folder |
| REQ-F-020–022, REQ-SAFETY-003 | `streaming.services` (online/offline), `streaming.views.DeviceStatusView` | SDD §3.2, §3.5 | Manual: disconnect `jetson_mock`, poll status |
| REQ-F-030–037, REQ-SAFETY-004–006 | `streaming.services`, `streaming.models.Session`, `streaming.consumers` | SDD §3.2, §3.3, §6 (state machine) | `flutter_app_mock` + `jetson_mock` session run |
| REQ-F-040–042, REQ-SAFETY-006–007 | `streaming.consumers`, `streaming.services.send_device_command` | SDD §3.3 | `flutter_app_mock` command send |
| REQ-F-050–053 | `streaming.consumers.JetsonConsumer`/`FlutterConsumer`, `streaming.services.relay_signal` | SDD §3.3, §7 | `jetson_mock` (aiortc) full negotiation |
| REQ-F-060–063 | `telemetry.services.record_analysis`, `telemetry.models.AnalysisEvent`, `telemetry.views` | SDD §4 | `telemetry/tests.py`; `flutter_app_mock` fake analysis |
| REQ-F-070–073, REQ-SAFETY-001–002 | `streaming.services.record_alert`, `streaming.models.AlertEvent` | SDD §3.2, §3.5 | Manual: `jetson_mock` alert injection |
| REQ-F-080–084, REQ-D-002 | `streaming.views` (recording upload), `streaming.authentication.DeviceTokenAuthentication`, `streaming.services.save_recording` | SDD §3.5 | Postman recordings folder; `jetson_mock` upload |
| REQ-F-090–092 | `dashboard.views` | SDD §5 | `dashboard/tests.py` |
| REQ-P-001–006 | `streaming.consumers`, ASGI/Daphne config | SDD §7 | Manual load run over LAN |
| REQ-SEC-004 | `config.settings` | SDD §8 | Manual settings review (release gate) |
| REQ-C-001–003 | `streaming.models`, `streaming.services` | SDD §3.1–3.2 | Design review |
