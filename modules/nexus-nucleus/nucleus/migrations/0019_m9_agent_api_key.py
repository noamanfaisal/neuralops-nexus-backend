"""
M9 — Add api_key_encrypted to AIAgent for external agent credentials.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("nucleus", "0018_rename_workspace_chatsession_user_topic_idx_workspace_c_user_id_d1b4c5_idx_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="aiagent",
            name="api_key_encrypted",
            field=models.TextField(
                blank=True,
                null=True,
                help_text="Fernet-encrypted API key for external agents. Use set_api_key() / get_api_key().",
            ),
        ),
    ]
