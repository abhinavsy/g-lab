import django.db.models.deletion
from django.db import migrations, models


def backfill_patient(apps, schema_editor):
    AnalysisEvent = apps.get_model("telemetry", "AnalysisEvent")
    Session = apps.get_model("streaming", "Session")
    for session in Session.objects.filter(analysis_events__isnull=False).distinct():
        AnalysisEvent.objects.filter(session=session).update(patient_id=session.patient_id)


class Migration(migrations.Migration):

    dependencies = [
        ("telemetry", "0002_remove_analysisevent_hip_angle_and_more"),
        ("patient", "0002_patient_details"),
        ("streaming", "0002_move_patient_to_patient_app"),
    ]

    operations = [
        migrations.AddField(
            model_name="analysisevent",
            name="patient",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="analysis_events",
                to="patient.patient",
            ),
        ),
        migrations.RunPython(backfill_patient, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="analysisevent",
            name="patient",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="analysis_events",
                to="patient.patient",
            ),
        ),
    ]
