# Jetson → Django → Flutter WebRTC Video Streaming

> **ഭാഷ:** മലയാളം  
> **Network:** ഒരേ Local Wi-Fi / LAN  
> **Internet:** Local streaming-ന് Internet ആവശ്യമില്ല

---

# 1. Overview

ഈ system-ൽ NVIDIA Jetson-ൽ നിന്നുള്ള live camera video Flutter application-ലേക്ക് WebRTC ഉപയോഗിച്ച് stream ചെയ്യുന്നു.

Jetson, Django Backend, Flutter എന്നിവ ഒരേ local Wi-Fi/LAN network-ൽ പ്രവർത്തിക്കാം.

പ്രധാന components:

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
                    │ WebSocket            │
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

# 3. പ്രധാന ആശയം

ഈ architecture-ൽ **application/session flow Flutter-ൽ നിന്നാണ് ആരംഭിക്കുന്നത്.**

```text
Flutter
   ↓
Django
   ↓
Jetson
```

Flutter നേരിട്ട് Jetson-നെ control ചെയ്യില്ല.

Flutter command Django-ലേക്ക് അയക്കും. Django request validate ചെയ്ത് Jetson-ന് ആവശ്യമായ command അയക്കും.

WebRTC negotiation കഴിഞ്ഞാൽ actual video Django വഴി പോകില്ല.

```text
Jetson ═══════════════════> Flutter
             WebRTC
          Actual Video
```

---

# 4. Working Flow

## Step 1 — Flutter Start ചെയ്യുന്നു

User Flutter application തുറന്ന് login ചെയ്യുന്നു.

```text
User
 ↓
Flutter
 ↓
Django
```

Flutter Django-യുമായി WebSocket connection establish ചെയ്യും.

ഈ WebSocket ഉപയോഗിക്കുന്നത്:

- Commands
- Session events
- Device status
- WebRTC signaling
- Analysis data relay (Flutter → Django, save ചെയ്യാൻ)

എന്നിവയ്ക്കാണ്. Live analysis data ആദ്യം Jetson-ൽ നിന്ന് നേരിട്ട് Flutter-ലേക്ക് WebRTC വഴിയാണ് വരുന്നത്; Flutter അത് ഈ WebSocket വഴി Django-ലേക്ക് relay ചെയ്യുന്നു.

---

# 5. Step 2 — Device / Session Select ചെയ്യുന്നു

User:

- Patient
- Jetson device
- Session

select ചെയ്യും.

ഉദാഹരണം:

```text
Patient: PAT001
Device:  JETSON001
```

---

# 6. Step 3 — START SESSION

User Flutter-ൽ:

```text
START SESSION
```

click ചെയ്യുന്നു.

Flutter Django-ലേക്ക് request അയക്കും.

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

**`device_id` വേണ്ട** — ഈ project-ൽ ഒരു Jetson മാത്രമേയുള്ളൂ, `Device` model
ഇല്ല (`streaming/services.py`); Jetson-ന്റെ id/secret settings-ൽ ആണ്
(`JETSON_DEVICE_ID`, `JETSON_AUTH_TOKEN` — `.env`). Django എപ്പോഴും ആ ഒരു
Jetson-നെ target ചെയ്യും. `device_id` pass ചെയ്താൽ അത്
`JETSON_DEVICE_ID`-യുമായി match ആകണം, അല്ലെങ്കിൽ error വരും.

---

# 7. Step 4 — Django Validate ചെയ്യുന്നു

Django പരിശോധിക്കും:

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

ഉദാഹരണം:

```text
Session ID: SES001
Status: STARTING
```

---

# 8. Step 5 — Django Jetson-നോട് പറയുന്നത്

Django Jetson-ന് WebSocket command അയക്കും.

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

അർത്ഥം:

> SES001 session-ന് stream start ചെയ്യുക.

---

# 9. Step 6 — Jetson Camera + AI Start ചെയ്യുന്നു

