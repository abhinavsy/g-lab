from django.urls import re_path

from .consumers import FlutterConsumer, JetsonConsumer

websocket_urlpatterns = [
    re_path(r"^ws/app/$", FlutterConsumer.as_asgi()),
    re_path(r"^ws/jetson/(?P<device_id>[\w-]+)/$", JetsonConsumer.as_asgi()),
]
