from django.db import models
from django.utils import timezone


class Patient(models.Model):
    """Patient record — structured data in PostgreSQL. See README_WebRTC.md #18.

    Moved here from streaming/ (streaming.Patient -> patient.Patient, same
    table data, see patient/migrations/0001_initial.py). Sessions still
    live in streaming (they're tied to the device/WebRTC lifecycle); a
    patient's session history is the `sessions` reverse relation from
    streaming.Session.patient, exposed at GET /api/patients/{id}/sessions/.
    """

    class Gender(models.TextChoices):
        MALE = "MALE", "Male"
        FEMALE = "FEMALE", "Female"
        OTHER = "OTHER", "Other"
        UNSPECIFIED = "UNSPECIFIED", "Unspecified"

    patient_id = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=255)
    date_of_birth = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=16, choices=Gender.choices, default=Gender.UNSPECIFIED)
    phone = models.CharField(max_length=32, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    diagnosis = models.TextField(blank=True)
    emergency_contact_name = models.CharField(max_length=255, blank=True)
    emergency_contact_phone = models.CharField(max_length=32, blank=True)
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.patient_id} ({self.name})"

    @property
    def age(self):
        if not self.date_of_birth:
            return None
        today = timezone.localdate()
        dob = self.date_of_birth
        return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


class SessionReport(models.Model):
    """The session report Flutter sends for one session ("Report of
    individual session": assessment details, spatial/temporal/kinematic
    parameters, foot pressure, COP, EMG, remarks).

    Scalar parameters are columns so they can be queried/trended across a
    patient's history; curves/maps are JSON. `raw_payload` keeps everything
    Flutter sent (merged across saves), so fields not modelled here are
    never lost. Saved via patient.services.save_session_report from
    PUT/PATCH /api/sessions/{session_id}/report/ or the `session_report`
    WebSocket message.
    """

    session = models.OneToOneField("streaming.Session", on_delete=models.CASCADE, related_name="report")
    # Denormalized from session.patient so a patient's reports query directly.
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="session_reports")

    # Assessment details
    test_type = models.CharField(max_length=64, blank=True, help_text="e.g. Walking Test")
    system_duration_seconds = models.FloatField(null=True, blank=True)

    # Spatial parameters
    step_length = models.FloatField(null=True, blank=True, help_text="m")
    stride_length = models.FloatField(null=True, blank=True, help_text="m")
    step_width = models.FloatField(null=True, blank=True, help_text="m")
    foot_rotation_angle = models.FloatField(null=True, blank=True, help_text="degrees")
    walking_velocity = models.FloatField(null=True, blank=True, help_text="m/s")

    # Temporal parameters
    cadence = models.FloatField(null=True, blank=True, help_text="steps/min")
    step_time = models.FloatField(null=True, blank=True, help_text="s")
    stride_time = models.FloatField(null=True, blank=True, help_text="s")
    stance_phase = models.FloatField(null=True, blank=True, help_text="% of gait cycle")
    swing_phase = models.FloatField(null=True, blank=True, help_text="% of gait cycle")

    # Kinematic parameters (degrees)
    hip_flexion = models.FloatField(null=True, blank=True)
    hip_extension = models.FloatField(null=True, blank=True)
    knee_flexion = models.FloatField(null=True, blank=True)
    knee_extension = models.FloatField(null=True, blank=True)
    ankle_dorsiflexion = models.FloatField(null=True, blank=True)
    ankle_plantarflexion = models.FloatField(null=True, blank=True)

    # Foot pressure analysis / COP / EMG — shape is whatever Flutter sends
    # (pressure grids, COP point lists, EMG time series).
    foot_pressure_average = models.JSONField(null=True, blank=True)
    foot_pressure_maximum = models.JSONField(null=True, blank=True)
    cop_data = models.JSONField(null=True, blank=True)
    emg_tibialis_anterior = models.JSONField(null=True, blank=True)
    emg_medial_gastrocnemius = models.JSONField(null=True, blank=True)

    remarks = models.TextField(blank=True)
    raw_payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Report {self.session.session_id}"
