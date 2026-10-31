from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import DoctorListView, PatientViewSet, SessionReportView

router = DefaultRouter()
router.register("patients", PatientViewSet, basename="patient")

urlpatterns = router.urls + [
    path("doctors/", DoctorListView.as_view(), name="doctor-list"),
    path(
        "sessions/<str:session_id>/report/",
        SessionReportView.as_view(),
        name="session-report",
    ),
]
