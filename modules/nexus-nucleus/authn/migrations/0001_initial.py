import uuid

import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="DeviceSession",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("device_id", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("device_name", models.CharField(default="NeuralOps Desktop", max_length=255)),
                (
                    "status",
                    models.CharField(
                        choices=[("pending", "Pending"), ("active", "Active"), ("expired", "Expired")],
                        default="pending",
                        max_length=20,
                    ),
                ),
                ("user_id", models.CharField(blank=True, max_length=255, null=True)),
                ("email", models.EmailField(blank=True, max_length=254, null=True)),
                ("session_expires_at", models.DateTimeField(blank=True, null=True)),
                ("celery_task_id", models.CharField(blank=True, max_length=255, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "device_sessions",
            },
        ),
    ]
