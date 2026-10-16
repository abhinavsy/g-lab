from django.db import migrations, models


def number_existing_sessions(apps, schema_editor):
    """Numbers each patient's existing sessions 1, 2, 3, ... oldest first."""
    Session = apps.get_model("streaming", "Session")
    counters = {}
    for session in Session.objects.order_by("patient_id", "created_at", "id"):
        counters[session.patient_id] = counters.get(session.patient_id, 0) + 1
        session.session_number = counters[session.patient_id]
        session.save(update_fields=["session_number"])


class Migration(migrations.Migration):

    dependencies = [
        ("streaming", "0002_move_patient_to_patient_app"),
    ]

    operations = [
        migrations.AddField(
            model_name="session",
            name="session_number",
            field=models.PositiveIntegerField(editable=False, null=True),
        ),
        migrations.RunPython(number_existing_sessions, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="session",
            name="session_number",
            field=models.PositiveIntegerField(editable=False),
        ),
        migrations.AddConstraint(
            model_name="session",
            constraint=models.UniqueConstraint(
                fields=("patient", "session_number"), name="unique_session_number_per_patient"
            ),
        ),
    ]
