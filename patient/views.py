from django.db.models import (
    Avg,
    Count,
    IntegerField,
    Max,
    OuterRef,
    ProtectedError,
    Q,
    Subquery,
)
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404
from rest_framework import generics, status, viewsets
from rest_framework.views import APIView
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from streaming.models import Session
from telemetry.models import AnalysisEvent

from . import services
from .models import Doctor, Patient, SessionReport
from .serializers import (
    DoctorSerializer,
    PatientSerializer,
    SessionHistoryDetailSerializer,
    SessionHistorySerializer,
    SessionReportSerializer,
)


def _sample_stat(aggregate, output_field=None):
    """Per-session aggregate over its Jetson samples, as a subquery — keeps
    the sample stats independent of the alert/recording count joins."""
    qs = (
        AnalysisEvent.objects.filter(session=OuterRef("pk"))
        .order_by()
        .values("session")
        .annotate(v=aggregate)
        .values("v")
    )
    return Subquery(qs, output_field=output_field)


def annotate_session_summary(sessions):
    return sessions.annotate(
        alert_count=Count("alerts", distinct=True),
        recording_count=Count("recordings", distinct=True),
        sample_count=Coalesce(_sample_stat(Count("id"), IntegerField()), 0),
        spasm_count=Coalesce(
            _sample_stat(Count("id", filter=Q(spasm_detected=True)), IntegerField()), 0
        ),
        avg_speed=_sample_stat(Avg("speed")),
        max_speed=_sample_stat(Max("speed")),
    )


class PatientViewSet(viewsets.ModelViewSet):
    serializer_class = PatientSerializer
    lookup_field = "patient_id"

    def get_queryset(self):
        return Patient.objects.select_related("doctor").annotate(
            session_count=Count("sessions"),
            last_session_at=Max("sessions__created_at"),
        ).order_by("-created_at")

    def destroy(self, request, *args, **kwargs):
        # Session.patient is PROTECT: keep history, deactivate instead.
        try:
            return super().destroy(request, *args, **kwargs)
        except ProtectedError:
            return Response(
                {
                    "detail": "Patient has sessions and can't be deleted; set is_active=false instead."
                },
                status=status.HTTP_409_CONFLICT,
            )

    @action(detail=True, methods=["get"])
    def sessions(self, request, patient_id=None):
        """GET /api/patients/{patient_id}/sessions/[?status=COMPLETED]

        The patient's session history, newest first, with per-session
        duration, a summary of the Jetson samples (count, spasms, speed)
        and alert/recording counts.
        """
        patient = self.get_object()
        sessions = annotate_session_summary(
            Session.objects.filter(patient=patient).select_related("patient")
        )
        status_filter = request.query_params.get("status")
        if status_filter:
            if status_filter not in Session.Status.values:
                raise ValidationError(
                    {"status": f"Must be one of {Session.Status.values}."}
                )
            sessions = sessions.filter(status=status_filter)
        # Explicit: Meta.ordering is ignored on aggregate (GROUP BY) queries.
        sessions = sessions.order_by("-created_at")
        return Response(SessionHistorySerializer(sessions, many=True).data)

    @action(detail=True, methods=["get"], url_path=r"sessions/(?P<session_id>[^/.]+)")
    def session_detail(self, request, patient_id=None, session_id=None):
        """GET /api/patients/{patient_id}/sessions/{session_id or session_number}/

        One session from the patient's history with every value received
        from the Jetson (in arrival order), plus its alerts and recordings.
        Accepts the session_id (SES...) or the patient's session number
        (1, 2, 3, ...).
        """
        patient = self.get_object()
        sessions = annotate_session_summary(
            Session.objects.filter(patient=patient)
            .select_related("patient")
            .select_related("report")
            .prefetch_related("analysis_events", "alerts", "recordings")
        )
        lookup = (
            {"session_number": int(session_id)}
            if session_id.isdigit()
            else {"session_id": session_id}
        )
        session = get_object_or_404(sessions, **lookup)
        return Response(SessionHistoryDetailSerializer(session).data)


class DoctorListView(generics.ListAPIView):
    queryset = Doctor.objects.all()
    serializer_class = DoctorSerializer


class SessionReportView(APIView):
    """/api/sessions/{session_id}/report/ — the report Flutter saves for a
    session (patient.SessionReport).

    GET: the saved report (404 if none yet).
    POST/PUT/PATCH: create or update it. Only the fields sent are changed
    (so PATCH {"remarks": "..."} is the "Add Remark" action); everything
    sent is also merged into the report's raw_payload. 201 on create, 200
    on update.
    """

    def get(self, request, session_id):
        report = get_object_or_404(
            SessionReport.objects.select_related("session", "patient"),
            session__session_id=session_id,
        )
        return Response(SessionReportSerializer(report).data)

    def put(self, request, session_id):
        session = get_object_or_404(Session, session_id=session_id)
        report, created = services.save_session_report(
            session=session, data=request.data
        )
        return Response(
            SessionReportSerializer(report).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    post = patch = put
