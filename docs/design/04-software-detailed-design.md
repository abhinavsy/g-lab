# Software Detailed Design Document (SDD)

**Document ID:** SDD-GLAB-01 · **Project:** g-lab · **Status:** Draft v0.1
**Traces to:** [SADD-GLAB-01](03-software-architectural-design.md), [SRS-GLAB-01](02-software-requirements-specification.md)

---

## 1. Purpose and Scope

This document specifies the internal logic, data structures, and unit-level interfaces of `config`, `streaming`, `telemetry`, and `dashboard` at a level sufficient to implement or review each module without re-deriving the design from the architecture alone.

## 2. Conventions

- Module-level detail is organized by Django app, then by file, matching the physical layout in [README_FOLDER_STRUCTURE.md](../../README_FOLDER_STRUCTURE.md).
- Field types are given as Django field classes; message schemas are given as JSON with types.
- "Shall" statements below are implementation-level and trace up to the SRS requirement IDs noted in brackets.

## 3. `streaming` — Detailed Design

### 3.1 `models.py`

**`Patient`**

| Field | Type | Constraint |
|---|---|---|
| `patient_id` | `CharField(32)` | unique [REQ-F-011] |
| `name` | `CharField(255)` | required |
| `notes` | `TextField` | blank ok |
| `created_at` | `DateTimeField` | `auto_now_add` |

**`Session`** — `generate_session_id()` returns `f"SES{uuid.uuid4().hex[:8].upper()}"` [REQ-F-032].

| Field | Type | Constraint |
|---|---|---|
| `session_id` | `CharField(32)` | unique, `default=generate_session_id`, `editable=False` |
| `patient` | `FK(Patient)` | `on_delete=PROTECT` [REQ-F-012] |
| `device_id` | `CharField(32)` | denormalized label, not FK [SADD §5] |
| `started_by` | `FK(User)` | `on_delete=SET_NULL`, `null=True` |
| `status` | `CharField(16)` | choices: `STARTING, ACTIVE, STOPPING, COMPLETED, FAILED`; default `STARTING` |
| `created_at`, `started_at`, `ended_at` | `DateTimeField` | `created_at` auto; others nullable, set by `services.py` transitions |

Ordering: `-created_at`.

**`AlertEvent`**

| Field | Type | Constraint |
|---|---|---|
| `session` | `FK(Session)` | `on_delete=CASCADE`, `related_name="alerts"` |
| `alert_type` | `CharField(32)` | choices: `SPASM_DETECTED, DEVICE_OFFLINE, OTHER`; default `OTHER` |
| `message` | `CharField(255)` | blank ok |
| `payload` | `JSONField` | `default=dict` |
| `created_at` | `DateTimeField` | `auto_now_add` |

Ordering: `-created_at`.

**`Recording`** — `recording_upload_path(instance, filename)` returns `f"sessions/{instance.session.session_id}/{filename}"`.

| Field | Type | Constraint |
|---|---|---|
| `session` | `FK(Session)` | `on_delete=CASCADE`, `related_name="recordings"` |
| `file` | `FileField` | `upload_to=recording_upload_path` |
| `clip_index` | `PositiveIntegerField` | default `0` |
| `duration_seconds` | `FloatField` | nullable |
| `created_at` | `DateTimeField` | `auto_now_add` |

Ordering: `clip_index`.

### 3.2 `services.py` — business logic

All functions below are the single implementation called by both `views.py` (REST) and `consumers.py` (WebSocket) [SADD §3.1].

**`start_session(user, patient_id, device_id=None) -> Session`** [REQ-F-030–034, REQ-SAFETY-005]
1. If `device_id` given and `device_id != settings.JETSON_DEVICE_ID` → raise validation error.
2. Look up `Patient` by `patient_id`; not found → raise not-found error.
3. `is_device_online()` → False → raise device-offline error.
4. Query for an existing `Session` with `status in (STARTING, ACTIVE)` → found → raise conflict error [REQ-SAFETY-005].
5. Create `Session(patient=patient, device_id=settings.JETSON_DEVICE_ID, started_by=user, status=STARTING)`.
6. Send `{"type": "start_stream", "session_id": session.session_id}` to the Jetson via the `session_<id>` group [REQ-F-034].
7. Return the created session.

