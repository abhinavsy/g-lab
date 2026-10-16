"""Read-only cross-session listing/summary endpoints.

streaming/views.py exposes CRUD-shaped, per-resource (and for alerts/
analysis, per-session-scoped) endpoints. This app adds the overview views
those don't cover: totals, and un-scoped "all sessions"/"all alerts" lists.
"""

from datetime import datetime, time, timedelta

from django.conf import settings
from django.utils import timezone
from rest_framework import generics
from rest_framework.response import Response
from rest_framework.views import APIView

import streaming.services as streaming_services
from patient.models import Patient
from streaming.models import AlertEvent, Session
from streaming.serializers import AlertEventSerializer, SessionSerializer
from telemetry.models import AnalysisEvent
from telemetry.serializers import AnalysisEventSerializer


class DashboardSummaryView(APIView):
    """GET /api/dashboard/summary/ — counts for an overview screen.

    `monitored_patients` is active patients (Patient.is_active);
    `sessions.this_week` counts sessions created since Monday 00:00 of the
    current week (settings.TIME_ZONE).
    """

    def get(self, request):
        today = timezone.localdate()
        week_start = timezone.make_aware(datetime.combine(today - timedelta(days=today.weekday()), time.min))
        return Response(
            {
                "patients": Patient.objects.count(),
                # "monitored_patients": Patient.objects.filter(is_active=True).count(),
                # "device": {
                #     "device_id": settings.JETSON_DEVICE_ID,
                #     "online": streaming_services.is_device_online(),
                # },
                "sessions": {
                    "total": Session.objects.count(),
                    "this_week": Session.objects.filter(created_at__gte=week_start).count(),
                    "active": Session.objects.filter(
                        status__in=[Session.Status.STARTING, Session.Status.ACTIVE]
                    ).count(),
                },
            }
        )


class SessionListView(generics.ListAPIView):
    """GET /api/dashboard/sessions/ — all sessions, newest first, across all
    patients (streaming.SessionViewSet's list is not scoped either, but this
    stays close to the other overview endpoints below)."""

    queryset = Session.objects.select_related("patient").all()
    serializer_class = SessionSerializer


class AlertListView(generics.ListAPIView):
    """GET /api/dashboard/alerts/ — recent alerts across ALL sessions
    (streaming only exposes alerts nested under a single session)."""

    serializer_class = AlertEventSerializer

    def get_queryset(self):
        return AlertEvent.objects.select_related("session").order_by("-created_at")[:200]


class AnalysisListView(generics.ListAPIView):
    """GET /api/dashboard/analysis/ — recent analysis samples across ALL
    sessions (streaming/telemetry only exposes this nested under a session)."""

    serializer_class = AnalysisEventSerializer

    def get_queryset(self):
        return AnalysisEvent.objects.select_related("session").order_by("-recorded_at")[:200]
