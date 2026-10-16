from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from django.conf import settings

from . import services
from .models import Session
from .permissions import IsAuthenticatedOrSessionDevice
from .serializers import (
    AlertEventSerializer,
    DeviceCommandSerializer,
    RecordingSerializer,
    RecordingUploadSerializer,
    SessionSerializer,
    StartSessionSerializer,
)


class DeviceStatusView(APIView):
    """GET /api/device/status/ — the single Jetson's identity/online status.

    No Device model/CRUD (single-Jetson deployment; see
    streaming/services.py): this just reads the cache-backed online flag
    the Jetson's WebSocket connect/disconnect sets.
    """

    def get(self, request):
        return Response(
            {
                "device_id": settings.JETSON_DEVICE_ID,
                "online": services.is_device_online(),
                "last_seen_at": services.device_last_seen_at(),
            }
        )


class SessionViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """REST counterpart to the WebSocket session-control flow described in
    README_WebRTC.md #6-#9 and #19. Flutter may use either transport; both
    end up in streaming/services.py so behaviour is identical.
    """

    queryset = Session.objects.select_related("patient").all()
    serializer_class = SessionSerializer
    lookup_field = "session_id"

    @action(detail=False, methods=["post"])
    def start(self, request):
        """POST /api/sessions/start/ {"patient_id": "PAT001"}

        `device_id` is optional and normally omitted entirely — there's no
        Device model, Django always targets the one configured Jetson
        (settings.JETSON_DEVICE_ID). Starts one session covering ALL
        cameras on that device — the Jetson streams/records every camera
        it has; there's no per-camera selection here.
        """
        serializer = StartSessionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            session = services.start_session(user=request.user, **serializer.validated_data)
        except services.ValidationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(SessionSerializer(session).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def stop(self, request, session_id=None):
        """POST /api/sessions/{session_id}/stop/"""
        session = self.get_object()
        try:
            session = services.stop_session(session=session)
        except services.ValidationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(SessionSerializer(session).data)

    @action(detail=True, methods=["post"], url_path="command")
    def send_command(self, request, session_id=None):
        """POST /api/sessions/{session_id}/command/ {"command": "SET_SPEED", "params": {...}}

        Device commands (README #15): START/STOP/PAUSE/RESUME/SET_SPEED/
        SET_RESISTANCE/CHANGE_MODE.
        """
        session = self.get_object()
        serializer = DeviceCommandSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            services.send_device_command(session=session, **serializer.validated_data)
        except services.ValidationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(status=status.HTTP_202_ACCEPTED)

    # Analysis events (README #14) moved to telemetry — see
    # GET /api/sessions/{session_id}/analysis/ in telemetry/urls.py.

    @action(detail=True, methods=["get"])
    def alerts(self, request, session_id=None):
        session = self.get_object()
        return Response(AlertEventSerializer(session.alerts.all(), many=True).data)

    @action(
        detail=True,
        methods=["get", "post"],
        parser_classes=[MultiPartParser, FormParser],
        permission_classes=[IsAuthenticatedOrSessionDevice],
    )
    def recordings(self, request, session_id=None):
        """GET: signed MinIO URLs for the session's recording + clips (#17, #18).

        POST: Jetson uploads the finished recording/clip here once it
        finalizes locally (README #19). Django writes it through to MinIO
        and stores the metadata row — the device never talks to MinIO
        directly. Auth: `Authorization: Device <settings.JETSON_AUTH_TOKEN>`.
        """
        session = self.get_object()

        if request.method == "POST":
            serializer = RecordingUploadSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            recording = services.save_recording(session=session, **serializer.validated_data)
            return Response(RecordingSerializer(recording).data, status=status.HTTP_201_CREATED)

        return Response(RecordingSerializer(session.recordings.all(), many=True).data)
