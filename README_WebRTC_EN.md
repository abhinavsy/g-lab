# Jetson → Django → Flutter WebRTC Video Streaming

> **Language:** English (translation of [`README_WebRTC.md`](README_WebRTC.md))
> **Network:** Same local Wi-Fi / LAN
> **Internet:** Not required for local streaming

---

# 1. Overview

In this system, live camera video from an NVIDIA Jetson is streamed to the Flutter application using WebRTC.

The Jetson, Django Backend, and Flutter all run on the same local Wi-Fi/LAN network.

Main components:

- **Flutter App** — User interface, session control
- **Django Backend** — API, authentication, session management, WebSocket, WebRTC signaling
- **Jetson** — Camera capture, AI/inference, H.264 encoding, WebRTC sender
- **PostgreSQL** — Structured application/session/analysis data
- **MinIO** — Recordings, clips, media storage

---

# 2. Correct Architecture

```text
                         SAME LOCAL WI-FI / LAN


                    ┌──────────────────────┐
                    │      FLUTTER APP     │
                    │                      │
                    │ Login                │
                    │ Start Session        │
                    │ Stop Session         │
                    │ Device Controls      │
                    │ Live Video           │
                    │ Live Analysis        │
                    └──────────┬───────────┘
                               │
                    REST / WebSocket
                    Commands + Signaling
                               │
                               ▼
                    ┌──────────────────────┐
                    │    DJANGO BACKEND    │
                    │                      │
                    │ Authentication      │
                    │ REST API             │
                    │ WebSocket           │
                    │ WebRTC Signaling     │
                    │ Session Management   │
                    │ Business Logic       │
                    └──────────┬───────────┘
                               │
                     WebSocket / Signaling
                     Start/Stop Commands
                               │
                               ▼
                    ┌──────────────────────┐
                    │        JETSON        │
                    │                      │
                    │ Camera               │
                    │ AI / Inference       │
                    │ GStreamer            │
                    │ H.264 Encoder        │
                    │ WebRTC Sender        │
                    └──────────┬───────────┘
                               │
                               │
                    ╔══════════▼══════════╗
                    ║       WEBRTC        ║
                    ║    Actual Video     ║
                    ╚══════════╤══════════╝
                               │
                               ▼
                    ┌──────────────────────┐
                    │      FLUTTER APP     │
                    │                      │
                    │     LIVE VIDEO       │
                    └──────────────────────┘


              ┌──────────── DJANGO DATA LAYER ────────────┐
              │                                           │
              │   ┌──────────────┐  ┌──────────────┐      │
              │   │ PostgreSQL   │  │    MinIO     │      │
              │   │              │  │              │      │
              │   │ Sessions     │  │ Recordings   │      │
              │   │ Analysis     │  │ Video Clips  │      │
              │   │ Events       │  │ Media Files  │      │
              │   └──────────────┘  └──────────────┘      │
              │                                           │
              └───────────────────────────────────────────┘
```

---

# 3. Key Concept

In this architecture, **the application/session flow starts from Flutter.**

```text
Flutter
   ↓
Django
   ↓
Jetson
```

Flutter never controls the Jetson directly.

Flutter sends a command to Django. Django validates the request and sends the necessary command to the Jetson.

Once WebRTC negotiation is complete, the actual video does not go through Django.

```text
Jetson ═══════════════════> Flutter
             WebRTC
          Actual Video
```

---

# 4. Working Flow

## Step 1 — Flutter Starts

The user opens the Flutter application and logs in.

```text
User
 ↓
Flutter
 ↓
Django
```

Flutter establishes a WebSocket connection with Django.

This WebSocket is used for:

- Commands
- Session events
- Device status
- WebRTC signaling
- Analysis data relay (Flutter → Django, to be saved)

Live analysis data first arrives directly from Jetson to Flutter over WebRTC; Flutter then relays it to Django over this WebSocket.

---

# 5. Step 2 — Selecting Device / Session

The user selects:

- Patient
- Jetson device
- Session

Example:

```text
Patient: PAT001
Device:  JETSON001
```

---

# 6. Step 3 — START SESSION

The user clicks:

```text
START SESSION
```

in Flutter.

Flutter sends a request to Django.

```text
Flutter
   │
   │ START_SESSION
   ▼
Django
```

Example:

```json
{
  "type": "start_session",
  "patient_id": "PAT001"
}
```

**`device_id` is not needed** — this project has only one Jetson, there is no `Device`
model (`streaming/services.py`); the Jetson's id/secret live in settings
(`JETSON_DEVICE_ID`, `JETSON_AUTH_TOKEN` — `.env`). Django always
targets that one Jetson. If `device_id` is passed, it must
match `JETSON_DEVICE_ID`, otherwise an error occurs.

---

# 7. Step 4 — Django Validates

Django checks:

