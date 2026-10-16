from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import DeviceStatusView, SessionViewSet

router = DefaultRouter()
router.register("sessions", SessionViewSet, basename="session")

urlpatterns = router.urls + [
    path("device/status/", DeviceStatusView.as_view(), name="device-status"),
]
