"""DRF authentication for the Jetson device itself calling the REST API
(currently just the recording upload endpoint — README_WebRTC.md #17).

No Device model (single-Jetson deployment — see streaming/services.py):
the Jetson presents the single shared secret in settings.JETSON_AUTH_TOKEN,
same convention as the signaling WebSocket (streaming/auth.py). Header:
`Authorization: Device <token>`.

Also defines DisabledAuthAuthentication — the settings.AUTH_DISABLED
catch-all used for every REST endpoint, not just device ones (see
config/settings.py REST_FRAMEWORK).
"""

from rest_framework import authentication, exceptions

from django.conf import settings

from . import services


class AuthenticatedDevice:
    """Stand-in for `request.auth` when the caller is the Jetson — there's
    no Device model/row to return, just the configured device_id (see
    streaming/permissions.py IsAuthenticatedOrSessionDevice)."""

    def __init__(self, device_id: str):
        self.device_id = device_id


class DeviceTokenAuthentication(authentication.BaseAuthentication):
    keyword = "Device"

    def authenticate(self, request):
        header = authentication.get_authorization_header(request).decode("utf-8")
        if not header or not header.startswith(f"{self.keyword} "):
            return None

        token = header[len(self.keyword) + 1 :].strip()
        # settings.AUTH_DISABLED: any non-empty token is accepted — the
        # header still has to be present so this authenticator only claims
        # requests that are actually trying to authenticate as the device.
        if not settings.AUTH_DISABLED and token != settings.JETSON_AUTH_TOKEN:
            raise exceptions.AuthenticationFailed("Invalid device token.")

        # No Django user for a device — downstream permission checks look at
        # request.auth.device_id.
        return (None, AuthenticatedDevice(settings.JETSON_DEVICE_ID))


class DisabledAuthAuthentication(authentication.BaseAuthentication):
    """settings.AUTH_DISABLED catch-all: authenticates every request that
    reached here (i.e. no valid JWT or device token was given) as a fixed
    dev user, so IsAuthenticated / request.user checks keep passing with no
    token at all. No-op — always returns None — when AUTH_DISABLED is
    False. See config/settings.py AUTH_DISABLED."""

    def authenticate(self, request):
        if not settings.AUTH_DISABLED:
            return None
        return (services.get_or_create_dev_user(), None)
