# Software Architectural Design Document (SADD)

**Document ID:** SADD-GLAB-01 · **Project:** g-lab · **Status:** Draft v0.1
**Traces to:** [SRS-GLAB-01](02-software-requirements-specification.md) · **Traces forward to:** [SDD-GLAB-01](04-software-detailed-design.md)

---

## 1. Purpose and Scope

This document decomposes g-lab into software units, defines the interfaces between them and with the external Jetson/Flutter/PostgreSQL/MinIO/Redis actors, and records the architectural decisions that satisfy SRS-GLAB-01. It covers `config`, `streaming`, `telemetry`, `dashboard`, and their external contract with `jetson_mock`/`flutter_app_mock`.

## 2. Architectural Overview

### 2.1 Context

```
   ┌──────────────┐   REST / WebSocket    ┌──────────────────┐   WebSocket    ┌──────────────┐
   │  Flutter App │◄─────────────────────►│  Django Backend   │◄──────────────►│    Jetson     │
   │ (login, ctrl,│   commands, signaling │  (control plane)  │  commands,     │ (camera, AI,  │
   │  live video)  │                       │                   │  signaling     │  H.264, WebRTC)│
   └──────┬───────┘                       └────────┬──────────┘                └──────┬───────┘
          │                                         │                                  │
          │              WebRTC — video + analysis data channel, direct                │
          └─────────────────────────────────────────────────────────────────────────────┘

                                    ┌────────────────────────────┐
                                    │        Django Backend        │
                                    │  ┌──────────┐ ┌───────────┐ │
                                    │  │PostgreSQL│ │   MinIO   │ │
                                    │  └──────────┘ └───────────┘ │
                                    │  ┌──────────┐               │
                                    │  │  Redis   │  (Channels,   │
                                    │  └──────────┘   online flag)│
                                    └────────────────────────────┘
```

### 2.2 Architectural Drivers (from SRS-GLAB-01)

| Driver | Source requirement(s) | Architectural consequence |
|---|---|---|
| Django must never sit in the video path | REQ-P-006, README_WebRTC.md §12 | Django implements signaling *relay* only — no media server component |
| Exactly one Jetson, no device CRUD | REQ-C-001 | No `Device` model; identity lives in `config.settings`, consumed by `streaming` |
| A session covers all cameras | REQ-C-003, REQ-F-037 | Protocol keyed on `session_id` only; no per-camera routing layer |
| Alerts must survive delivery failure | REQ-SAFETY-001/002 | Persist-then-forward ordering enforced inside `streaming.services`, not left to the consumer |
| REST and WebSocket share validation | REQ-F-030–042 | Single `streaming.services` module is the only place session/command business logic lives; both transports call into it |
| The one real Flutter→Django data transfer is analysis samples | REQ-F-060–063 | Isolated into its own app (`telemetry`) rather than folded into `streaming`, so that transfer path is architecturally distinct from control-plane traffic |
| Cross-session views need no new schema | REQ-F-090–092 | `dashboard` is model-less by design — a read/query layer over `streaming`/`telemetry`, not a third data owner |

## 3. Software Unit Decomposition

| Unit | Responsibility | Contains |
|---|---|---|
| `config` | Project composition root: settings, URL root, ASGI/WSGI entrypoints | `settings.py`, `urls.py`, `asgi.py`, `wsgi.py` |
| `streaming` | Control plane: sessions, device commands, WebRTC signaling relay, alerts, recording ingestion | `models.py`, `serializers.py`, `views.py`, `services.py`, `consumers.py`, `routing.py`, `auth.py`, `authentication.py`, `permissions.py`, `admin.py`, `urls.py` |
| `telemetry` | The one Flutter→Django data transfer: live analysis samples | `models.py`, `serializers.py`, `services.py`, `views.py`, `urls.py` |
| `dashboard` | Cross-session read-only aggregation over `streaming`/`telemetry` | `views.py`, `urls.py` (no `models.py`) |
| `jetson_mock` *(external harness)* | Stand-in Jetson: real WebRTC via aiortc, drives `streaming`'s device-facing contract | Out-of-repo-scope implementation; contract-relevant only |
| `flutter_app_mock` *(external harness)* | Stand-in Flutter client: login, session control, real WebRTC render, fake `analysis_data` | Out-of-repo-scope implementation; contract-relevant only |

Unit boundaries follow *who talks to whom*, not feature grouping — this is what keeps `AlertEvent` inside `streaming` (Jetson → Django, not Flutter → Django) even though "alerts" reads like a `telemetry`-shaped concern (README_FOLDER_STRUCTURE.md §3).

