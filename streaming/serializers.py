from rest_framework import serializers

from .models import AlertEvent, Recording, Session


class SessionSerializer(serializers.ModelSerializer):
    patient_id = serializers.SlugRelatedField(source="patient", slug_field="patient_id", read_only=True)

    class Meta:
        model = Session
        fields = [
            "id",
            "session_id",
            "session_number",
            "patient_id",
            "device_id",
            "status",
            "created_at",
            "started_at",
            "ended_at",
        ]
        read_only_fields = fields


class StartSessionSerializer(serializers.Serializer):
    """Mirrors the WebSocket `start_session` payload (README_WebRTC.md #6).

    `device_id` is optional and normally omitted entirely — there's no
    Device model (single-Jetson deployment; see services.start_session),
    Django always targets settings.JETSON_DEVICE_ID. If passed, it must
    match that value. The Jetson itself decides internally which/how many
    of its own cameras to stream/record; Django/Flutter never pick a
    `camera_id`.
    """

    patient_id = serializers.CharField(max_length=32)
    device_id = serializers.CharField(max_length=32, required=False, allow_null=True, default=None)


class DeviceCommandSerializer(serializers.Serializer):
    command = serializers.ChoiceField(
        choices=["START", "STOP", "PAUSE", "RESUME", "SET_SPEED", "SET_RESISTANCE", "CHANGE_MODE"]
    )
    params = serializers.DictField(required=False, default=dict)


class AlertEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = AlertEvent
        fields = ["id", "alert_type", "message", "payload", "created_at"]


class RecordingSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()

    class Meta:
        model = Recording
        fields = ["id", "clip_index", "duration_seconds", "created_at", "url"]

    def get_url(self, obj):
        return obj.file.url if obj.file else None


class RecordingUploadSerializer(serializers.Serializer):
    """Body for POST /api/sessions/{session_id}/recordings/.

    The Jetson uploads the finished recording/clip once it finalizes
    locally (README #17, #19); Django streams the multipart file through to
    MinIO via Recording.file (S3Storage backend, config/settings.py
    STORAGES) and records the metadata row in PostgreSQL.
    """

    file = serializers.FileField()
    clip_index = serializers.IntegerField(required=False, default=0)
    duration_seconds = serializers.FloatField(required=False, allow_null=True, default=None)
