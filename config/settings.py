"""
Django settings for the Jetson -> Django -> Flutter WebRTC signaling backend.

See README_WebRTC.md at the repo root for the architecture this project
implements: Django is the REST/WebSocket control plane and WebRTC signaling
relay. Live video + live analysis flow directly Jetson -> Flutter over
WebRTC once negotiation is complete (Django never touches that path), but
finished recordings/clips are uploaded by Jetson through Django's REST API
(streaming.views.SessionViewSet.recordings, POST) which writes them through
to MinIO — Jetson never talks to MinIO directly. See README #17.
"""

from datetime import timedelta
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DJANGO_DEBUG=(bool, False),
    MINIO_USE_SSL=(bool, False),
    AUTH_DISABLED=(bool, True),
)
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("DJANGO_SECRET_KEY", default="insecure-dev-key-change-me")
DEBUG = env("DJANGO_DEBUG")
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["*"])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    "rest_framework",
    "rest_framework_simplejwt",
    "corsheaders",
    "channels",
    "patient",
    "streaming",
    "telemetry",
    "dashboard",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# ---------------------------------------------------------------------------
# Database (PostgreSQL) — structured application/session/analysis data.
# ---------------------------------------------------------------------------
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("POSTGRES_DB", default="jetson_stream"),
        "USER": env("POSTGRES_USER", default="jetson_stream"),
        "PASSWORD": env("POSTGRES_PASSWORD", default="jetson_stream"),
        "HOST": env("POSTGRES_HOST", default="localhost"),
        "PORT": env("POSTGRES_PORT", default="5432"),
    }
}

# ---------------------------------------------------------------------------
# Channels — WebSocket signaling / commands (Django Channels + Redis).
# ---------------------------------------------------------------------------
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [(env("REDIS_HOST", default="localhost"), env.int("REDIS_PORT", default=6379))],
        },
    },
}

# Cache — used only to track the Jetson's online/offline status
# (streaming/services.py mark_device_online/offline, is_device_online).
# Redis-backed (not locmem) so status is consistent across every
# Daphne/gunicorn worker process, not just whichever one holds the socket.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": f"redis://{env('REDIS_HOST', default='localhost')}:{env.int('REDIS_PORT', default=6379)}/1",
    }
}

# ---------------------------------------------------------------------------
# MinIO (S3-compatible) — recordings, clips, media storage.
# ---------------------------------------------------------------------------
STORAGES = {
    "default": {
        "BACKEND": "storages.backends.s3.S3Storage",
    },
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}

AWS_ACCESS_KEY_ID = env("MINIO_ACCESS_KEY", default="minioadmin")
AWS_SECRET_ACCESS_KEY = env("MINIO_SECRET_KEY", default="minioadmin")
AWS_STORAGE_BUCKET_NAME = env("MINIO_BUCKET_NAME", default="recordings")
AWS_S3_ENDPOINT_URL = env("MINIO_ENDPOINT_URL", default="http://localhost:9000")
AWS_S3_USE_SSL = env("MINIO_USE_SSL")
AWS_S3_ADDRESSING_STYLE = "path"
AWS_DEFAULT_ACL = None
AWS_QUERYSTRING_AUTH = True
AWS_QUERYSTRING_EXPIRE = 3600  # signed URL TTL for recordings/clips

# ---------------------------------------------------------------------------
# !! AUTH CURRENTLY DISABLED (default True) !!
#
# Every REST call and both WebSocket connections (ws/app/, ws/jetson/) skip
# real authentication while this is True — any request is treated as a
# fixed dev user / the configured Jetson, no valid JWT or device token
# required (see streaming/authentication.py DisabledAuthAuthentication,
# streaming/auth.py TokenAuthMiddleware). This is for local/LAN testing
# convenience only.
#
# Set AUTH_DISABLED=False in .env to turn real auth back on (JWT for
# Flutter, JETSON_AUTH_TOKEN for the Jetson) before any non-trusted
# deployment.
# ---------------------------------------------------------------------------
AUTH_DISABLED = env("AUTH_DISABLED")

# ---------------------------------------------------------------------------
# Single Jetson device identity — no Device DB model/API (see
# streaming/services.py). One Jetson only: its id + shared secret live here
# instead of a database row. Rotate JETSON_AUTH_TOKEN via .env + redeploy;
# it's compared directly against the ?token=/Authorization: Device <token>
# the Jetson presents (streaming/auth.py, streaming/authentication.py).
# ---------------------------------------------------------------------------
JETSON_DEVICE_ID = env("JETSON_DEVICE_ID", default="JETSON001")
JETSON_AUTH_TOKEN = env("JETSON_AUTH_TOKEN", default="changeme-dev-token")

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# DRF / JWT — Flutter authenticates over REST, then reuses the JWT as the
# WebSocket auth token (?token=<access>) for the signaling connection.
# ---------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        # Jetson has no Django user/JWT; it authenticates recording uploads
        # with its own device token instead (README_WebRTC.md #17).
        "streaming.authentication.DeviceTokenAuthentication",
        # Catch-all: only kicks in when AUTH_DISABLED and neither of the
        # above matched (no valid JWT / device token given) — auths as a
        # fixed dev user so every endpoint stays reachable with no token
        # at all. See settings.AUTH_DISABLED above.
        "streaming.authentication.DisabledAuthAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
    ),
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(hours=8),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
}

# Same-LAN deployment: Flutter/Jetson origins are on the local network and
# not known ahead of time, so CORS is left open. Tighten this for production.
CORS_ALLOW_ALL_ORIGINS = True

# ---------------------------------------------------------------------------
# Logging — without this, app-level logger.info()/.warning() calls (e.g.
# streaming.consumers logging each analysis_data sample as it's relayed and
# persisted — README_WebRTC.md #14) go nowhere: Python's logging module only
# has a "last resort" handler that prints WARNING+ with no config at all, so
# INFO never surfaces. This sends everything from our own apps (not
# Django/DB internals — those stay at WARNING to avoid drowning the output)
# to the console, which `docker logs`/`docker compose logs` capture.
# ---------------------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {"class": "logging.StreamHandler"},
    },
    "root": {
        "handlers": ["console"],
        "level": "WARNING",
    },
    "loggers": {
        "streaming": {"level": "INFO", "propagate": True},
        "telemetry": {"level": "INFO", "propagate": True},
        "dashboard": {"level": "INFO", "propagate": True},
    },
}