**`stop_session(session_id) -> Session`** [REQ-F-035]
1. Look up `Session`; not found → raise not-found error.
2. Set `status = STOPPING`.
3. Send `{"type": "stop_stream", "session_id": session_id}` to the Jetson.
4. (Terminal transition to `COMPLETED`/`FAILED` happens on `stream_stopped` receipt — see §3.3 `JetsonConsumer`.)

**`send_device_command(session_id, command, params) -> None`** [REQ-F-040–042, REQ-SAFETY-006]
1. Look up `Session`; must exist and have `status == ACTIVE` → else raise error.
2. Forward `{"type": "device_command", "session_id": session_id, "command": command, "params": params}` to the `session_<id>` group, tagged so `JetsonConsumer` alone acts on it.

**`relay_signal(session_id, message, sender_role) -> None`** [REQ-F-050–052]
1. Validate `session_id` refers to an existing, non-terminal session [REQ-SAFETY-006].
2. Broadcast `message` unmodified to `session_<id>`, tagging the sender's role so the group-send excludes the originating connection (no self-echo) [REQ-F-052].

**`record_alert(session_id, alert_type, message, payload) -> AlertEvent`** [REQ-F-070–072, REQ-SAFETY-001–002]
1. Create and save `AlertEvent` **first** (persist-before-forward ordering) [REQ-SAFETY-001].
2. Broadcast `{"type": "alert", ...}` to the Flutter side of `session_<id>` group.
3. Return the saved row regardless of forward outcome — a forward failure does not roll back the write [REQ-SAFETY-002].

**`mark_device_online() / mark_device_offline() / is_device_online() -> bool`** [REQ-F-021–022, REQ-SAFETY-003]
- Backed by a single cache key (Redis), not a DB row. `mark_device_offline()` also triggers a session-safety check (see next).
- On unexpected disconnect, `mark_device_offline()` shall check for a `Session` in `ACTIVE`/`STARTING` state for the device and, if found, transition it toward `FAILED` and emit a `session_status` message so Flutter observes the failure rather than a silently stalled session [REQ-SAFETY-004].

**`save_recording(session_id, file, clip_index, duration_seconds=None) -> Recording`** [REQ-F-080–084, REQ-D-002]
1. Verify caller authenticated via `DeviceTokenAuthentication` (enforced upstream by the view/permission layer, not re-checked here).
2. Look up `Session`; not found → raise not-found error.
3. Save `Recording(session=session, file=file, clip_index=clip_index, duration_seconds=duration_seconds)` — Django's storage backend (`django-storages`, MinIO/S3) performs the actual write-through.
4. Return the saved row (id, clip_index, duration_seconds, and — via the serializer — a signed URL).

### 3.3 `consumers.py` — WebSocket state machines

**`JetsonConsumer`** (`ws/jetson/<JETSON_DEVICE_ID>/`)

| Event | Action |
|---|---|
| `connect` | Validate `token` == `JETSON_AUTH_TOKEN` via `auth.py`; reject (close) on mismatch [REQ-F-003]; else accept and call `services.mark_device_online()`. |
| `receive: sdp_offer` | `services.relay_signal(session_id, message, sender_role="jetson")` [REQ-F-050]. |
| `receive: ice_candidate` | Same relay path, sender `"jetson"`. |
| `receive: webrtc_connected` | Update `Session.status = ACTIVE` if not already; relay to Flutter group [REQ-F-053]. |
| `receive: alert` | `services.record_alert(session_id, alert_type, message, payload)` [REQ-F-070]. |
| `receive: stream_stopped` | Set `Session.ended_at = now()`, `status = COMPLETED` (or `FAILED` if the stop followed an error condition); relay `session_status` to Flutter. |
| `disconnect` | `services.mark_device_offline()` — triggers REQ-SAFETY-004 handling. |

**`FlutterConsumer`** (`ws/app/`)