### 3.1 `streaming` — internal structure

```
                      ┌───────────────────────────────────────┐
                      │               streaming                │
                      │                                         │
  REST clients ──────►│  views.py ──┐                           │
                      │             ▼                           │
  WebSocket ─────────►│  consumers.py ──► services.py ──► models.py
  (Jetson, Flutter)    │             ▲          │                │
                      │  auth.py ────┘          ▼                │
                      │  authentication.py   (PostgreSQL,        │
                      │  permissions.py       Redis cache)       │
                      └───────────────────────────────────────┘
```

`services.py` is the single point both `views.py` (REST) and `consumers.py` (WebSocket) call into for session/command/signaling/alert/recording logic — this is what satisfies REQ-F-030–042's shared-validation requirement without duplicating rules per transport.

### 3.2 `telemetry` — internal structure

```
FlutterConsumer (streaming) ──► telemetry.services.record_analysis() ──► telemetry.models.AnalysisEvent
                                                                                 │
GET /api/sessions/{id}/analysis/  ◄── telemetry.views.SessionAnalysisListView ──┘
```

`telemetry` depends on `streaming.models.Session` (FK) but `streaming` has no reverse dependency on `telemetry` beyond the `related_name="analysis_events"` relation — the dependency is one-directional.

### 3.3 `dashboard` — internal structure

`dashboard.views` queries `streaming` and `telemetry` models directly (no service layer of its own, since it performs no writes and enforces no business rule beyond read scoping) and exposes four read endpoints: summary, sessions, alerts, analysis — each an unscoped, cross-session counterpart to a `streaming`/`telemetry` endpoint that is per-session-scoped.

## 4. External Interfaces

### 4.1 REST (Flutter ↔ `streaming`/`telemetry`/`dashboard`)

| Endpoint | Method | Unit | Auth |
|---|---|---|---|
| `/api/auth/login/` | POST | `streaming` | none → issues JWT |
| `/api/patients/` | GET/POST | `streaming` | JWT |
| `/api/device/status/` | GET | `streaming` | JWT |
| `/api/sessions/` | GET | `streaming` | JWT |
| `/api/sessions/start/` | POST | `streaming` | JWT |
| `/api/sessions/{id}/stop/` | POST | `streaming` | JWT |
| `/api/sessions/{id}/command/` | POST | `streaming` | JWT |
| `/api/sessions/{id}/analysis/` | GET | `telemetry` | JWT |
| `/api/sessions/{id}/alerts/` | GET | `streaming` | JWT |
| `/api/sessions/{id}/recordings/` | GET | `streaming` | JWT |
| `/api/sessions/{id}/recordings/` | POST | `streaming` | Device token |
| `/api/dashboard/summary/`, `/sessions/`, `/alerts/`, `/analysis/` | GET | `dashboard` | JWT |

Full request/response shapes: [API_REFERENCE.md](../../API_REFERENCE.md).

### 4.2 WebSocket (Flutter/Jetson ↔ `streaming`)

| Endpoint | Consumer | Peer |
|---|---|---|
| `ws/app/?token=<jwt>` | `FlutterConsumer` | Flutter |
| `ws/jetson/<JETSON_DEVICE_ID>/?token=<...>` | `JetsonConsumer` | Jetson |

Both consumers exchange the JSON `type`-tagged frames enumerated in README.md's message table (`start_session`, `session_started`/`session_status`, `stop_session`, `device_command`, `start_stream`/`stop_stream`, `sdp_offer`, `sdp_answer`, `ice_candidate`, `webrtc_connected`, `analysis_data`, `alert`, `stream_stopped`). Relay is mediated by a per-session Channels group `session_<id>`, on the Redis-backed channel layer, so `JetsonConsumer` and `FlutterConsumer` never call each other directly — this decoupling is what lets either side reconnect independently without the other needing to know its channel name.

### 4.3 Media plane (Jetson ↔ Flutter, no Django)

WebRTC video and the analysis data channel negotiate through the signaling relay above but, once connected, flow directly Jetson → Flutter. This is an architectural boundary, not an incidental one: no unit in this decomposition is permitted to sit on that path (REQ-P-006).

### 4.4 Datastore interfaces

