"""
Every project gets a "NeuralOps Setup" internal MCP row (owner's ruling,
2026-10-30: the setup capability "should be a necessary part of every
project"). New projects get it from provisioning (workspace.services
.ensure_setup_row); this backfills the projects that already exist.

Data-only and idempotent: a project that already has the row (by its
reserved name) is left alone. Reverse is a no-op on purpose — taking the
row away from live personas would silently strip their tools.
"""
from django.db import migrations

SETUP_ROW_NAME = "NeuralOps Setup"
DESCRIPTION = (
    "This app's own administration tools: models, personas and topics. "
    "Every write pauses on an approval card, and the persona acts with "
    "the asking person's own rights."
)


def add_setup_rows(apps, schema_editor):
    Project = apps.get_model("nucleus", "Project")
    MCPServer = apps.get_model("nucleus", "MCPServer")
    for project in Project.objects.all().iterator():
        if MCPServer.objects.filter(
            project=project, name=SETUP_ROW_NAME, is_internal=True
        ).exists():
            continue
        MCPServer.objects.create(
            company=project.company,
            project=project,
            name=SETUP_ROW_NAME,
            is_internal=True,
            capability_config={"setup": {}},
            description=DESCRIPTION,
            # Internal rows must be auth "none" (mcp_internal_has_no_endpoint
            # constraint) — same note as the Capabilities row.
            auth_type="none",
            is_protected=True,
        )


class Migration(migrations.Migration):
    dependencies = [
        ("nucleus", "0045_audit_anatomy"),
    ]
    operations = [
        migrations.RunPython(add_setup_rows, migrations.RunPython.noop),
    ]
