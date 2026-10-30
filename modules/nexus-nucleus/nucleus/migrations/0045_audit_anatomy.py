# AI audit log (1.3.0, owner's ask 2026-10-29): the prompt-anatomy fields on
# AIRequestLog — topic/project scope, the model seat, and the breakdown the
# engine captures (sections + history + retrieval + message). Hand-written,
# like every migration in this repo.
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("nucleus", "0044_chain_query"),
    ]

    operations = [
        migrations.AddField(
            model_name="airequestlog",
            name="topic_id",
            field=models.CharField(blank=True, db_index=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="airequestlog",
            name="project",
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="ai_request_logs", to="nucleus.project",
            ),
        ),
        migrations.AddField(
            model_name="airequestlog",
            name="role",
            field=models.CharField(blank=True, default="", max_length=20),
        ),
        migrations.AddField(
            model_name="airequestlog",
            name="model_name",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="airequestlog",
            name="breakdown",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
