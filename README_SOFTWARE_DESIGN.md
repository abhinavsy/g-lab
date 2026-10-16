# Software Design Overview — for Team Discussion

> Companion to [`README_WebRTC.md`](README_WebRTC.md) (the *behavior*) and [`README_FOLDER_STRUCTURE.md`](README_FOLDER_STRUCTURE.md) (the *layout*). This one is the *design* — why the system is shaped the way it is, what we're promising it will do, and what's still open. Bring this to the review meeting; the four full documents it summarizes live in [`docs/design/`](docs/design/) if anyone wants to go deeper on one part.

---

# 1. Why this doc exists

We've written four formal design documents for g-lab (Plan → Requirements → Architecture → Detailed Design). They're useful as a record, but nobody wants to review four documents in a meeting. This is the one-pager version: the shape of the system, the decisions worth arguing about, and the open items — with pointers into the full docs for anyone who wants the detail behind a claim.

```
docs/design/
├── 01-software-development-plan.md            (SDP)  — how we work, CM, traceability
├── 02-software-requirements-specification.md  (SRS)  — what it must do, how fast, how safely
├── 03-software-architectural-design.md        (SADD) — how it's decomposed, the interfaces
└── 04-software-detailed-design.md              (SDD)  — logic, data, message schemas
```

---

# 2. The system in one picture

```text
                         SAME LOCAL WI-FI / LAN

   ┌──────────────┐   REST / WebSocket     ┌───────────────────┐   WebSocket    ┌──────────────┐
   │  FLUTTER APP │◄──────────────────────►│   DJANGO BACKEND    │◄──────────────►│    JETSON     │
   │ login, ctrl,  │  commands, signaling    │  (control plane)    │  commands,     │ camera, AI,   │
   │ live video    │                         │                     │  signaling     │ H.264, WebRTC │
   └──────┬───────┘                         └──────────┬──────────┘                └──────┬───────┘
          │                                             │                                  │
          │              WebRTC — video + analysis data channel, DIRECT, no Django          │
          └───────────────────────────────────────────────────────────────────────────────┘

                                     ┌──────────────────────────┐
                                     │       Django data layer     │
                                     │  PostgreSQL   MinIO   Redis │
                                     │  (structured) (files) (rt)  │
                                     └──────────────────────────┘
```

**The one sentence that matters:** Django coordinates and validates everything; it never carries a video frame. Full flow: [README_WebRTC.md](README_WebRTC.md).

---

# 3. How the four documents fit together

```text
   SDP                SRS                    SADD                    SDD
"how we work"    "what it must do"     "how it's split up"    "how each piece works"

  Plan  ──────►  Requirement  ──────►  Software unit  ──────►  Function / message /
                 REQ-F-030             streaming.services       field, line-level
                 "start session,       .start_session()         (see docs/design/04
                  validate, no two                                §3.2)
                  sessions at once"
```

Every requirement in the SRS has an ID (`REQ-F-030`, `REQ-SAFETY-004`, ...) that's traceable all the way to the code area that implements it and the test/procedure that checks it (SRS §11). That matrix is the thing to point at when someone asks "wait, where does that rule actually live?"

---

# 4. Software units — who owns what

| Unit | Owns | Talks to |
|---|---|---|
| `streaming` | Sessions, device commands, WebRTC signaling relay, alerts, recording ingestion | Flutter (REST+WS), Jetson (WS+REST upload), PostgreSQL, Redis, MinIO |
| `telemetry` | The one real Flutter→Django *data* transfer: live analysis samples | `streaming.Session` (FK only, one-directional) |
| `dashboard` | Cross-session read views — no data of its own | Reads `streaming` + `telemetry` at request time |
| `config` | Settings, routing, ASGI/WSGI entrypoints | Everything, as the composition root |

**The rule that decides where new code goes:** boundary is *who talks to whom*, not feature name. That's why `AlertEvent` lives in `streaming` (Jetson → Django) even though "alerts" sounds like it could be a `telemetry` thing (which is Flutter → Django only). Full rationale: [SADD §2.2, §9](docs/design/03-software-architectural-design.md#9-design-rationale-summary).

---

# 5. The session lifecycle (the thing to whiteboard)

