"""Seeds dummy patients with a session history (sessions, Jetson samples,
alerts and session reports) for testing the patient APIs and the Flutter
history screens:

    GET /api/patients/
    GET /api/patients/{patient_id}/sessions/
    GET /api/patients/{patient_id}/sessions/{session_id}/

Dummy patients use the DEMO prefix (DEMO001, DEMO002, ...). Re-running
deletes and recreates them, so the data stays a fixed set.

Usage:
    python manage.py seed_dummy_data                # inside the venv/container
    docker exec g-lab-backend-1 python manage.py seed_dummy_data
    docker exec g-lab-backend-1 python manage.py seed_dummy_data --clear   # only remove it
"""
import random
from datetime import date, timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from patient.models import Doctor, Patient, SessionReport
from streaming.models import AlertEvent, Session
from telemetry.models import AnalysisEvent

PREFIX = "DEMO"
DOCTOR_PREFIX = "DOC"

DOCTORS = [
    {
        "name": "Anjali Krishnan",
        "specialty": "Physical Medicine and Rehabilitation",
        "phone": "+91 98470 10101",
        "email": "anjali.krishnan@example.com",
    },
    {
        "name": "Rohan Mathew",
        "specialty": "Orthopedics",
        "phone": "+91 98470 10102",
        "email": "rohan.mathew@example.com",
    },
    {
        "name": "Sana Fathima",
        "specialty": "Neurology",
        "phone": "+91 98470 10103",
        "email": "sana.fathima@example.com",
    },
]

PATIENTS = [
    {
        "name": "Arjun Menon",
        "height_cm": 172.00,
        "weight_kg": 74.50,
        "date_of_birth": date(1958, 3, 14),
        "gender": Patient.Gender.MALE,
        "phone": "+91 98470 11201",
        "email": "arjun.menon@example.com",
        "address": "12 MG Road, Kochi, Kerala",
        "diagnosis": "Post-stroke hemiparesis (left side)",
        "emergency_contact_name": "Meera Menon",
        "emergency_contact_phone": "+91 98470 11202",
        "notes": "Uses a walking stick outdoors.",
    },
    {
        "name": "Priya Nair",
        "height_cm": 160.00,
        "weight_kg": 61.20,
        "date_of_birth": date(1972, 7, 2),
        "gender": Patient.Gender.FEMALE,
        "phone": "+91 94460 22301",
        "email": "priya.nair@example.com",
        "address": "45 Statue Junction, Thiruvananthapuram, Kerala",
        "diagnosis": "Parkinson's disease, stage 2",
        "emergency_contact_name": "Rahul Nair",
        "emergency_contact_phone": "+91 94460 22302",
    },
    {
        "name": "Thomas George",
        "height_cm": 180.00,
        "weight_kg": 82.00,
        "date_of_birth": date(1990, 11, 23),
        "gender": Patient.Gender.MALE,
        "phone": "+91 90480 33401",
        "address": "8 Market Road, Kottayam, Kerala",
        "diagnosis": "ACL reconstruction rehab (right knee)",
        "emergency_contact_name": "Anna George",
        "emergency_contact_phone": "+91 90480 33402",
    },
    {
        "name": "Fathima Rasheed",
        "height_cm": 148.00,
        "weight_kg": 42.00,
        "date_of_birth": date(2012, 5, 9),
        "gender": Patient.Gender.FEMALE,
        "phone": "+91 97450 44501",
        "address": "21 Beach Road, Kozhikode, Kerala",
        "diagnosis": "Spastic diplegic cerebral palsy",
        "emergency_contact_name": "Rasheed K",
        "emergency_contact_phone": "+91 97450 44502",
        "notes": "Frequent calf spasms; monitor closely.",
    },
    {
        "name": "Lakshmi Varma",
        "height_cm": 155.00,
        "weight_kg": 68.30,
        "date_of_birth": date(1965, 1, 30),
        "gender": Patient.Gender.FEMALE,
        "phone": "+91 99610 55601",
        "address": "3 Temple Street, Thrissur, Kerala",
        "diagnosis": "Total hip replacement (left), 6 weeks post-op",
        "emergency_contact_name": "Ravi Varma",
        "emergency_contact_phone": "+91 99610 55602",
        "is_active": False,
    },
]

TEST_TYPES = ["Walking Test", "Timed Up and Go", "10m Walk Test", "Balance Test"]
REMARKS = [
    "Gait symmetry improving compared to last session.",
    "Reduced stance phase on affected side; continue strengthening.",
    "Patient fatigued towards the end of the test.",
    "Good progress, cadence up from previous session.",
    "",
]


