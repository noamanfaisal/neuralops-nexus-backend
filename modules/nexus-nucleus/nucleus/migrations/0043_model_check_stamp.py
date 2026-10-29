# Save-lock (owner's ruling 2026-10-28, MISSING.md B14): the Edit dialog locks
# Save until the model has passed a provider check, so "has passed before" has
# to survive a reload. One nullable timestamp; existing rows start unstamped
# and get their stamp from the next check that passes with the stored values.
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("nucleus", "0042_remove_recall_and_deliverables"),
    ]

    operations = [
        migrations.AddField(
            model_name="modelconfig",
            name="last_check_ok_at",
            field=models.DateTimeField(
                blank=True,
                null=True,
                help_text="When the stored values last passed a provider check. Set by the check endpoint only.",
            ),
        ),
    ]