| Event | Action |
|---|---|
| `connect` | Validate JWT via `auth.py` [REQ-F-002]; reject on invalid/expired token; else accept, add to no group yet (joins `session_<id>` once a session exists in this connection's scope). |
| `receive: start_session` | `services.start_session(user, patient_id, device_id)`; on success join `session_<id>` group, reply `session_started`; on failure reply an error frame. |
| `receive: stop_session` | `services.stop_session(session_id)`. |
| `receive: device_command` | `services.send_device_command(session_id, command, params)`. |
| `receive: sdp_answer` | `services.relay_signal(session_id, message, sender_role="flutter")` [REQ-F-050]. |
| `receive: ice_candidate` | Same relay path, sender `"flutter"`. |
| `receive: webrtc_connected` | Same as Jetson side — either party can trigger the `ACTIVE` transition [REQ-F-053]. |
| `receive: analysis_data` | Call `telemetry.services.record_analysis(session_id, payload)` [REQ-F-060–061]. |
| `disconnect` | No session-state change — per REQ-SAFETY-008, only explicit stop or device-offline ends a session; the consumer simply leaves its groups. |

### 3.4 `auth.py`, `authentication.py`, `permissions.py`

- **`auth.py`** (WebSocket, `AuthMiddlewareStack`-style): reads `?token=` query param at connect time; for `ws/app/` decodes as JWT and attaches the resolved user to connection scope [REQ-F-002]; for `ws/jetson/<id>/` compares literal equality against `settings.JETSON_AUTH_TOKEN` and checks `<id> == settings.JETSON_DEVICE_ID` [REQ-F-003].
- **`authentication.py` → `DeviceTokenAuthentication`** (DRF `BaseAuthentication`): parses `Authorization: Device <token>`, compares to `settings.JETSON_AUTH_TOKEN`; returns `(AnonymousUser-like device principal, None)` on match, `None` on absent header (falls through to other authenticators), raises `AuthenticationFailed` on mismatch [REQ-F-004, REQ-F-084].
- **`permissions.py` → `IsAuthenticatedOrSessionDevice`**: grants access if `request.user.is_authenticated` (Flutter/JWT path) **or** the request was authenticated via `DeviceTokenAuthentication` (Jetson path) — used on the recording-upload endpoint, which is the one REST endpoint reachable by either actor class.

### 3.5 `views.py`, `serializers.py`, `urls.py`

| Endpoint | View | Serializer | Notes |
|---|---|---|---|
| `POST /api/auth/login/` | (DRF SimpleJWT view) | — | Issues access/refresh pair [REQ-F-001] |
| `GET/POST /api/patients/` | `PatientViewSet` | `PatientSerializer` | Standard DRF CRUD, `patient_id` unique validated at serializer level |
| `GET /api/device/status/` | `DeviceStatusView` | ad hoc dict: `{device_id, online, last_seen}` | Read-only; `device_id` sourced from `settings.JETSON_DEVICE_ID`, `online`/`last_seen` from `services.is_device_online()` + cache metadata |
| `GET /api/sessions/` | `SessionViewSet` (list/retrieve) | `SessionSerializer` | Read-only from this viewset; mutation is via the action endpoints below |
| `POST /api/sessions/start/` | `SessionViewSet.start` (action) | `SessionSerializer` | Body `{"patient_id"}`; calls `services.start_session`; maps its exceptions to 400 (validation), 404 (patient), 409 (device offline / session conflict) |
| `POST /api/sessions/{id}/stop/` | `SessionViewSet.stop` (action) | `SessionSerializer` | Calls `services.stop_session` |
| `POST /api/sessions/{id}/command/` | `SessionViewSet.command` (action) | — | Body `{"command","params"}`; calls `services.send_device_command` |
| `GET /api/sessions/{id}/analysis/` | (delegates to `telemetry.views.SessionAnalysisListView`) | `telemetry.serializers.AnalysisEventSerializer` | Scoped to one session |
| `GET /api/sessions/{id}/alerts/` | `SessionAlertsView` | `AlertEventSerializer` | Scoped to one session |
| `GET /api/sessions/{id}/recordings/` | `SessionRecordingsView` | `RecordingSerializer` | Returns signed MinIO URL per recording (via storage backend `.url` property) |
| `POST /api/sessions/{id}/recordings/` | `SessionRecordingsView.create` | `RecordingSerializer` | `parser_classes = [MultiPartParser]`; `authentication_classes` includes `DeviceTokenAuthentication`; `permission_classes = [IsAuthenticatedOrSessionDevice]`; delegates to `services.save_recording`; **201** with the saved row on success |

Error mapping convention (all views): validation error → 400, auth failure → 401/403, not-found → 404, business conflict (device offline, session already active) → 409 [REQ-I-002].

## 4. `telemetry` — Detailed Design

### 4.1 `models.py`

**`AnalysisEvent`**

| Field | Type | Constraint |
|---|---|---|
| `session` | `FK(streaming.Session)` | `on_delete=CASCADE`, `related_name="analysis_events"` |
| `hip_angle`, `knee_angle`, `speed` | `FloatField` | nullable [REQ-F-063] |
| `spasm_detected` | `BooleanField` | default `False` |
| `raw_payload` | `JSONField` | default `dict` — preserves the full inbound payload even if the typed fields above don't cover every key |
| `recorded_at` | `DateTimeField` | `auto_now_add` |

Ordering: `recorded_at` (chronological, unlike `streaming`'s reverse-chronological default — analysis is read as a time series).

### 4.2 `services.py`

**`record_analysis(session_id, payload) -> AnalysisEvent`** [REQ-F-060–063]
1. Look up `Session` by `session_id`; not found → raise not-found error (called from `FlutterConsumer.receive`, which turns this into an error frame back to Flutter rather than a hard disconnect).
2. Extract `hip_angle`, `knee_angle`, `speed`, `spasm_detected` from `payload` if present (each optional); store the full `payload` unmodified into `raw_payload`.
3. Save and return the `AnalysisEvent`.
4. Caller (`FlutterConsumer`) is responsible for any live re-broadcast to other session participants; `record_analysis` itself only persists (single-responsibility split from `streaming.services.record_alert`, which does persist *and* forward, because alerts — unlike routine analysis samples — are safety-relevant per REQ-SAFETY-001).

### 4.3 `views.py`, `urls.py`

`SessionAnalysisListView` — `GET /api/sessions/{session_id}/analysis/`: filters `AnalysisEvent.objects.filter(session__session_id=session_id)`, ordered `recorded_at`, serialized via `AnalysisEventSerializer`; 404 if the session doesn't exist.

## 5. `dashboard` — Detailed Design

No models; each view below is a read-only query composed directly from `streaming`/`telemetry`.

| View | Endpoint | Query shape |
|---|---|---|
| `DashboardSummaryView` | `GET /api/dashboard/summary/` | Aggregate counts: total/active sessions, total patients, total alerts (optionally last-N-days windowed), device online flag |
| `SessionListView` | `GET /api/dashboard/sessions/` | `Session.objects.all()`, unscoped (unlike `streaming`'s per-session endpoints), with patient/status filters as query params |
| `AlertListView` | `GET /api/dashboard/alerts/` | `AlertEvent.objects.select_related("session")`, unscoped, newest-first |
| `AnalysisListView` | `GET /api/dashboard/analysis/` | `AnalysisEvent.objects.select_related("session")`, unscoped, with optional `spasm_detected=true` filter for alert-adjacent triage views |

All four are read-only (`GET` only, no `ViewSet` mutation actions) [REQ-F-090–092].

## 6. Session State Machine (detailed)

```
                 start_session (services.start_session)
                          │
                          ▼
                     STARTING ──────────────────────────┐
                          │                              │ device goes offline while
                          │ webrtc_connected              │ STARTING/ACTIVE
                          ▼                              │ (services.mark_device_offline)
                      ACTIVE ────────────────────────────┤ [REQ-SAFETY-004]
                          │                              │
                          │ stop_session                 │
                          ▼                              ▼
                     STOPPING                          FAILED
                          │
                          │ stream_stopped (normal)
                          ▼
                     COMPLETED
```

| Transition | Trigger | Guard |
|---|---|---|
| — → `STARTING` | `services.start_session` | patient exists, device online, no other active session [REQ-SAFETY-005] |
| `STARTING` → `ACTIVE` | `webrtc_connected` from either consumer | session must be `STARTING` |
| `ACTIVE`/`STARTING` → `FAILED` | `services.mark_device_offline` finds a live session | unconditional once triggered [REQ-SAFETY-004] |
| `ACTIVE` → `STOPPING` | `services.stop_session` | session must be `ACTIVE` (or `STARTING`, for an early abort) |
| `STOPPING` → `COMPLETED` | `stream_stopped` from `JetsonConsumer` | normal teardown path |
| `STOPPING` → `FAILED` | `stream_stopped` carrying an error indicator, or timeout | abnormal teardown |

## 7. Message Protocol — Field-Level Schemas

| `type` | Direction | Payload |
|---|---|---|
| `start_session` | Flutter → Django | `{type, patient_id: str}` |
| `session_started` | Django → Flutter | `{type, session_id: str, status: "STARTING"}` |
| `session_status` | Django → Flutter | `{type, session_id: str, status: str}` |
| `stop_session` | Flutter → Django | `{type, session_id: str}` |
| `device_command` | Flutter → Django | `{type, session_id: str, command: str, params: object}` |
| `start_stream` / `stop_stream` | Django → Jetson | `{type, session_id: str}` |
| `sdp_offer` | Jetson → Django → Flutter | `{type, session_id: str, sdp: str}` |
| `sdp_answer` | Flutter → Django → Jetson | `{type, session_id: str, sdp: str}` |
| `ice_candidate` | either → Django → other | `{type, session_id: str, candidate: str, sdpMid: str, sdpMLineIndex: int}` |
| `webrtc_connected` | either → Django | `{type, session_id: str}` |
| `analysis_data` | Flutter → Django | `{type, session_id: str, hip_angle?: float, knee_angle?: float, speed?: float, spasm_detected?: bool, ...}` |
| `alert` | Jetson → Django → Flutter | `{type, session_id: str, alert_type: str, message?: str, payload?: object}` |
| `stream_stopped` | Jetson → Django | `{type, session_id: str, reason?: str}` |

All frames are single JSON objects, no framing/newlines [REQ-I-001].

## 8. Configuration Detail (`config`)

| Setting | Source | Consumed by |
|---|---|---|
| `JETSON_DEVICE_ID`, `JETSON_AUTH_TOKEN` | `.env` | `streaming.auth`, `streaming.authentication`, `streaming.services` |
| `DATABASES` | `.env` (Postgres DSN parts) | Django ORM, all apps |
| `CHANNEL_LAYERS` | `.env` (Redis URL) | `streaming.consumers`, ASGI |
| `CACHES` | `.env` (Redis URL) | `streaming.services` (device online flag) |
| MinIO/S3 storage settings | `.env` | `django-storages`, `streaming.models.Recording.file` |
| JWT settings | `.env`/defaults | DRF SimpleJWT, `streaming.auth` |
| `CORS_ALLOW_ALL_ORIGINS`, `ALLOWED_HOSTS` | `config/settings.py` defaults | Flagged as a release gate — REQ-SEC-004 |

`config/asgi.py` wires `streaming.routing` into the Channels `ProtocolTypeRouter`; `config/urls.py` includes `streaming.urls`, `telemetry.urls`, `dashboard.urls` under `/api/`.

## 9. Error Handling and Logging

- Business-rule violations in `services.py` raise typed exceptions (e.g. `DeviceOfflineError`, `SessionConflictError`, `SessionNotFoundError`); `views.py` maps each to the HTTP status convention in §3.5, and `consumers.py` maps each to an error-typed WebSocket frame rather than closing the connection, so a rejected command doesn't tear down signaling state.
- Every state transition in §6 and every alert (§3.2 `record_alert`) is logged at `INFO` with `session_id` for traceability; auth failures (`auth.py`, `authentication.py`) are logged at `WARNING` with the failing principal type (Flutter/Jetson) but never the token value.

## 10. Unit Test Mapping

| Test file | Covers |
|---|---|
| `dashboard/tests.py` | `dashboard.views` read/aggregation logic §5 |
| `telemetry/tests.py` | `telemetry.services.record_analysis`, `telemetry.views.SessionAnalysisListView` §4 |
| *(gap — see SDP-GLAB-01 §11)* | `streaming.services` state-machine and validation logic §3.2, §6 need dedicated `streaming/tests.py` coverage |

## 11. Traceability

This document's section numbers are the SDD-column targets referenced from SRS-GLAB-01 §11; no separate matrix is repeated here to avoid the two drifting out of sync.