```text
User authenticated?
        ↓
Patient valid?
        ↓
Device exists?
        ↓
Device online?
        ↓
Another session running?
        ↓
Create session
```

Example:

```text
Session ID: SES001
Status: STARTING
```

---

# 8. Step 5 — What Django Tells the Jetson

Django sends a WebSocket command to the Jetson.

```text
Flutter
   │
   │ START_SESSION
   ▼
Django
   │
   │ START_STREAM
   ▼
Jetson
```

Example:

```json
{
  "type": "start_stream",
  "session_id": "SES001"
}
```

Meaning:

> Start the stream for session SES001.

---

# 9. Step 6 — Jetson Starts Camera + AI

After the Jetson receives the command:

```text
Camera
   ↓
Video Capture
   ↓
Jetson Processing
   ├──────────────> AI / Inference
   │                     ↓
   │                Analysis Data
   │
   └──────────────> H.264 Encoder
                         ↓
                      WebRTC
```

Jetson:

1. Starts the camera
2. Captures video
3. Starts AI/inference
4. Starts H.264 encoding
5. Starts the WebRTC pipeline

---

# 10. WebRTC Signaling Flow

**The application-level signaling workflow is initiated from Flutter.**

Flutter sends a stream request:

```text
Flutter
   │
   │ START_STREAM
   ▼
Django
   │
   │ REQUEST_STREAM
   ▼
Jetson
```

Since the Jetson is the video sender, it creates the SDP Offer.

```text
Jetson
   │
   │ SDP OFFER
   ▼
Django
   │
   │ SDP OFFER
   ▼
Flutter
```

Flutter receives the Offer and creates the SDP Answer.

```text
Flutter
   │
   │ SDP ANSWER
   ▼
Django
   │
   │ SDP ANSWER
   ▼
Jetson
```

Then ICE candidates are exchanged.

```text
Jetson
   │
   │ ICE Candidate
   ▼
Django
   │
   ▼
Flutter

Flutter
   │
   │ ICE Candidate
   ▼
Django
   │
   ▼
Jetson
```

---

# 11. Flutter Initiates, Jetson Offers

This is very important.

### Application initiation

```text
Flutter → Django → Jetson
```

Flutter is the one that starts the session/stream workflow.

### SDP negotiation

```text
Jetson → Django → Flutter
       SDP Offer
```

Since the Jetson is the video sender, the Jetson creates the SDP Offer.

After that:

```text
Flutter → Django → Jetson
       SDP Answer
```

So the correct description is:

> **Flutter initiates the application/session and signaling workflow; Jetson generates the WebRTC SDP Offer after being instructed to start the stream.**

---

# 12. WebRTC Connection Established

Once the Offer, Answer, and ICE candidate exchange are complete:

```text
WEBRTC CONNECTED
```

Then:

```text
Jetson ═══════════════════> Flutter
             WebRTC
          Actual Video
```

**Django is not in the actual video path here.**

---

# 13. Actual Video Flow

```text
Camera
   ↓
Jetson
   ↓
GStreamer
   ↓
H.264 Hardware Encoder
   ↓
WebRTC
   ↓
Local Wi-Fi
   ↓
Flutter
   ↓
Video Renderer
```

Actual media path:

```text
Jetson ═══════════════════> Flutter
             WebRTC
          Actual Video
```

---

# 14. AI / Analysis Data Flow

The Jetson processes camera data.

```text
Camera
   ↓
Jetson
   ├──────────────> AI / Inference
   │                     ↓
   │                Analysis Data
   │
   └──────────────> WebRTC
```

Example:

```json
{
  "session_id": "SES001",
  "hip_angle": 32.5,
  "knee_angle": 45.2,
  "speed": 1.2,
  "spasm_detected": false
}
```

Analysis flow:

```text
Jetson
   │
   │ WebRTC (Data Channel)
   ▼
Flutter
   │
   │ WebSocket
   ▼
Django
   │
   └──────────────> PostgreSQL
```

Analysis data, like the actual video, goes directly from Jetson to Flutter over WebRTC (it does not pass through Django). After Flutter receives the analysis data, it sends it to Django over the WebSocket. Django saves it in PostgreSQL.

Django can save the data to the database and also send it live to Flutter.

---

# 15. Device Commands

All device control commands are initiated from Flutter.

```text
Flutter
   │
   │ Command
   ▼
Django
   │
   │ Command
   ▼
Jetson
```

Examples:

```text
START
STOP
PAUSE
RESUME
SET_SPEED
SET_RESISTANCE
CHANGE_MODE
```

After Django checks authorization/business rules, the command can be sent to the Jetson.

---

# 16. Alert Flow

Jetson detects:

```text
SPASM DETECTED
```

Flow:

```text
Jetson
   │
   │ Event
   ▼
Django
   ├──────────────> PostgreSQL
   │
   └──────────────> Flutter
```