class Command(BaseCommand):
    help = "Creates dummy patients (DEMO###) with session history, Jetson samples, alerts and reports."

    def add_arguments(self, parser):
        parser.add_argument("--clear", action="store_true", help="Only delete the dummy data, don't recreate it.")
        parser.add_argument("--seed", type=int, default=42, help="Random seed (default 42) so runs are repeatable.")

    @transaction.atomic
    def handle(self, *args, **options):
        deleted = self._clear()
        if deleted:
            self.stdout.write(f"removed {deleted} existing dummy patient(s)")
        if options["clear"]:
            return

        rng = random.Random(options["seed"])
        doctors = []
        for index, data in enumerate(DOCTORS, start=1):
            doctor = Doctor.objects.create(doctor_id=f"{DOCTOR_PREFIX}{index:03d}", **data)
            doctors.append(doctor)
            self.stdout.write(f"{doctor.doctor_id} {doctor.name}")

        user = get_user_model().objects.filter(is_superuser=True).order_by("id").first()
        now = timezone.now()

        session_total = 0
        for i, data in enumerate(PATIENTS, start=1):
            patient = Patient.objects.create(
                patient_id=f"{PREFIX}{i:03d}",
                doctor=doctors[(i - 1) % len(doctors)],
                **data,
            )
            n_sessions = rng.randint(3, 6)
            # Oldest first (so Session 1 is the earliest), 5-10 days apart.
            gaps = [rng.randint(5, 10) for _ in range(n_sessions)]
            for s in range(n_sessions):
                start = now - timedelta(days=sum(gaps[s:]), hours=rng.randint(0, 8))
                self._create_session(rng, patient, user, start, progress=s / max(n_sessions - 1, 1))
            session_total += n_sessions
            self.stdout.write(f"{patient.patient_id} {patient.name}: {n_sessions} session(s)")

        self.stdout.write(self.style.SUCCESS(f"created {len(PATIENTS)} patients, {session_total} sessions"))

    def _clear(self):
        Doctor.objects.filter(doctor_id__startswith=DOCTOR_PREFIX).delete()
        patients = Patient.objects.filter(patient_id__startswith=PREFIX)
        count = patients.count()
        # Session.patient is PROTECT, so sessions (and their alerts/samples/
        # reports via CASCADE) go first.
        Session.objects.filter(patient__in=patients).delete()
        patients.delete()
        return count

    def _create_session(self, rng, patient, user, start, progress):
        failed = rng.random() < 0.1
        duration = timedelta(seconds=rng.randint(60, 600))
        end = start + (duration / 3 if failed else duration)

        session = Session.objects.create(
            patient=patient,
            device_id=settings.JETSON_DEVICE_ID,
            started_by=user,
            status=Session.Status.FAILED if failed else Session.Status.COMPLETED,
            started_at=start,
            ended_at=end,
        )
        # created_at is auto_now_add; backdate it so history ordering matches.
        Session.objects.filter(pk=session.pk).update(created_at=start - timedelta(seconds=5))

        # Jetson samples, one every ~5s. recorded_at is auto_now_add too.
        n_samples = max(int((end - start).total_seconds() // 5), 3)
        base_speed = 0.6 + 0.5 * progress
        events = []
        for _ in range(n_samples):
            payload = {
                "hip_angle_left": round(rng.uniform(15, 35), 1),
                "hip_angle_right": round(rng.uniform(15, 35), 1),
                "knee_angle_left": round(rng.uniform(40, 65), 1),
                "knee_angle_right": round(rng.uniform(40, 65), 1),
                "speed": round(base_speed + rng.uniform(-0.15, 0.15), 2),
                "spasm_detected": rng.random() < 0.04,
            }
            events.append(AnalysisEvent(session=session, patient=patient, raw_payload=payload, **payload))
        created = AnalysisEvent.objects.bulk_create(events)
        for idx, event in enumerate(created):
            AnalysisEvent.objects.filter(pk=event.pk).update(recorded_at=start + timedelta(seconds=5 * idx))

        for idx, event in enumerate(created):
            if event.spasm_detected:
                alert = AlertEvent.objects.create(
                    session=session,
                    alert_type=AlertEvent.AlertType.SPASM_DETECTED,
                    message="SPASM DETECTED",
                    payload={"knee_angle_left": event.knee_angle_left, "knee_angle_right": event.knee_angle_right},
                )
                AlertEvent.objects.filter(pk=alert.pk).update(created_at=start + timedelta(seconds=5 * idx))

        if not failed:
            self._create_report(rng, session, patient, (end - start).total_seconds(), base_speed)
        return session

    def _create_report(self, rng, session, patient, duration, speed):
        cadence = round(rng.uniform(80, 115), 1)
        step_length = round(speed * 60 / cadence, 2)  # metres per step
        stance = round(rng.uniform(58, 66), 1)
        report = {
            "test_type": rng.choice(TEST_TYPES),
            "system_duration_seconds": round(duration, 1),
            "step_length": step_length,
            "stride_length": round(step_length * 2, 2),
            "step_width": round(rng.uniform(0.08, 0.15), 2),
            "foot_rotation_angle": round(rng.uniform(5, 12), 1),
            "walking_velocity": round(speed, 2),
            "cadence": cadence,
            "step_time": round(60 / cadence, 2),
            "stride_time": round(120 / cadence, 2),
            "stance_phase": stance,
            "swing_phase": round(100 - stance, 1),
            "hip_flexion": round(rng.uniform(25, 35), 1),
            "hip_extension": round(rng.uniform(5, 15), 1),
            "knee_flexion": round(rng.uniform(50, 65), 1),
            "knee_extension": round(rng.uniform(0, 5), 1),
            "ankle_dorsiflexion": round(rng.uniform(8, 15), 1),
            "ankle_plantarflexion": round(rng.uniform(15, 25), 1),
            "foot_pressure_average": {"left": round(rng.uniform(40, 60), 1), "right": round(rng.uniform(40, 60), 1)},
            "foot_pressure_maximum": {"left": round(rng.uniform(90, 140), 1), "right": round(rng.uniform(90, 140), 1)},
            "cop_data": [{"x": round(rng.uniform(-2, 2), 2), "y": round(y * 1.5, 2)} for y in range(10)],
            "emg_tibialis_anterior": [round(rng.uniform(0, 1), 3) for _ in range(20)],
            "emg_medial_gastrocnemius": [round(rng.uniform(0, 1), 3) for _ in range(20)],
            "remarks": rng.choice(REMARKS),
        }
        SessionReport.objects.create(session=session, patient=patient, raw_payload=dict(report), **report)