```text
                 start_session
                      │
                      ▼
                 STARTING ─────────────────────────┐
                      │                             │ Jetson drops offline
                      │ webrtc_connected              │ while STARTING/ACTIVE
                      ▼                             │ (safety transition,
                  ACTIVE ───────────────────────────┤  not silent — see §7)
                      │                             │
                      │ stop_session                 │
                      ▼                             ▼
                 STOPPING                          FAILED
                      │
                      │ stream_stopped (normal)
                      ▼
                 COMPLETED
```

- Only **one** session can be `STARTING`/`ACTIVE` at a time — there's one Jetson, one set of cameras, no concurrency to reason about.
- A dropped Flutter connection does **not** end a session — only an explicit stop, an explicit command, or the device going offline does. Losing your phone signal for a second shouldn't kill someone's monitoring session.

---

# 6. Requirements, condensed

Full lists: functional ([SRS §4](docs/design/02-software-requirements-specification.md#4-functional-requirements)), performance ([§5](docs/design/02-software-requirements-specification.md#5-performance-requirements)), safety ([§6](docs/design/02-software-requirements-specification.md#6-safety-requirements)), security ([§7](docs/design/02-software-requirements-specification.md#7-security-requirements)).

| Area | Headline requirement |
|---|---|
| Functional | Flutter starts/stops sessions and sends commands; Django validates and relays; Jetson offers, Flutter answers |
| Performance | Signaling relay < 200 ms, alert delivery < 500 ms, ≥10 analysis samples/sec sustained |
| **Safety** | An alert is **written to the DB before or atomically with** being forwarded — never deliverable-but-unrecorded. Device going offline mid-session **must** surface as a failed session, never a silent stall. |
| Security | Flutter uses JWT; the Jetson uses a static shared secret (`JETSON_AUTH_TOKEN`) — never a Django user account |

---

# 7. Discussion topics — bring opinions

These are the places the design makes a call that's worth the team pressure-testing, or flags as unfinished:

1. **No `Device`/`Camera` model.** One Jetson, hardcoded via `.env`. Fine for pilot deployments — but if a second clinic/device is on the roadmap, this is a schema + protocol change, not a config tweak. Worth deciding *now* whether that's coming, since it changes how much to invest in generalizing `streaming.services`. ([SRS §10, constraints](docs/design/02-software-requirements-specification.md#10-constraints))
2. **`CORS_ALLOW_ALL_ORIGINS` + open `ALLOWED_HOSTS`.** Fine for a trusted LAN pilot, not fine for anything beyond it. This needs to be an explicit release gate, not something we remember to fix later. ([SRS REQ-SEC-004](docs/design/02-software-requirements-specification.md#7-security-requirements))
3. **`streaming/` has no dedicated unit tests yet** (`telemetry` and `dashboard` do). The session state machine and safety transitions in §5/§6 above are exactly the kind of logic that should have tests before it has more features stacked on it.
4. **Static shared device secret.** Acceptable for a closed LAN; if the Jetson ever talks to Django over anything less trusted, we need short-lived tokens instead of a long-lived `.env` value.
5. **Alert delivery has no retry/ack today** beyond "it's safely persisted." If Flutter is disconnected when an alert fires, the clinician only sees it on next fetch (`GET /api/sessions/{id}/alerts/`), not push-retried. Is that acceptable, or do we want a "you have unseen alerts" nudge on reconnect?

---

# 8. Who to loop in on what

| If the conversation is about... | Point them at |
|---|---|
| Process, deliverables, who reviews what | [SDP](docs/design/01-software-development-plan.md) |
| "Should the system do X?" / safety behavior | [SRS](docs/design/02-software-requirements-specification.md) |
| "Which app should this code live in?" | [SADD](docs/design/03-software-architectural-design.md) |
| "What exactly does this function/message look like?" | [SDD](docs/design/04-software-detailed-design.md) |
| "What actually happens on the wire?" (existing doc) | [README_WebRTC.md](README_WebRTC.md) |

---

# 9. Bottom line

> Flutter starts and controls the session. Django validates everything and coordinates signaling but never touches a video frame — that goes Jetson → Flutter directly over WebRTC once negotiation completes. Alerts are safety-relevant: written to the database before they're ever forwarded, and a dropped device is never silently treated as "still monitoring." The system is deliberately scoped to one Jetson today; multi-device is a real design decision, not a small change, if it's needed next.
