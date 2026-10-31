from django.contrib import admin

from .models import Doctor, Patient, SessionReport


@admin.register(Doctor)
class DoctorAdmin(admin.ModelAdmin):
    list_display = ("doctor_id", "name", "specialty", "phone", "email", "is_active")
    list_filter = ("specialty", "is_active")
    search_fields = ("doctor_id", "name", "specialty", "email", "phone")


@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    list_display = ("patient_id", "name", "gender", "date_of_birth", "phone", "is_active", "created_at")
    list_filter = ("gender", "is_active")
    search_fields = ("patient_id", "name", "phone", "email")


@admin.register(SessionReport)
class SessionReportAdmin(admin.ModelAdmin):
    list_display = ("session", "patient", "test_type", "cadence", "walking_velocity", "created_at")
    list_filter = ("test_type",)
    search_fields = ("session__session_id", "patient__patient_id", "patient__name")
