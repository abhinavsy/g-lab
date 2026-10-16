# Software Development Plan (SDP)

**Document ID:** SDP-GLAB-01 · **Project:** g-lab (Jetson → Django → Flutter WebRTC rehab-monitoring platform)
**Status:** Draft v0.1 · **Applies to:** `config`, `streaming`, `telemetry`, `dashboard`, and the `jetson_mock` / `flutter_app_mock` test harnesses

Companion documents: [SRS-GLAB-01](02-software-requirements-specification.md) · [SADD-GLAB-01](03-software-architectural-design.md) · [SDD-GLAB-01](04-software-detailed-design.md)

---

## 1. Purpose and Scope

This plan defines how g-lab's software is developed, verified, and controlled across its life. g-lab is the Django backend that sits between a single NVIDIA Jetson edge device (camera capture, AI inference, WebRTC video sender) and a Flutter clinical app, coordinating session control and WebRTC signaling while never carrying the video itself (see [README_WebRTC.md](../../README_WebRTC.md)). The plan covers the four Django apps (`config`, `streaming`, `telemetry`, `dashboard`) and the two off-runtime test harnesses (`jetson_mock`, `flutter_app_mock`) used to exercise the backend without real hardware or a real Flutter build.

Out of scope: the Jetson-side AI/inference implementation and the production Flutter app, both owned by other teams; this plan only defines the interfaces g-lab exposes to them.

## 2. Reference Documents

| Doc | Content |
|---|---|
| [README.md](../../README.md) | Stack, local setup, REST/WebSocket endpoint summary |
| [README_WebRTC.md](../../README_WebRTC.md) | End-to-end signaling/session/recording flow (source of truth for behavior) |
| [README_FOLDER_STRUCTURE.md](../../README_FOLDER_STRUCTURE.md) | App boundaries and ownership |
| [API_REFERENCE.md](../../API_REFERENCE.md) | REST/WebSocket contract detail |
| `g-lab.postman_collection.json` | Executable API reference / manual test collection |
| SRS-GLAB-01, SADD-GLAB-01, SDD-GLAB-01 | This document's companions |

## 3. Lifecycle Model

g-lab uses a **unit-incremental lifecycle**: the four phases below (Plan → Requirements → Architecture → Detailed Design, then Implementation/Verification) run once at the whole-system level to fix the contracts every app must honor, then repeat per app/increment as functionality is added, because the apps are already partitioned along clean seams (control plane vs. data relay vs. read-only aggregation — [README_FOLDER_STRUCTURE.md](../../README_FOLDER_STRUCTURE.md) §1–5) that let them move independently once the shared contract (session/message model, DB schema) is frozen.

```
Phase 0  System Plan + SRS + SADD           (this document + SRS/SADD, whole-system, done once)
Phase 1  streaming/  detailed design → build → verify   (control plane: sessions, signaling, commands, alerts, recordings)
Phase 2  telemetry/  detailed design → build → verify   (analysis-event relay)
Phase 3  dashboard/  detailed design → build → verify   (cross-cutting read API)
Phase 4  jetson_mock / flutter_app_mock                 (test harnesses, developed alongside Phase 1 to unblock it)
Phase 5  Integration verification (real REST/WS traffic against mocks) → Release
```

Each app-level increment still runs its own mini Requirements→Architecture→Detailed-Design→Build→Verify cycle before merge; nothing skips straight to code. `dashboard` (Phase 3) is deliberately sequenced last because it only *reads* `streaming`/`telemetry` data and has no schema of its own — its design is unstable until those two are frozen.

## 4. Organization and Responsibilities

| Role | Responsibility |
|---|---|
| Backend/Django owner | `config`, `streaming`, `telemetry`, `dashboard` — this plan's primary scope |
| Edge/AI team | Jetson-side capture, inference, GStreamer/H.264, WebRTC sender — consumes this plan's interfaces, does not implement inside this repo |
| Mobile team | Flutter app — consumes this plan's interfaces, does not implement inside this repo |
| QA / integration | Runs `jetson_mock` + `flutter_app_mock` + Postman collection against each release candidate |

Because the Jetson and Flutter implementations live outside this repo, `jetson_mock` and `flutter_app_mock` are this plan's primary integration-verification tool — they are the executable form of the interface contract in SADD-GLAB-01 §5.

## 5. Deliverables

| Phase | Deliverables |
|---|---|
| Plan | This document (SDP-GLAB-01) |
| Requirements | SRS-GLAB-01, updates to [README_WebRTC.md](../../README_WebRTC.md) where behavior changes |
| Architecture | SADD-GLAB-01, `README_FOLDER_STRUCTURE.md` kept current |
| Detailed design | SDD-GLAB-01 |
| Implementation | Source under `config/`, `streaming/`, `telemetry/`, `dashboard/`; Django migrations; `.env.example` updates for new settings |
| Verification | `dashboard/tests.py`, `telemetry/tests.py` (and equivalents to be added for `streaming/`); `g-lab.postman_collection.json`; manual runs via `jetson_mock`/`flutter_app_mock` |
| Release | Tagged commit, `requirements.txt`/`uv.lock` pinned, `docker-compose.yml` / `Dockerfile` validated |

## 6. Development Environment

- **Language/runtime:** Python (pinned via `.python-version`), dependency set via `pyproject.toml` + `uv.lock` (uv) and mirrored in `requirements.txt`
- **Framework:** Django 5 + Django REST Framework (REST, JWT auth), Django Channels + `channels_redis` (WebSocket, ASGI via Daphne — `config/asgi.py`)
- **Datastores:** PostgreSQL (structured data), Redis (channel layer + online/offline cache), MinIO/S3 via `django-storages` (recordings)
- **Local infra:** `docker-compose.yml` (dev services), `docker-compose.jetson-mock.yml` (mock edge device), `Dockerfile` / `docker-entrypoint.sh` (app container)
- **API tooling:** `g-lab.postman_collection.json`

