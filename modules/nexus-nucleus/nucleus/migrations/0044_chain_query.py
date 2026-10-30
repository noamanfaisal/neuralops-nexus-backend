# Chains v2 (1.1.0, ruling 3): a chain takes a QUERY at run time — stored on
# the run so a resume after a checkpoint (a fresh Celery task) still sees it.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("nucleus", "0043_model_check_stamp"),
    ]

    operations = [
        migrations.AddField(
            model_name="runbookrun",
            name="query",
            field=models.TextField(blank=True, default=""),
        ),
    ]
