"""Persistence for the session report Flutter sends (patient.SessionReport).

Shared by the REST endpoint (patient/views.py SessionReportView) and the
`session_report` WebSocket message (streaming/consumers.py FlutterConsumer),
so both validate and save the same way.
"""

from django.db import transaction

from streaming.models import Session

from .models import SessionReport
from .serializers import SessionReportSerializer

ENVELOPE_KEYS = ("type", "session_id")


@transaction.atomic
def save_session_report(*, session: Session, data: dict) -> tuple[SessionReport, bool]:
    """Create or update the session's report from Flutter's payload.

    Known fields go to their columns; the full payload (minus the WS
    envelope) is merged into raw_payload so nothing Flutter sends is lost.
    Raises rest_framework.exceptions.ValidationError on bad values.
    """
    payload = {k: v for k, v in data.items() if k not in ENVELOPE_KEYS}
    report = SessionReport.objects.select_for_update().filter(session=session).first()
    created = report is None
    serializer = SessionReportSerializer(report, data=payload, partial=True)
    serializer.is_valid(raise_exception=True)
    raw = {**(report.raw_payload if report else {}), **payload}
    report = serializer.save(session=session, patient_id=session.patient_id, raw_payload=raw)
    return report, created