## 7. Standards and Conventions

- **One app, one responsibility** ([README_FOLDER_STRUCTURE.md](../../README_FOLDER_STRUCTURE.md) §1): a new capability is placed by *who talks to whom*, not by feature name — Jetson↔Django/Flutter↔Django control traffic stays in `streaming`; the one genuine Flutter→Django data transfer (analysis samples) stays isolated in `telemetry`; cross-session read-only views stay in `dashboard`.
- **No `Device`/`Camera` model** — this deployment targets exactly one Jetson; its identity is a settings value (`JETSON_DEVICE_ID`, `JETSON_AUTH_TOKEN`), not a database row. Any future multi-device support is an SRS-level decision (see SRS-GLAB-01 §10, constraints), not something to bolt on ad hoc in `streaming/services.py`.
- **`session_id`, never `camera_id` or `device_id`, on the wire** — one session always covers every camera the device has.
- Registering a new app requires updates in both `config/settings.py` (`INSTALLED_APPS`) and `config/urls.py` (`urlpatterns`) — call this out explicitly in PR descriptions that add an app.
- REST and WebSocket code paths share business logic through `streaming/services.py`; a new session/command/signaling rule is added there once, not duplicated per transport.

## 8. Configuration Management Plan

| Item | Under version control? | Notes |
|---|---|---|
| Application source (`config/`, `streaming/`, `telemetry/`, `dashboard/`) | Yes | Git, this repository |
| Django migrations | Yes | Committed alongside the model change that produced them |
| `pyproject.toml`, `uv.lock`, `requirements.txt` | Yes | Kept in sync; `uv.lock` is the source of truth for exact versions |
| `docker-compose*.yml`, `Dockerfile`, `docker-entrypoint.sh` | Yes | |
| `.env.example` | Yes | Documents every setting; updated whenever a new setting is introduced |
| `.env`, secrets, `JETSON_AUTH_TOKEN` values | **No** | `.gitignore`d; distributed out-of-band per environment |
| `g-lab.postman_collection.json` | Yes | Treated as an executable interface artifact — updated in the same PR as any endpoint change |
| Design documents (this set) | Yes | `docs/design/` |

**Branching:** feature branches off `main`/`master`; PRs required for merge. **Change control:** a change to a REST/WebSocket message shape or a model field is a change to SRS/SADD/SDD and must update the relevant document in the same PR — these documents are expected to drift from the code otherwise, which is the failure mode this CM section exists to prevent.

## 9. Traceability Policy

Requirements are identified `REQ-<AREA>-<NNN>` (e.g. `REQ-F-012`, `REQ-SAFETY-003`) in SRS-GLAB-01. Each requirement traces forward to:

1. One or more software units in SADD-GLAB-01 (e.g. `streaming.consumers.JetsonConsumer`)
2. One or more detailed-design elements in SDD-GLAB-01 (e.g. a specific service function or message handler)
3. A verification method (test file, Postman request, or manual mock-harness procedure)

The consolidated matrix lives in SRS-GLAB-01 §11. Every new requirement added to the SRS must gain a row in that matrix before the corresponding code is merged.

## 10. Verification and Validation Approach

| Level | Method | Current artifact |
|---|---|---|
| Unit | Django `TestCase` | `dashboard/tests.py`, `telemetry/tests.py`; `streaming/` unit tests are a gap — see §11 |
| API contract | Postman collection run against a live dev server | `g-lab.postman_collection.json` |
| Integration (control plane + signaling) | `jetson_mock` (aiortc-based, real SDP/ICE/video) and `flutter_app_mock` driving real REST/WebSocket traffic against `streaming`/`telemetry`/`dashboard` | `docker-compose.jetson-mock.yml`, `mock_flutter_answer.py`, `web_test*.py` |
| Manual/system | End-to-end run: mock Jetson + mock Flutter + real Django on one LAN segment | Procedure to be captured as a runbook |

## 11. Risk Management

| Risk | Impact | Mitigation / status |
|---|---|---|
| Single Jetson, no `Device` model | A hardware swap or multi-device deployment requires a schema and protocol change, not a config change | Documented constraint (SRS-GLAB-01 §10); treat as a deliberate scope boundary, not a defect |
| `CORS_ALLOW_ALL_ORIGINS` + open `ALLOWED_HOSTS` | Unsafe beyond a trusted LAN | Called out in [README.md](../../README.md) §Notes; must be closed before any non-LAN deployment — tracked as a pre-release gate, not yet enforced in settings |
| `JETSON_AUTH_TOKEN` is a static shared secret | Token compromise gives full device-command and recording-upload access | Acceptable for closed-LAN v1; rotate via `.env` + redeploy; short-lived tokens flagged as future work if the Jetson ever leaves the trusted LAN |
| No STUN/TURN configured | WebRTC negotiation fails if Jetson and Flutter end up on different networks | Intentional for the LAN-only v1 (README_WebRTC.md §23); revisit if deployment topology changes |
| `streaming/` has no dedicated unit tests yet | Regressions in session/signaling logic are only caught by manual/integration runs | Backlog item — see §10 |

## 12. Milestones

Dates are TBD pending scheduling; sequencing follows §3:

1. System-level Plan/SRS/SADD baselined (this document set)
2. `streaming/` detailed design, implementation, and verification complete
3. `telemetry/` detailed design, implementation, and verification complete
4. `dashboard/` detailed design, implementation, and verification complete
5. Full mock-harness integration pass (Jetson mock + Flutter mock + Django, one LAN segment)
6. Release candidate cut, CM items pinned, hardening items from §11 reviewed
