
# Folder Structure

> **ഭാഷ:** മലയാളം

---

# 1. Overview

ഈ Django project-ൽ നാല് Django apps ഉണ്ട് — `streaming`, `telemetry`, `dashboard`, പിന്നെ project-level `config`. ഓരോ app-നും ഒരു വ്യക്തമായ ഉത്തരവാദിത്തം (responsibility) മാത്രമേ ഉള്ളൂ, അതുകൊണ്ട് ഏത് data ഏത് ഭാഗത്തുകൂടെ പോകുന്നു എന്ന് കണ്ടെത്താൻ എളുപ്പമാണ്.

```text
g-lab/
├── manage.py
├── requirements.txt
├── docker-compose.yml
├── .env.example
├── README.md
├── README_WebRTC.md
├── README_FOLDER_STRUCTURE.md   (ഈ file)
│
├── config/            → Project settings, URLs, ASGI/WSGI entrypoints
├── streaming/          → Control plane: Jetson ↔ Django ↔ Flutter (signaling, sessions, commands)
├── telemetry/          → Flutter → Django data transfer (analysis events മാത്രം)
├── dashboard/          → Cross-cutting listing/summary API (read-only)
│
├── jetson_mock/         → Real-Jetson-hardware ഇല്ലാതെ testing-നു വേണ്ടി:
│                           Python/aiortc script — real WebRTC (SDP/ICE/video),
│                           NUC-ൽ run ചെയ്യാം. AI/ML team-ന്റെ real Jetson code അല്ല.
└── flutter_app_mock/    → Real Flutter app അല്ലാത്ത, minimal test client —
                            login/session control/real WebRTC video render/
                            fake analysis_data. Django API test ചെയ്യാൻ.
```

`jetson_mock/` ഉം `flutter_app_mock/` ഉം Django project-ന്റെ ഭാഗമല്ല (വേറെ dependencies, വേറെ runtime) — ഇവ **test harnesses** മാത്രമാണ്, ഓരോന്നിനും അതിന്റേതായ README ഉണ്ട്.

---

# 2. `config/` — Project-level Configuration

Django project-ന്റെ "root" ഇവിടെയാണ്. ഇത് ഒരു app അല്ല — settings, routing, entrypoints മാത്രം.

```text
config/
├── settings.py   → INSTALLED_APPS, DATABASES (PostgreSQL), CHANNEL_LAYERS (Redis),
│                    MinIO/S3 storage, JWT config, CORS
├── urls.py       → Root URLConf: /admin/, /api/auth/, streaming/telemetry/dashboard urls include ചെയ്യുന്നു
├── asgi.py       → WebSocket routing-നു വേണ്ടി (Channels) — streaming/routing.py ഉപയോഗിക്കുന്നു
└── wsgi.py       → സാധാരണ HTTP (REST API) serve ചെയ്യാൻ
```

**ഓർക്കുക:** പുതിയ ഒരു app add ചെയ്യുമ്പോൾ `INSTALLED_APPS` (settings.py) ലും `urlpatterns` (urls.py) ലും register ചെയ്യണം — ഇത് ഇപ്പോൾ `telemetry`, `dashboard` apps-നു വേണ്ടി ചെയ്തിട്ടുണ്ട്.

---

# 3. `streaming/` — Control Plane (Jetson ↔ Django ↔ Flutter)

README_WebRTC.md-ൽ വിവരിച്ച signaling/session flow മുഴുവൻ ഇവിടെയാണ്. WebRTC media itself Django വഴി പോകില്ല — ഇത് session lifecycle, commands, alerts, recordings metadata മാത്രം handle ചെയ്യുന്നു.

```text
streaming/
├── models.py         → Patient, Session, AlertEvent, Recording
│                       (No Device/Camera model — one Jetson only; its
│                       id/secret live in settings, see services.py below)
├── serializers.py    → മുകളിലെ models-ന്റെ DRF serializers
├── views.py          → REST ViewSets (/api/patients/, /api/sessions/…) +
│                       DeviceStatusView (/api/device/status/, read-only)
├── services.py       → Business logic: start_session, stop_session, send_device_command,
│                       relay_signal, record_alert, mark_device_online/offline/is_device_online
│                       (REST ഉം WebSocket ഉം ഇത് share ചെയ്യുന്നു)
├── consumers.py      → WebSocket consumers:
│                       - JetsonConsumer  (ws/jetson/<JETSON_DEVICE_ID>/)
│                       - FlutterConsumer (ws/app/)
├── routing.py        → WebSocket URL routing (config/asgi.py ഇത് ഉപയോഗിക്കുന്നു)
├── auth.py           → WebSocket token auth (JWT for Flutter, JETSON_AUTH_TOKEN for Jetson)
├── authentication.py → DRF DeviceTokenAuthentication (recording upload, REST)
├── permissions.py    → IsAuthenticatedOrSessionDevice
├── admin.py          → Django admin registration
└── urls.py           → /api/ prefix-ന് താഴെയുള്ള REST routes
```

