from django.db import models

from streaming.models import Session


class AnalysisEvent(models.Model):
    """Live AI/analysis samples relayed Flutter -> Django over WebSocket.

    This is the one piece of session data that actually travels
    Flutter -> Django (the analysis itself arrives Jetson -> Flutter over
    the WebRTC data channel; Flutter relays it here to persist — see
    README_WebRTC.md #14 and streaming/consumers.py FlutterConsumer). It
    lives in its own app, separate from streaming/, to keep that transfer
    path distinct from the Django<->Jetson/Flutter control-plane models.
    """

    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name="analysis_events")
    # Denormalized from session.patient (set in services.record_analysis) so
    # a patient's Jetson data can be queried directly — see patient/views.py.
    patient = models.ForeignKey("patient.Patient", on_delete=models.CASCADE, related_name="analysis_events")
    hip_angle_left = models.FloatField(null=True, blank=True)
    hip_angle_right = models.FloatField(null=True, blank=True)
    knee_angle_left = models.FloatField(null=True, blank=True)
    knee_angle_right = models.FloatField(null=True, blank=True)
    speed = models.FloatField(null=True, blank=True)
    spasm_detected = models.BooleanField(default=False)
    raw_payload = models.JSONField(default=dict, blank=True)
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["recorded_at"]

    def __str__(self):
        return f"{self.session_id} @ {self.recorded_at:%H:%M:%S}"
