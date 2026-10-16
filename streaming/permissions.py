from rest_framework.permissions import BasePermission

from .authentication import AuthenticatedDevice


class IsAuthenticatedOrSessionDevice(BasePermission):
    """GET requires a logged-in user (Flutter/dashboard reading recordings).

    POST requires the Jetson's device token (see
    streaming/authentication.py DeviceTokenAuthentication) — checked against
    the session's own `device_id` (single-Jetson deployment, but this still
    guards against a stale/mismatched session row, README #17).
    """

    def has_permission(self, request, view):
        if request.method == "POST":
            return isinstance(request.auth, AuthenticatedDevice)
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, session):
        if request.method == "POST":
            return isinstance(request.auth, AuthenticatedDevice) and session.device_id == request.auth.device_id
        return True
