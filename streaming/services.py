"""Business logic shared by the REST API (streaming/views.py) and the
WebSocket consumers (streaming/consumers.py), so both entry points enforce
the same validation described in README_WebRTC.md #6-#9, #15, #16, #19.
"""

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from patient.models import Patient

from .models import AlertEvent, Recording, Session

# Single-Jetson deployment: there's no Device DB model. Online/offline state
# is the one piece of runtime state that would otherwise need a Device row,
# so it lives in the cache instead (Redis-backed — see config/settings.py
# CACHES — so it's consistent across every worker process, not just
# whichever one holds the Jetson's WebSocket).
_DEVICE_ONLINE_CACHE_KEY = "jetson:online"

# Single-Jetson, single-active-session deployment (start_session below
# refuses to start a second session while one is STARTING/ACTIVE) — so
# there's no need for per-session Channels groups. Every connected Flutter
# client just joins this one static group; the Jetson has its own static
# device group (device_group_name below). Django relays between the two
# groups directly, with no join/leave bookkeeping and no echo filtering
# (a message sent to one group can never reach the role that sent it).
APP_GROUP = "app_clients"

DEVICE_COMMANDS = {
    "START",
    "STOP",
    "PAUSE",
    "RESUME",
    "SET_SPEED",
    "SET_RESISTANCE",
    "CHANGE_MODE",
}


class ValidationError(Exception):
    """Raised for any business-rule failure; carries a client-safe message."""


def device_group_name(device_id: str) -> str:
    return f"device_{device_id}"


def _send_to_device(device_id: str, payload: dict) -> None:
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        device_group_name(device_id),
        {"type": "device.command", "message": payload},
    )


def _send_to_app(payload: dict) -> None:
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        APP_GROUP,
        {"type": "app.event", "message": payload},
    )


# ---------------------------------------------------------------------------
# Step 3/4/5 — START SESSION (README #6, #7, #8)
# ---------------------------------------------------------------------------
def start_session(*, user, patient_id: str, device_id: str | None = None) -> Session:
    """Starts one session covering *all* cameras on the (one, only) Jetson —
    it decides internally how many cameras it has and streams/records every
    one of them for this session; Django/Flutter never select a
    `camera_id`. `device_id` is optional and, if given, must match
    settings.JETSON_DEVICE_ID — there's nothing to "pick" with one device."""
    if not (user and user.is_authenticated):
        raise ValidationError("User authenticated?")

    if device_id and device_id != settings.JETSON_DEVICE_ID:
        raise ValidationError("Device exists?")

    try:
        patient = Patient.objects.get(patient_id=patient_id)
    except Patient.DoesNotExist as exc:
        raise ValidationError("Patient valid?") from exc

    if not is_device_online():
        raise ValidationError("Device online?")

    if Session.objects.filter(status__in=[Session.Status.STARTING, Session.Status.ACTIVE]).exists():
        raise ValidationError("Another session already running on this device?")

    session = Session.objects.create(
        patient=patient,
        device_id=settings.JETSON_DEVICE_ID,
        started_by=user,
        status=Session.Status.STARTING,
        started_at=timezone.now(),
    )

    _send_to_device(
        settings.JETSON_DEVICE_ID,
        {"type": "start_stream", "session_id": session.session_id},
    )
    return session


# ---------------------------------------------------------------------------
# Step — STOP SESSION (README #19)
# ---------------------------------------------------------------------------
def stop_session(*, session: Session) -> Session:
    if session.status not in (Session.Status.STARTING, Session.Status.ACTIVE):
        raise ValidationError(f"Session is not active (status={session.status}).")

    session.status = Session.Status.STOPPING
    session.save(update_fields=["status"])

    _send_to_device(
        session.device_id,
        {"type": "stop_stream", "session_id": session.session_id},
    )
    return session


def finalize_session(*, session: Session, failed: bool = False) -> Session:
    """Called once Jetson confirms camera/AI/WebRTC teardown is complete."""
    session.status = Session.Status.FAILED if failed else Session.Status.COMPLETED
    session.ended_at = timezone.now()
    session.save(update_fields=["status", "ended_at"])
    _send_to_app({"type": "session_status", "session_id": session.session_id, "status": session.status})
    return session


def mark_session_active(*, session: Session) -> Session:
    """Called once WebRTC negotiation completes (README #12)."""
    if session.status == Session.Status.STARTING:
        session.status = Session.Status.ACTIVE
        session.save(update_fields=["status"])
        _send_to_app({"type": "session_status", "session_id": session.session_id, "status": session.status})
    return session


# ---------------------------------------------------------------------------
# Device commands (README #15)
# ---------------------------------------------------------------------------
def send_device_command(*, session: Session, command: str, params: dict | None = None) -> None:
    command = command.upper()
    if command not in DEVICE_COMMANDS:
        raise ValidationError(f"Unknown command: {command}")
    if session.status not in (Session.Status.STARTING, Session.Status.ACTIVE):
        raise ValidationError("Session is not active.")

    _send_to_device(
        session.device_id,
        {
            "type": "device_command",
            "session_id": session.session_id,
            "command": command,
            "params": params or {},
        },
    )