Jetson command receive ചെയ്ത ശേഷം:

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

1. Camera start ചെയ്യും
2. Video capture ചെയ്യും
3. AI/inference start ചെയ്യും
4. H.264 encoding start ചെയ്യും
5. WebRTC pipeline start ചെയ്യും

---

# 10. WebRTC Signaling Flow

**Application-level signaling workflow Flutter-ൽ നിന്നാണ് initiate ചെയ്യുന്നത്.**

Flutter stream request അയക്കും:

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

Jetson video sender ആയതിനാൽ SDP Offer create ചെയ്യും.

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

Flutter Offer receive ചെയ്ത് SDP Answer create ചെയ്യും.

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

ശേഷം ICE candidates exchange ചെയ്യും.

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

ഇത് വളരെ പ്രധാനമാണ്.

### Application initiation

```text
Flutter → Django → Jetson
```

Flutter ആണ് session/stream workflow ആരംഭിക്കുന്നത്.

### SDP negotiation

```text
Jetson → Django → Flutter
       SDP Offer
```

Jetson video sender ആയതിനാൽ Jetson SDP Offer create ചെയ്യുന്നു.

അതിന് ശേഷം:

```text
Flutter → Django → Jetson
       SDP Answer
```

അതിനാൽ ശരിയായ description:

> **Flutter initiates the application/session and signaling workflow; Jetson generates the WebRTC SDP Offer after being instructed to start the stream.**

---

# 12. WebRTC Connection Establish

Offer, Answer, ICE candidate exchange complete ആയാൽ:

```text
WEBRTC CONNECTED
```

ശേഷം:

```text
Jetson ═══════════════════> Flutter
             WebRTC
          Actual Video
```

**ഇവിടെ Django actual video path-ൽ ഇല്ല.**

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

Jetson camera data process ചെയ്യുന്നു.

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

Analysis data actual video-യെ പോലെ WebRTC വഴി Jetson-ൽ നിന്ന് നേരിട്ട് Flutter-ലേക്ക് പോകുന്നു (Django-യെ കടക്കുന്നില്ല). Flutter analysis data receive ചെയ്ത ശേഷം അത് WebSocket വഴി Django-ലേക്ക് അയക്കുന്നു, Django അത് PostgreSQL-ൽ save ചെയ്യുന്നു.

Django data database-ൽ save ചെയ്യുകയും Flutter-ലേക്ക് live ആയി അയക്കുകയും ചെയ്യാം.

---

# 15. Device Commands

Device control commands എല്ലാം Flutter-ൽ നിന്നാണ് initiate ചെയ്യുന്നത്.

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

Django authorization/business rules പരിശോധിച്ച ശേഷം command Jetson-ലേക്ക് അയക്കാം.

---

# 16. Alert Flow

Jetson detect ചെയ്തു:

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

Flutter:

```text
⚠ SPASM DETECTED
```

എന്ന് live alert കാണിക്കും.

---

# 17. Recording Flow

Live video:

```text
Jetson ═════ WebRTC ═════> Flutter
```

Recording വേണമെങ്കിൽ separate recording pipeline ഉപയോഗിക്കാം — പക്ഷേ ഫയൽ
Jetson നേരിട്ട് MinIO-ലേക്ക് എഴുതില്ല. Session finalize ആയാൽ Jetson recorded
clip Django REST API വഴി upload ചെയ്യുന്നു (`POST
/api/sessions/{session_id}/recordings/`, device token auth); Django ആ ഫയൽ
MinIO-ലേക്ക് write ചെയ്ത് PostgreSQL-ൽ metadata സൂക്ഷിക്കുന്നു.

**ആരാണ് അയക്കുന്നത്, എന്ത് format-ൽ:**

