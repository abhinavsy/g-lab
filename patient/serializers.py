from rest_framework import serializers

from streaming.serializers import AlertEventSerializer, RecordingSerializer, SessionSerializer
from telemetry.models import AnalysisEvent

from .models import Patient, SessionReport


class PatientSerializer(serializers.ModelSerializer):
    age = serializers.IntegerField(read_only=True)
    # Annotated in PatientViewSet.get_queryset.
    session_count = serializers.IntegerField(read_only=True)
    last_session_at = serializers.DateTimeField(read_only=True)

    class Meta:
        model = Patient
        fields = [
            "id",
            "patient_id",
            "name",
            "date_of_birth",
            "age",
            "gender",
            "phone",
            "email",
            "address",
            "diagnosis",
            "emergency_contact_name",
            "emergency_contact_phone",
            "notes",
            "is_active",
            "session_count",
            "last_session_at",
            "created_at",
            "updated_at",
        ]


class SessionReportSerializer(serializers.ModelSerializer):
    session_id = serializers.CharField(source="session.session_id", read_only=True)
    patient_id = serializers.CharField(source="patient.patient_id", read_only=True)

    class Meta:
        model = SessionReport
        exclude = ["id", "session", "patient", "raw_payload"]
        read_only_fields = ["created_at", "updated_at"]


class JetsonSampleSerializer(serializers.ModelSerializer):
    """One analysis sample as the Jetson produced it (relayed by Flutter).

    `values` is the received payload minus the envelope keys, so it shows
    exactly what arrived (hip_angle, knee_angle, speed, spasm_detected, ...)
    whatever field names the Jetson uses.
    """

    values = serializers.SerializerMethodField()

    class Meta:
        model = AnalysisEvent
        fields = ["id", "recorded_at", "values"]
        read_only_fields = fields

    def get_values(self, obj):
        return {k: v for k, v in obj.raw_payload.items() if k not in ("type", "session_id")}


class SessionHistorySerializer(SessionSerializer):
    """One row of a patient's session history (GET /api/patients/{id}/sessions/)."""

    # Annotated in patient.views.annotate_session_summary.
    alert_count = serializers.IntegerField(read_only=True)
    recording_count = serializers.IntegerField(read_only=True)
    sample_count = serializers.IntegerField(read_only=True)
    spasm_count = serializers.IntegerField(read_only=True)
    avg_speed = serializers.FloatField(read_only=True)
    max_speed = serializers.FloatField(read_only=True)
    duration_seconds = serializers.SerializerMethodField()
    has_report = serializers.SerializerMethodField()

    class Meta(SessionSerializer.Meta):
        fields = SessionSerializer.Meta.fields + [
            "duration_seconds",
            "has_report",
            "sample_count",
            "spasm_count",
            "avg_speed",
            "max_speed",
            "alert_count",
            "recording_count",
        ]
        read_only_fields = fields

    def get_duration_seconds(self, obj):
        if obj.started_at and obj.ended_at:
            return (obj.ended_at - obj.started_at).total_seconds()
        return None

    def get_has_report(self, obj):
        return hasattr(obj, "report")


class SessionHistoryDetailSerializer(SessionHistorySerializer):
    """GET /api/patients/{id}/sessions/{session_id}/ — summary plus every
    Jetson sample, alert and recording for the session."""

    report = SessionReportSerializer(read_only=True)
    samples = JetsonSampleSerializer(source="analysis_events", many=True, read_only=True)
    alerts = AlertEventSerializer(many=True, read_only=True)
    recordings = RecordingSerializer(many=True, read_only=True)

    class Meta(SessionHistorySerializer.Meta):
        fields = SessionHistorySerializer.Meta.fields + ["report", "samples", "alerts", "recordings"]
        read_only_fields = fields
