from django.urls import path

from .views import SessionAnalysisListView

urlpatterns = [
    path("sessions/<str:session_id>/analysis/", SessionAnalysisListView.as_view(), name="session-analysis"),
]