| Store | Owner unit(s) | Contents |
|---|---|---|
| PostgreSQL | `streaming` (Patient, Session, AlertEvent, Recording metadata), `telemetry` (AnalysisEvent) | Structured, relational |
| MinIO | `streaming` (write path only, via `services.save_recording`) | Recording/clip binary files, keyed `sessions/<session_id>/<file>` |
| Redis | `streaming` (Channels layer, device online/offline cache) | Ephemeral runtime state |

`dashboard` has no datastore of its own — see §2.2.

## 5. Data Architecture

```
Patient 1───* Session 1───* AlertEvent
                  │  1───* Recording
                  │
                  └──────* AnalysisEvent   (telemetry app, FK to streaming.Session)
```

- `Patient.patient_id` is the natural key exposed externally; `Session.session_id` is system-generated (`SES########`), never client-supplied.
- `Session.device_id` is a denormalized label (always the configured `JETSON_DEVICE_ID` today) recorded at start time for historical traceability, not a foreign key — there is deliberately no `Device` table to point at (§2.2).
- `AlertEvent` and `Recording` cascade-delete with their `Session`; `Patient` is protected against deletion while it has sessions (REQ-F-012, REQ-D-004).

## 6. Runtime / Concurrency View

- `consumers.py` runs async (Channels/ASGI via Daphne — `config/asgi.py`); `views.py` runs sync (WSGI-compatible DRF, though served under the same ASGI process in this deployment).
- Session state (`STARTING → ACTIVE → STOPPING → COMPLETED`/`FAILED`) is the sole coordination point between the two consumers; each transition is written by `streaming.services` so REST reads (`GET /api/sessions/`) and WebSocket-driven state agree without a second source of truth.
- Device online/offline is cache-backed (Redis) rather than DB-backed specifically so it reflects the *current* WebSocket connection state instantly, without a write-heavy DB round trip on every connect/disconnect (REQ-SAFETY-003).
- Only one session may be `STARTING`/`ACTIVE` at a time for the device (REQ-SAFETY-005); this is enforced in `streaming.services.start_session`, not at the database constraint level, because it requires reading current session status plus device online state together.

## 7. Security Architecture

| Actor | Mechanism | Unit |
|---|---|---|
| Flutter user | JWT (DRF `SimpleJWT` or equivalent) | `streaming` REST/WS auth, `config.settings` |
| Jetson (signaling) | Static shared secret (`JETSON_AUTH_TOKEN`) matched in `streaming.auth` | `streaming` |
| Jetson (recording upload) | `Authorization: Device <token>` via `streaming.authentication.DeviceTokenAuthentication` | `streaming` |
| Cross-cutting | `streaming.permissions.IsAuthenticatedOrSessionDevice` gates endpoints usable by either actor class | `streaming` |

Both device-facing mechanisms deliberately avoid the Django user/JWT system (REQ-SEC-002) since the Jetson is not a Django user — it is configuration, per REQ-C-001.

## 8. Deployment View

```
docker-compose.yml
 ├── app          (Django, Daphne — config.asgi:application; also serves WSGI for management)
 ├── postgres
 ├── redis        (Channels layer + cache)
 └── minio

docker-compose.jetson-mock.yml
 └── jetson_mock  (aiortc-based stand-in device, same LAN/network as app)
```

`Dockerfile` + `docker-entrypoint.sh` build and start the Django app container; `.env`/`.env.example` supply `JETSON_DEVICE_ID`, `JETSON_AUTH_TOKEN`, database/Redis/MinIO connection settings, and JWT/CORS configuration consumed by `config.settings`.

## 9. Design Rationale Summary

| Decision | Rationale |
|---|---|
| `telemetry` split from `streaming` | Keeps the one genuine Flutter→Django *data* transfer distinct from Django↔Jetson/Flutter *control-plane* traffic — a different concern with a different growth path (README_FOLDER_STRUCTURE.md §4) |
| `dashboard` has no models | Avoids a third, competing source of truth for session/alert/analysis data; it is a view, not a store |
| No `Device`/`Camera` model | Matches the single-Jetson deployment reality (REQ-C-001); avoids CRUD/API surface for an entity that never varies |
| Business logic centralized in `services.py` | REST and WebSocket are two transports for the same rules (REQ-F-030–042); duplicating validation per transport was rejected as a maintenance and safety risk |
| Recording upload is REST, not WebSocket | The signaling WebSocket carries time-sensitive JSON control messages; a large binary upload does not belong on that connection (README_WebRTC.md §17) |

## 10. Traceability to SRS

See SRS-GLAB-01 §11 for the consolidated requirement → unit → detailed-design → verification matrix; the unit column there is populated from §3 of this document.