Flutter shows a live alert:

```text
⚠ SPASM DETECTED
```

---

# 17. Recording Flow

Live video:

```text
Jetson ═════ WebRTC ═════> Flutter
```

If recording is needed, a separate recording pipeline can be used — but the file
is not written directly by the Jetson to MinIO. Once the session finalizes, the Jetson
uploads the recorded clip through Django's REST API (`POST
/api/sessions/{session_id}/recordings/`, device token auth); Django writes that
file to MinIO and keeps the metadata in PostgreSQL.

**Who sends it, and in what format:**

- **Only the Jetson sends it** — Flutter does not have the raw recording file
  in hand (it only ever gets the live WebRTC stream); it is the Jetson that
  records locally via GStreamer and, after "Finalize Recording" (§17), ends up
  with the file in hand.
- **Body:** `multipart/form-data` — a `.mp4` produced by the GStreamer/H.264
  encoder (`recording.mp4` / `clip_001.mp4` / ...) in a `file` part, along with
  `clip_index` (int) and optional `duration_seconds` (float) as normal
  form fields.
- **Auth:** `Authorization: Device <JETSON_AUTH_TOKEN>` header — the Jetson has
  no Django user/JWT (there's only one Jetson, no `Device` model); this is the
  same settings-based shared secret used on the signaling WebSocket
  (`streaming/authentication.py` `DeviceTokenAuthentication`).
- **Response:** `201` — the saved `Recording` row (id, clip_index,
  duration_seconds, signed MinIO `url`).
- **Why this REST POST instead of sending it (chunked/binary) over WebSocket:**
  `JetsonConsumer`/`FlutterConsumer` are both JSON-only, and that socket also
  carries time-sensitive control messages like signaling — sending a large
  binary file over it wouldn't be ideal.

```text
                    Jetson
                       │
              ┌────────┴────────┐
              │                 │
              ▼                 ▼
           WebRTC            Recording
              │              (finalized
              ▼               clip file)
           Flutter               │
                                  │ POST /api/sessions/{id}/recordings/
                                  │ (Authorization: Device <token>)
                                  ▼
                               Django
                                  │
                        ┌─────────┴─────────┐
                        ▼                   ▼
                   PostgreSQL             MinIO
                  (Recording row)     (actual file)
```

MinIO example:

```text
sessions/
└── SES001/
    ├── recording.mp4
    ├── clip_001.mp4
    └── clip_002.mp4
```

---

# 18. PostgreSQL vs MinIO

### PostgreSQL

Structured data:

```text
Users
Patients
Sessions
Analysis
Events
Metadata
```

(No `Devices` table — single-Jetson deployment, the device's id/secret live
in settings/`.env` instead; only its runtime online/offline flag is cached,
in Redis, not PostgreSQL. See §17 and `streaming/services.py`.)

### MinIO

Media/object data:

```text
Recordings
Video Clips
Images
Large Media Files
```

---

# 19. Session Stop

The user clicks:

```text
STOP SESSION
```

in Flutter.

```text
Flutter
   │
   │ STOP_SESSION
   ▼
Django
   │
   │ STOP_STREAM
   ▼
Jetson
```

Jetson:

```text
Stop Camera
     ↓
Stop AI
     ↓
Stop WebRTC
     ↓
Finalize Recording
     ↓
Upload Recording ──> Django (REST, device token) ──> MinIO
```

Django:

```text
Save final analysis
        ↓
Update session
        ↓
Session = COMPLETED
```

---

# 20. Complete End-to-End Flow

```text
USER
  │
  │ START SESSION
  ▼
FLUTTER
  │
  │ REST / WebSocket
  ▼
DJANGO
  │
  │ Validate
  │ Create Session
  │
  │ START_STREAM
  ▼
JETSON
  │
  ├── Start Camera
  ├── Start AI
  ├── Start H.264
  └── Create WebRTC Offer
          │
          │ SDP Offer
          ▼
       DJANGO
          │
          ▼
       FLUTTER
          │
          │ SDP Answer
          ▼
       DJANGO
          │
          ▼
       JETSON
          │
          │ ICE Candidate Exchange
          ▼
    WEBRTC CONNECTED
          │
          │
          ╞═══════════════════════╗
          │                       ║
          ▼                       ║
       FLUTTER                    ║
    LIVE VIDEO + ANALYSIS         ║
      (via WebRTC)                ║
          │                       ║
          │ WebSocket             ║
          ▼                       ║
       DJANGO ────────────────────╢
          │                       ║
          └──> PostgreSQL         ║
                                  ║
Flutter ── Commands ──> Django ──> Jetson
                                  ║
          ════════════════════════╝
