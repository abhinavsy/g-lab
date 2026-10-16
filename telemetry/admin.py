from django.contrib import admin

from .models import AnalysisEvent


@admin.register(AnalysisEvent)
class AnalysisEventAdmin(admin.ModelAdmin):
    list_display = (
        "session",
        "hip_angle_left",
        "hip_angle_right",
        "knee_angle_left",
        "knee_angle_right",
        "speed",
        "spasm_detected",
        "recorded_at",
    )
    list_filter = ("spasm_detected",)