**ശ്രദ്ധിക്കുക:** `AlertEvent` ഇവിടെ തന്നെയാണ് — കാരണം അത് Jetson → Django ആണ് (Jetson നേരിട്ട് `alert` message അയക്കുന്നു JetsonConsumer-ലേക്ക്), Flutter → Django അല്ല.

---

# 4. `telemetry/` — Flutter → Django Data Transfer

ഇത് പുതിയതായി separate ചെയ്ത app ആണ്. **ശരിക്കും Flutter Django-ലേക്ക് അയക്കുന്ന ഒരേ ഒരു data ഇത് മാത്രമാണ്**: live AI analysis samples (hip angle, knee angle, speed, spasm detection...). ഇത് Jetson → Flutter (WebRTC data channel വഴി) വരും, എന്നിട്ട് Flutter അത് `ws/app/` WebSocket വഴി Django-ലേക്ക് relay ചെയ്യും (README_WebRTC.md #14).

```text
telemetry/
├── models.py       → AnalysisEvent (streaming.Session-ലേക്ക് FK)
├── serializers.py  → AnalysisEventSerializer
├── services.py      → record_analysis() — streaming/consumers.py FlutterConsumer ഇത് call ചെയ്യുന്നു
├── views.py         → SessionAnalysisListView
└── urls.py          → GET /api/sessions/{session_id}/analysis/
```

**എന്തിനാണ് ഇത് `streaming`-ൽ നിന്ന് വേറെയാക്കിയത്?** `streaming`-ലെ ബാക്കി എല്ലാം (sessions, commands, signaling, alerts) Django ↔ Jetson അല്ലെങ്കിൽ Django ↔ Flutter control-plane traffic ആണ്. `AnalysisEvent` മാത്രമാണ് ശരിക്കും ഒരു Flutter → Django *data transfer* — അതുകൊണ്ട് അതിന് സ്വന്തമായി ഒരു app.

---

# 5. `dashboard/` — Cross-Cutting Listing/Summary API

ഇതും models ഇല്ലാത്ത, read-only app ആണ് — `streaming`, `telemetry` apps-ലെ data query ചെയ്ത് session/patient/device സംബന്ധിച്ച **overview** views കൊടുക്കുന്നു. `streaming`-ലെ endpoints (e.g. alerts, analysis) ഓരോ session-നും scoped ആണ്; ഇവിടെ എല്ലാ sessions-ന്റെയും data ഒരുമിച്ച് list ചെയ്യാം.

```text
dashboard/
├── views.py   → DashboardSummaryView, SessionListView, AlertListView, AnalysisListView
└── urls.py    → /api/dashboard/summary/, /sessions/, /alerts/, /analysis/
```

---

# 6. Data Flow Summary (ആരാണ് ഏത് app owns ചെയ്യുന്നത്)

| Data / Flow | Direction | App |
|---|---|---|
| Session start/stop, device commands | Flutter → Django → Jetson | `streaming` |
| WebRTC signaling (SDP/ICE) relay | Jetson ↔ Django ↔ Flutter | `streaming` |
| Alerts (e.g. SPASM_DETECTED) | Jetson → Django | `streaming` |
| Recording/clip metadata | Jetson → Django (MinIO-ൽ file) | `streaming` |
| **Live analysis samples** | **Flutter → Django** | **`telemetry`** |
| Cross-session listing/summary | Django (internal query) | `dashboard` |

---

# 7. Root-level Files

```text
manage.py             → Django management command entrypoint
requirements.txt       → Python dependencies
docker-compose.yml     → PostgreSQL, Redis, MinIO (local dev services)
.env.example           → Environment variable template (config/settings.py ഇത് വായിക്കുന്നു)
README.md              → Project setup/quickstart
README_WebRTC.md        → പൂർണ്ണ WebRTC signaling architecture (Malayalam)
README_FOLDER_STRUCTURE.md → ഈ file
```