- **അയക്കുന്നത് Jetson മാത്രം** — Flutter-ന്റെ കയ്യിൽ raw recording file
  ഇല്ല (അതിന് live WebRTC stream മാത്രമേ കിട്ടൂ); Jetson ആണ് GStreamer വഴി
  locally record ചെയ്ത് "Finalize Recording" (§19) കഴിഞ്ഞ് ഫയൽ കയ്യിൽ
  വരുന്നത്.
- **Body:** `multipart/form-data` — ഒരു `file` part-ൽ GStreamer/H.264
  encoder ഉണ്ടാക്കിയ `.mp4` (`recording.mp4` / `clip_001.mp4` / ...), കൂടെ
  `clip_index` (int), optional `duration_seconds` (float) സാധാരണ form
  fields ആയി.
- **Auth:** `Authorization: Device <JETSON_AUTH_TOKEN>` header — Jetson-ന്
  Django user/JWT ഇല്ല (ഒരു Jetson മാത്രം, `Device` model ഇല്ല), signaling
  WebSocket-ൽ ഉപയോഗിക്കുന്ന അതേ settings-based shared secret തന്നെ ഇവിടെയും
  (`streaming/authentication.py` `DeviceTokenAuthentication`).
- **Response:** `201` — സേവ് ചെയ്ത `Recording` row (id, clip_index,
  duration_seconds, signed MinIO `url`).
- ഈ REST POST അല്ലാതെ WebSocket വഴി (chunked/binary) അയക്കാത്തതിന്റെ
  കാരണം: `JetsonConsumer`/`FlutterConsumer` രണ്ടും JSON-only ആണ്, ആ socket
  signaling പോലുള്ള time-sensitive control messages-ഉം carry ചെയ്യുന്നു —
  വലിയ binary file അതിലൂടെ അയക്കുന്നത് ideal അല്ല.

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

User Flutter-ൽ:

```text
STOP SESSION
```

click ചെയ്യുന്നു.

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
❌ ആവശ്യമില്ല
```

Local network:

```text
✅ ആവശ്യമാണ്
```

Same LAN-ൽ local WebRTC connectivity ഉപയോഗിച്ച് video stream ചെയ്യാം.

---

# 23. STUN / TURN

Initial same-LAN/offline setup-ൽ public STUN/TURN services dependency ആക്കേണ്ടതില്ല.

Later different networks-ൽ devices communicate ചെയ്യണമെങ്കിൽ STUN/TURN add ചെയ്യാം.

Fully offline system ആണെങ്കിൽ ആവശ്യമായ signaling/TURN infrastructure local network-ൽ host ചെയ്യണം.

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

> **Flutter ആണ് application/session flow ആരംഭിക്കുന്നത്. Django request validate ചെയ്ത് session control ചെയ്യുകയും WebRTC signaling coordinate ചെയ്യുകയും ചെയ്യുന്നു. Django Jetson-നോട് stream start ചെയ്യാൻ പറയുന്നു. Jetson WebRTC Offer create ചെയ്യുന്നു, Flutter Answer നൽകുന്നു. Negotiation കഴിഞ്ഞാൽ actual live video-യും live analysis dataയും Jetson-ൽ നിന്ന് നേരിട്ട് Flutter-ലേക്ക് WebRTC വഴി പോകുന്നു (Django ഇടയിൽ ഇല്ല). Flutter ആ analysis data പിന്നീട് WebSocket വഴി Django-ലേക്ക് അയക്കുന്നു, save ചെയ്യാൻ. Session finalize ആയാൽ Jetson recorded ഫയൽ Django REST API വഴി (device token auth) upload ചെയ്യുന്നു — Jetson MinIO-ലേക്ക് നേരിട്ട് എഴുതുന്നില്ല, Django ആണ് ആ ഫയൽ MinIO-ലേക്ക് write ചെയ്യുന്നത്. Control commandsഉം stop/start signaling-ഉം Django/WebSocket വഴി പോകുന്നു. PostgreSQL structured dataയും MinIO recordings/mediaയും Django വഴി തന്നെ സൂക്ഷിക്കുന്നു.**
