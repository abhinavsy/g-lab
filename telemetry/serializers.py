from rest_framework import serializers

from .models import AnalysisEvent


class AnalysisEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = AnalysisEvent
        fields = [
            "id",
            "hip_angle_left",
            "hip_angle_right",
            "knee_angle_left",
            "knee_angle_right",
            "speed",
            "spasm_detected",
            "raw_payload",
            "recorded_at",
        ]
        read_only_fields = fields