```

---

# 21. Communication Summary

| Purpose | Flow | Technology |
|---|---|---|
| Start Session | Flutter → Django → Jetson | REST/WebSocket |
| Device Commands | Flutter → Django → Jetson | WebSocket |
| WebRTC Signaling | Jetson ↔ Django ↔ Flutter | WebSocket |
| Actual Video | Jetson → Flutter | WebRTC |
| Live Analysis | Jetson → Flutter | WebRTC (Data Channel) |
| Relay Analysis | Flutter → Django | WebSocket |
| Save Analysis | Django → PostgreSQL | PostgreSQL |
| Save Recording | Jetson → Django (REST, device token) → MinIO | REST / Object Storage |
| Alerts | Jetson → Django → Flutter | WebSocket |
| Stop Session | Flutter → Django → Jetson | WebSocket |

---

# 22. Same Wi-Fi / No Internet

Example:

```text
                 Wi-Fi Router
                      │
        ┌─────────────┼─────────────┐
        │             │             │
        ▼             ▼             ▼
      Jetson        Django        Flutter

  192.168.1.10   192.168.1.20   192.168.1.30
```

Internet:

```text
❌ Not required
```

Local network:

```text
✅ Required
```

Video can be streamed on the same LAN using local WebRTC connectivity.

---

# 23. STUN / TURN

For the initial same-LAN/offline setup, there's no need to depend on public STUN/TURN services.

Later, if devices need to communicate across different networks, STUN/TURN can be added.

For a fully offline system, the necessary signaling/TURN infrastructure should be hosted on the local network.

---

# 24. Recommended Technology Stack

| Component | Technology |
|---|---|
| Client | Flutter |
| Backend | Django |
| API | Django REST Framework |
| Signaling | Django Channels + WebSocket |
| Edge Device | NVIDIA Jetson |
| Camera | USB / CSI |
| Video Pipeline | GStreamer |
| Codec | H.264 |
| Video Transport | WebRTC |
| Database | PostgreSQL |
| Object Storage | MinIO |
| Network | Local Wi-Fi / LAN |

---

# 25. Final Architecture Diagram

```text
                           USER
                            │
                            │
                            ▼
                 ┌─────────────────────┐
                 │     FLUTTER APP     │
                 │                     │
                 │ Login               │
                 │ Start/Stop Session  │
                 │ Controls            │
                 │ Live Video          │
                 │ Live Analysis       │
                 └──────────┬──────────┘
                            │
                  REST / WebSocket
                            │
                            ▼
                 ┌─────────────────────┐
                 │   DJANGO BACKEND    │
                 │                     │
                 │ Authentication      │
                 │ REST API            │
                 │ WebSocket           │
                 │ WebRTC Signaling    │
                 │ Session Management  │
                 │ Business Logic      │
                 └──────────┬──────────┘
                            │
                    WebSocket Commands
                    WebRTC Signaling
                            │
                            ▼
                 ┌─────────────────────┐
                 │       JETSON        │
                 │                     │
                 │ Camera              │
                 │ AI / Inference      │
                 │ GStreamer           │
                 │ H.264 Encoder       │
                 │ WebRTC Sender       │
                 └──────────┬──────────┘
                            │
                            │
                  ╔═════════▼═════════╗
                  ║      WEBRTC       ║
                  ║                   ║
                  ║   ACTUAL VIDEO    ║
                  ║                   ║
                  ╚═════════╤═════════╝
                            │
                            ▼
                 ┌─────────────────────┐
                 │     FLUTTER APP     │
                 │                     │
                 │   LIVE VIDEO        │
                 └─────────────────────┘


             ┌──────────────── DJANGO ────────────────┐
             │                                        │
             │       ┌──────────────┐                 │
             │       │ PostgreSQL   │                 │
             │       │              │                 │
             │       │ Sessions     │                 │
             │       │ Analysis     │                 │
             │       │ Events       │                 │
             │       └──────────────┘                 │
             │                                        │
             │       ┌──────────────┐                 │
             │       │    MinIO     │                 │
             │       │              │                 │
             │       │ Recordings   │                 │
             │       │ Video Clips  │                 │
             │       └──────────────┘                 │
             │                                        │
             └────────────────────────────────────────┘
```

---

# 26. Final Principle

> **Flutter is the one that starts the application/session flow. Django validates the request, controls the session, and coordinates WebRTC signaling. Django tells the Jetson to start streaming. The Jetson creates the WebRTC Offer, and Flutter provides the Answer. Once negotiation is complete, the actual live video and live analysis data go directly from Jetson to Flutter over WebRTC (Django is not in between). Flutter then sends that analysis data to Django over the WebSocket, to be saved. Once the session finalizes, the Jetson uploads the recorded file to Django via the REST API (device token auth) — the Jetson does not write directly to MinIO; Django is the one that writes that file to MinIO. Control commands and stop/start signaling go through Django/WebSocket. PostgreSQL keeps the structured data and MinIO keeps the recordings/media, both through Django.**
