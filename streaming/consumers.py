"""WebSocket consumers implementing README_WebRTC.md #10-#16.

Two connection types, both JSON-over-WebSocket:

- JetsonConsumer  — ws/jetson/<device_id>/   (persistent, one per device)
- FlutterConsumer — ws/app/                  (one per logged-in app session)

A single Jetson can run several cameras concurrently over that one
connection, but Django/Flutter address it by `session_id` only — the Jetson
decides internally which/how many of its own cameras to stream/record for
that session. There's no Device model either (single-Jetson deployment) —
its identity/secret live in settings.JETSON_DEVICE_ID/JETSON_AUTH_TOKEN
(see streaming/services.py, streaming/auth.py).

Django never touches the WebRTC media itself; these consumers only relay
signaling messages (SDP offer/answer, ICE candidates), forward validated
device commands, and persist analysis/alerts that the app relays back over
this same channel.

Single-Jetson, single-active-session deployment (streaming/services.py
start_session refuses a second concurrent session), so relaying doesn't need
per-session Channels groups: there are just two static groups — the Jetson's
device group (one Jetson) and services.APP_GROUP (every connected Flutter
client). Each consumer only ever receives group messages from the *other*
role, so there's no echo to filter either.
"""

import logging

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from rest_framework.exceptions import ValidationError as DRFValidationError

import patient.services
import telemetry.services

from . import services
from .models import Session

logger = logging.getLogger(__name__)

# Message types relayed as-is between Jetson and Flutter without Django
# needing to understand their contents (README #10, #12).
SIGNAL_PASSTHROUGH_TYPES = {"sdp_offer", "sdp_answer", "ice_candidate"}


class GetSessionMixin:
    """Shared DB lookup used by both consumers to validate a session_id."""

    @database_sync_to_async
    def _get_session(self, session_id: str) -> Session | None:
        return Session.objects.select_related("patient").filter(session_id=session_id).first()


class JetsonConsumer(GetSessionMixin, AsyncJsonWebsocketConsumer):
    """Persistent connection for the (one, only) Jetson device.

    Auth: ?token=<settings.JETSON_AUTH_TOKEN> (see streaming/auth.py). The
    device_id in the URL must match settings.JETSON_DEVICE_ID.
    """

    async def connect(self):
        self.device_id = self.scope.get("device_id")
        url_device_id = self.scope["url_route"]["kwargs"]["device_id"]

        if self.device_id is None or self.device_id != url_device_id:
            await self.close(code=4001)  # unauthenticated / wrong device token
            return

        await self.accept()
        await database_sync_to_async(services.mark_device_online)()
        await self.channel_layer.group_add(services.device_group_name(self.device_id), self.channel_name)

    async def disconnect(self, close_code):
        if getattr(self, "device_id", None) is None:
            return
        await self.channel_layer.group_discard(services.device_group_name(self.device_id), self.channel_name)
        await database_sync_to_async(services.mark_device_offline)()

    async def receive_json(self, content, **kwargs):
        msg_type = content.get("type")
        session_id = content.get("session_id")

        if msg_type in SIGNAL_PASSTHROUGH_TYPES:
            # Jetson is the WebRTC offerer (README #11); relay untouched.
            await database_sync_to_async(services.relay_signal)(sender_role="jetson", payload=content)

        elif msg_type == "webrtc_connected":
            session = await self._get_session(session_id)
            if session:
                await database_sync_to_async(services.mark_session_active)(session=session)

        elif msg_type == "alert":
            session = await self._get_session(session_id)
            if session:
                await database_sync_to_async(services.record_alert)(
                    session=session,
                    alert_type=content.get("alert_type", "OTHER"),
                    message=content.get("message", ""),
                    payload=content.get("payload", {}),
                )

        elif msg_type == "stream_stopped":
            # Jetson confirms camera/AI/WebRTC teardown + recording finalize
            # (README #19).
            session = await self._get_session(session_id)
            if session:
                await database_sync_to_async(services.finalize_session)(
                    session=session, failed=content.get("failed", False)
                )

        else:
            await self.send_json({"type": "error", "detail": f"Unknown message type: {msg_type}"})

    async def device_command(self, event):
        """Handler for type="device.command" group messages (from Django,
        originating in services.start_session / stop_session / send_device_command,
        or relayed from the Flutter client via services.relay_signal)."""
        await self.send_json(event["message"])