# ---------------------------------------------------------------------------
# WebRTC signaling relay (README #10, #11, #12)
# ---------------------------------------------------------------------------
def relay_signal(*, sender_role: str, payload: dict) -> None:
    """Forward an SDP offer/answer or ICE candidate to the other side.
    `sender_role` is "jetson" or "flutter" — whichever one *didn't* send it.
    Single-Jetson, single-active-session deployment, so there's exactly one
    peer on each side; no session_id-based addressing needed."""
    if sender_role == "jetson":
        _send_to_app(payload)
    else:
        _send_to_device(settings.JETSON_DEVICE_ID, payload)


# Analysis relay + persistence (README #14) now lives in telemetry.services
# (see streaming/consumers.py FlutterConsumer._handle_analysis_data) — that's
# the actual Flutter -> Django data transfer, split out from this module's
# Django<->Jetson/Flutter control-plane logic.


# ---------------------------------------------------------------------------
# Recording upload (README #17) — Jetson finalizes a clip locally, then
# uploads it here (SessionViewSet.recordings, POST) instead of writing to
# MinIO itself. Django is the only thing that talks to MinIO.
# ---------------------------------------------------------------------------
def save_recording(*, session: Session, file, clip_index: int = 0, duration_seconds: float | None = None) -> Recording:
    """Write an uploaded recording/clip through to MinIO (Recording.file,
    S3Storage backend — see config/settings.py STORAGES) and persist its
    metadata in PostgreSQL (README #18)."""
    return Recording.objects.create(
        session=session,
        file=file,
        clip_index=clip_index,
        duration_seconds=duration_seconds,
    )


# ---------------------------------------------------------------------------
# Alerts (README #16)
# ---------------------------------------------------------------------------
def record_alert(*, session: Session, alert_type: str, message: str = "", payload: dict | None = None) -> AlertEvent:
    alert = AlertEvent.objects.create(
        session=session,
        alert_type=alert_type,
        message=message,
        payload=payload or {},
    )
    _send_to_app(
        {
            "type": "alert",
            "session_id": session.session_id,
            "alert_type": alert.alert_type,
            "message": alert.message,
            "payload": alert.payload,
        }
    )
    return alert


# ---------------------------------------------------------------------------
# Jetson online/offline (no Device model — see module docstring/models.py).
# Set from JetsonConsumer.connect/disconnect; read from start_session.
#
# Reference-counted rather than a blind on/off flag: AUTH_DISABLED (or any
# client hitting ws/jetson/<JETSON_DEVICE_ID>/) lets more than one
# connection register as "the Jetson" at once — e.g. a passive observer
# like web_test_listen.py connected alongside the real device. Without
# counting, that observer's disconnect would call mark_device_offline()
# and wipe the flag out from under the still-connected real device.
# _DEVICE_CONN_COUNT_KEY only ever reaches 0 once every such connection has
# disconnected, which is when the device is actually reported offline.
# ---------------------------------------------------------------------------
_DEVICE_CONN_COUNT_KEY = "jetson:conn_count"


def mark_device_online() -> None:
    try:
        cache.incr(_DEVICE_CONN_COUNT_KEY)
    except ValueError:
        # Key doesn't exist yet (first connection, or count previously hit
        # 0 and got cleared) — initialize it. A simultaneous first-connect
        # from two connections could race here and both set(1) instead of
        # incrementing to 2; acceptable at this single-device dev/test
        # scale, same as the rest of this module's assumptions.
        cache.set(_DEVICE_CONN_COUNT_KEY, 1, timeout=None)
    cache.set(_DEVICE_ONLINE_CACHE_KEY, timezone.now().isoformat(), timeout=None)


def mark_device_offline() -> None:
    try:
        remaining = cache.decr(_DEVICE_CONN_COUNT_KEY)
    except ValueError:
        remaining = 0
    if remaining <= 0:
        cache.delete(_DEVICE_CONN_COUNT_KEY)
        cache.delete(_DEVICE_ONLINE_CACHE_KEY)


def is_device_online() -> bool:
    return cache.get(_DEVICE_ONLINE_CACHE_KEY) is not None


def device_last_seen_at() -> str | None:
    return cache.get(_DEVICE_ONLINE_CACHE_KEY)


# ---------------------------------------------------------------------------
# settings.AUTH_DISABLED support — a fixed dev user stands in for whoever
# would normally have logged in with a JWT, so start_session's "User
# authenticated?" check (and anything else needing a real user FK) still
# has something valid to point at. See streaming/authentication.py
# DisabledAuthAuthentication and streaming/auth.py TokenAuthMiddleware.
# ---------------------------------------------------------------------------
def get_or_create_dev_user():
    from django.contrib.auth import get_user_model

    User = get_user_model()
    user, _ = User.objects.get_or_create(username="dev", defaults={"is_active": True})
    return user
