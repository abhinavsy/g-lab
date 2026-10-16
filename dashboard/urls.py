from django.urls import path

from .views import AlertListView, AnalysisListView, DashboardSummaryView, SessionListView

urlpatterns = [
    path("summary/", DashboardSummaryView.as_view(), name="dashboard-summary"),
    path("sessions/", SessionListView.as_view(), name="dashboard-sessions"),
    path("alerts/", AlertListView.as_view(), name="dashboard-alerts"),
    path("analysis/", AnalysisListView.as_view(), name="dashboard-analysis"),
]
