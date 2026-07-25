"""
Sync AIAgent.api_key_encrypted help_text with current model definition.
No schema change — help_text is not stored in the DB.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("nucleus", "0019_m9_agent_api_key"),
    ]

    operations = [
        migrations.AlterField(
            model_name="aiagent",
            name="api_key_encrypted",
            field=models.TextField(
                blank=True,
                null=True,
                help_text="Fernet-encrypted API key. Do not set directly — use set_api_key().",
            ),
        ),
    ]
