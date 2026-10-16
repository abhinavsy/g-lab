# Moves Patient from the streaming app into this one without touching the
# data: the existing streaming_patient table is renamed in place and only
# Django's migration state gets a new model. streaming/0002 then repoints
# Session.patient and drops streaming.Patient from state.

from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("streaming", "0001_initial"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql="ALTER TABLE streaming_patient RENAME TO patient_patient",
                    reverse_sql="ALTER TABLE patient_patient RENAME TO streaming_patient",
                ),
            ],
            state_operations=[
                migrations.CreateModel(
                    name="Patient",
                    fields=[
                        ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                        ("patient_id", models.CharField(max_length=32, unique=True)),
                        ("name", models.CharField(max_length=255)),
                        ("notes", models.TextField(blank=True)),
                        ("created_at", models.DateTimeField(auto_now_add=True)),
                    ],
                ),
            ],
        ),
    ]
