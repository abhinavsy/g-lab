"""WebSocket authentication for the two kinds of signaling client:

- Flutter connects to ws/app/ with a JWT access token obtained from
  /api/auth/login/ (?token=<jwt>). scope["user"] is set to the Django user.
- Jetson connects to ws/jetson/<device_id>/ with the single shared secret
  in settings.JETSON_AUTH_TOKEN (?token=<that value> — no Device model,
  this is a one-Jetson deployment; see streaming/services.py). scope["device_id"]
  is set to settings.JETSON_DEVICE_ID on a match.

Both use the same query-string convention because browsers/WebRTC clients
cannot set custom headers on a WebSocket handshake.

**settings.AUTH_DISABLED**: when True (see config/settings.py), every
connection to either socket is accepted with no token check at all —
scope["user"] is a fixed dev user and scope["device_id"] is always
settings.JETSON_DEVICE_ID, regardless of what (if anything) ?token= holds.
"""

from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware
from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import AccessToken

from . import services


@database_sync_to_async
def get_user_from_jwt(token: str):
    from django.contrib.auth import get_user_model

    try:
        validated = AccessToken(token)
        return get_user_model().objects.get(id=validated["user_id"])
    except (TokenError, Exception):  # noqa: BLE001 - any failure -> anonymous
        return AnonymousUser()


get_dev_user = database_sync_to_async(services.get_or_create_dev_user)


class TokenAuthMiddleware(BaseMiddleware):
    """Populates scope["user"] and scope["device_id"] from ?token=... .

    Whichever consumer handles the connection decides which one it needs
    (JetsonConsumer requires scope["device_id"], everything else requires
    scope["user"]).
    """

    async def __call__(self, scope, receive, send):
        scope["user"] = AnonymousUser()
        scope["device_id"] = None

        if settings.AUTH_DISABLED:
            scope["device_id"] = settings.JETSON_DEVICE_ID
            scope["user"] = await get_dev_user()
        else:
            query_string = scope.get("query_string", b"").decode()
            token = parse_qs(query_string).get("token", [None])[0]
            if token:
                if token == settings.JETSON_AUTH_TOKEN:
                    scope["device_id"] = settings.JETSON_DEVICE_ID
                else:
                    scope["user"] = await get_user_from_jwt(token)

        return await super().__call__(scope, receive, send)
