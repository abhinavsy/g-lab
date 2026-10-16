from django.contrib import admin

from .models import AlertEvent, Recording, Session

# No Device/Camera admin — single-Jetson deployment, no Device/Camera model
# (see streaming/services.py). Check online status via GET
# /api/device/status/ instead; the id/secret live in settings
# (JETSON_DEVICE_ID/JETSON_AUTH_TOKEN, set via .env).


@admin.register(Session)
class SessionAdmin(admin.ModelAdmin):
    list_display = ("session_id", "patient", "device_id", "status", "started_at", "ended_at")
    list_filter = ("status",)
    search_fields = ("session_id",)


@admin.register(AlertEvent)
class AlertEventAdmin(admin.ModelAdmin):
    list_display = ("session", "alert_type", "message", "created_at")
    list_filter = ("alert_type",)


@admin.register(Recording)
class RecordingAdmin(admin.ModelAdmin):
    list_display = ("session", "clip_index", "duration_seconds", "created_at")
