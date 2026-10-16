import os

from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

# get_asgi_application() must run before importing anything that touches
# models, so streaming.routing is imported after this call.
django_asgi_app = get_asgi_application()

import streaming.routing  # noqa: E402
from streaming.auth import TokenAuthMiddleware  # noqa: E402

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": AllowedHostsOriginValidator(
            TokenAuthMiddleware(URLRouter(streaming.routing.websocket_urlpatterns))
        ),
    }
)
