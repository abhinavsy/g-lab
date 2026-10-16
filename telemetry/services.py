"""Persistence for data relayed Flutter -> Django. Called from
streaming/consumers.py FlutterConsumer._handle_analysis_data (README_WebRTC.md
#14), kept separate from streaming/services.py which handles the
Django<->Jetson/Flutter control-plane logic.
"""

from streaming.models import Session

from .models import AnalysisEvent


def record_analysis(*, session: Session, payload: dict) -> AnalysisEvent:
    return AnalysisEvent.objects.create(
        session=session,
        patient_id=session.patient_id,
        hip_angle_left=payload.get("hip_angle_left"),
        hip_angle_right=payload.get("hip_angle_right"),
        knee_angle_left=payload.get("knee_angle_left"),
        knee_angle_right=payload.get("knee_angle_right"),
        speed=payload.get("speed"),
        spasm_detected=bool(payload.get("spasm_detected", False)),
        raw_payload=payload,
    )