class FlutterConsumer(GetSessionMixin, AsyncJsonWebsocketConsumer):
    """Connection for the (one, only) logged-in Flutter app session.

    Auth: ?token=<JWT access token> from /api/auth/login/.
    """

    async def connect(self):
        user = self.scope.get("user")
        if user is None or not user.is_authenticated:
            await self.close(code=4001)
            return
        self.user = user
        await self.accept()
        await self.channel_layer.group_add(services.APP_GROUP, self.channel_name)

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(services.APP_GROUP, self.channel_name)

    async def receive_json(self, content, **kwargs):
        msg_type = content.get("type")

        if msg_type == "start_session":
            await self._handle_start_session(content)
        elif msg_type == "stop_session":
            await self._handle_stop_session(content)
        elif msg_type == "device_command":
            await self._handle_device_command(content)
        elif msg_type in SIGNAL_PASSTHROUGH_TYPES:
            await database_sync_to_async(services.relay_signal)(sender_role="flutter", payload=content)
        elif msg_type == "analysis_data":
            # Analysis arrives Jetson -> Flutter over the WebRTC data
            # channel (not via Django); Flutter relays it here to persist
            # it (README #14).
            await self._handle_analysis_data(content)
        elif msg_type == "session_report":
            await self._handle_session_report(content)
        else:
            await self.send_json({"type": "error", "detail": f"Unknown message type: {msg_type}"})

    async def app_event(self, event):
        """Handler for type="app.event" group messages (from Django, or
        relayed from the Jetson via services.relay_signal)."""
        await self.send_json(event["message"])

    async def _handle_start_session(self, content):
        try:
            session = await database_sync_to_async(services.start_session)(
                user=self.user,
                patient_id=content.get("patient_id"),
                device_id=content.get("device_id"),
            )
        except services.ValidationError as exc:
            await self.send_json({"type": "error", "detail": str(exc)})
            return
        await self.send_json(
            {"type": "session_started", "session_id": session.session_id, "status": session.status}
        )

    async def _handle_stop_session(self, content):
        session = await self._get_session(content.get("session_id"))
        if session is None:
            await self.send_json({"type": "error", "detail": "Session not found."})
            return
        try:
            session = await database_sync_to_async(services.stop_session)(session=session)
        except services.ValidationError as exc:
            await self.send_json({"type": "error", "detail": str(exc)})
            return
        await self.send_json({"type": "session_status", "session_id": session.session_id, "status": session.status})

    async def _handle_device_command(self, content):
        session = await self._get_session(content.get("session_id"))
        if session is None:
            await self.send_json({"type": "error", "detail": "Session not found."})
            return
        try:
            await database_sync_to_async(services.send_device_command)(
                session=session, command=content.get("command", ""), params=content.get("params", {})
            )
        except services.ValidationError as exc:
            await self.send_json({"type": "error", "detail": str(exc)})

    async def _handle_session_report(self, content):
        """Flutter saves the session's report (patient.SessionReport) — same
        as PUT /api/sessions/{session_id}/report/."""
        session_id = content.get("session_id")
        session = await self._get_session(session_id)
        if session is None:
            await self.send_json({"type": "error", "detail": "Session not found."})
            return
        try:
            report, created = await database_sync_to_async(patient.services.save_session_report)(
                session=session, data=content
            )
        except DRFValidationError as exc:
            await self.send_json({"type": "error", "detail": exc.detail})
            return
        await self.send_json({"type": "session_report_saved", "session_id": session_id, "created": created})

    async def _handle_analysis_data(self, content):
        session_id = content.get("session_id")
        session = await self._get_session(session_id)
        if session is None:
            logger.warning("analysis_data for unknown session_id=%s, dropped: %s", session_id, content)
            return
        await database_sync_to_async(telemetry.services.record_analysis)(session=session, payload=content)
        logger.info(
            "analysis_data persisted session_id=%s hip_angle_left=%s hip_angle_right=%s "
            "knee_angle_left=%s knee_angle_right=%s speed=%s spasm_detected=%s",
            session_id,
            content.get("hip_angle_left"),
            content.get("hip_angle_right"),
            content.get("knee_angle_left"),
            content.get("knee_angle_right"),
            content.get("speed"),
            content.get("spasm_detected"),
        )
