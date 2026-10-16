from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import PatientViewSet, SessionReportView

router = DefaultRouter()
router.register("patients", PatientViewSet, basename="patient")

urlpatterns = router.urls + [
    path("sessions/<str:session_id>/report/", SessionReportView.as_view(), name="session-report"),
]
