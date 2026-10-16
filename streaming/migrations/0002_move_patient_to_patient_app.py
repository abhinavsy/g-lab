# State-only half of moving Patient to the patient app (see
# patient/migrations/0001_initial.py, which renames the table). The FK
# constraint already points at the renamed table, so no DB changes here.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("streaming", "0001_initial"),
        ("patient", "0001_initial"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name="session",
                    name="patient",
                    field=models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="sessions",
                        to="patient.patient",
                    ),
                ),
                migrations.DeleteModel(name="Patient"),
            ],
        ),
    ]
