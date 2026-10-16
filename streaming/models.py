import uuid

from django.conf import settings
from django.db import models


def generate_session_id():
    return f"SES{uuid.uuid4().hex[:8].upper()}"


class Session(models.Model):
    """A single stream/session run on the (one, only) Jetson device for a
    patient.

    Flow: STARTING -> ACTIVE -> STOPPING -> COMPLETED (or FAILED).
    See README_WebRTC.md #6, #7, #19. A session covers *all* of the device's
    cameras at once — the Jetson streams/records every camera it has for the
    session's duration.

    There is no `Device`/`Camera` model: this project targets exactly one
    Jetson, whose id/secret live in settings (JETSON_DEVICE_ID,
    JETSON_AUTH_TOKEN — see streaming/services.py, streaming/auth.py,
    streaming/authentication.py) rather than a database row. `device_id`
    here is just a denormalized label recorded at start time (always
    settings.JETSON_DEVICE_ID today); it exists so historical sessions keep
    a record of which device ran them if that ever changes.

    `patient` points at patient.Patient (moved out of this app); a
    patient's session history is served by patient.views.PatientViewSet.

    The `analysis_events` reverse relation is defined on telemetry.AnalysisEvent
    (Flutter -> Django data lives in its own app; see telemetry/models.py).
    """

    class Status(models.TextChoices):
        STARTING = "STARTING", "Starting"
        ACTIVE = "ACTIVE", "Active"
        STOPPING = "STOPPING", "Stopping"
        COMPLETED = "COMPLETED", "Completed"
        FAILED = "FAILED", "Failed"

    session_id = models.CharField(max_length=32, unique=True, default=generate_session_id, editable=False)
    patient = models.ForeignKey("patient.Patient", on_delete=models.PROTECT, related_name="sessions")
    # Per-patient counter (Session 1, 2, 3, ...) so a session is easy to
    # identify within a patient's history. Assigned in save().
    session_number = models.PositiveIntegerField(editable=False)
    device_id = models.CharField(max_length=32)
    started_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="started_sessions"
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.STARTING)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["patient", "session_number"], name="unique_session_number_per_patient"),
        ]

    def __str__(self):
        return self.session_id

    def save(self, *args, **kwargs):
        if self.session_number is None:
            last = Session.objects.filter(patient_id=self.patient_id).aggregate(n=models.Max("session_number"))["n"]
            self.session_number = (last or 0) + 1
        super().save(*args, **kwargs)


class AlertEvent(models.Model):
    """Device-detected alerts (e.g. SPASM DETECTED). See #16."""

    class AlertType(models.TextChoices):
        SPASM_DETECTED = "SPASM_DETECTED", "Spasm detected"
        DEVICE_OFFLINE = "DEVICE_OFFLINE", "Device offline"
        OTHER = "OTHER", "Other"

    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name="alerts")
    alert_type = models.CharField(max_length=32, choices=AlertType.choices, default=AlertType.OTHER)
    message = models.CharField(max_length=255, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


def recording_upload_path(instance, filename):
    return f"sessions/{instance.session.session_id}/{filename}"


class Recording(models.Model):
    """Recording/clip metadata; the file itself lives in MinIO, uploaded by
    the Jetson through Django's REST API (POST /api/sessions/{id}/recordings/,
    streaming.services.save_recording) rather than written by the device
    directly. See #17."""

    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name="recordings")
    file = models.FileField(upload_to=recording_upload_path)
    clip_index = models.PositiveIntegerField(default=0)
    duration_seconds = models.FloatField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["clip_index"]
