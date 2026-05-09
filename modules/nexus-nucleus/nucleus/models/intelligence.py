from django.conf import settings
from django.db import models

from apps.core.models import TenantBaseModel, ProjectBaseModel

class Provider(TenantBaseModel):
    """
    Model provider name only.

    Example:
    - litellm
    - openai
    - ollama
    - azure
    """

    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=100)

    class Meta:
        db_table = "intelligence_provider"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "slug"],
                name="uniq_provider_slug_per_company",
            )
        ]

    def __str__(self):
        return self.name




class MCPServer(TenantBaseModel):
    class Transport(models.TextChoices):
        STDIO = "stdio", "STDIO"
        SSE = "sse", "SSE"
        HTTP = "http", "HTTP"

    name = models.CharField(max_length=255)

    transport = models.CharField(
        max_length=20,
        choices=Transport.choices,
        default=Transport.HTTP,
        db_index=True,
    )

    command_url = models.CharField(
        max_length=500,
        help_text="Command for stdio, or URL for HTTP/SSE MCP server.",
    )

    config = models.JSONField(
        default=dict,
        blank=True,
        help_text="Non-secret MCP configuration.",
    )

    secret_ref = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text="Secret manager reference. Do not store raw secrets.",
    )

    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        db_table = "intelligence_mcp_server"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "name"],
                name="uniq_mcp_server_name_per_company",
            )
        ]
        indexes = [
            models.Index(fields=["company", "is_active"]),
            models.Index(fields=["company", "transport"]),
        ]

    def __str__(self):
        return self.name

class AIAgent(ProjectBaseModel):
    """
    AI agent configuration.

    Agent has a User identity, so it can appear in chat as sender.
    """

    identity_user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ai_agent_profile",
    )

    name = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)

    model = models.ForeignKey(
        "intelligence.AIModel",
        on_delete=models.PROTECT,
        related_name="agents",
    )

    mcp_servers = models.ManyToManyField(
        MCPServer,
        through="AIAgentMCPServer",
        related_name="agents",
        blank=True,
    )

    system_prompt = models.TextField()

    safety_mode = models.BooleanField(default=True)

    config = models.JSONField(
        default=dict,
        blank=True,
        help_text="Agent runtime config: max_steps, tool_choice, memory policy, etc.",
    )

    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        db_table = "intelligence_ai_agent"
        constraints = [
            models.UniqueConstraint(
                fields=["project", "name"],
                name="uniq_ai_agent_name_per_project",
            )
        ]
        indexes = [
            models.Index(fields=["company", "project", "is_active"]),
        ]

    def __str__(self):
        return self.name


class AIAgentMCPServer(models.Model):
    agent = models.ForeignKey(
        AIAgent,
        on_delete=models.CASCADE,
        related_name="mcp_links",
    )

    mcp_server = models.ForeignKey(
        MCPServer,
        on_delete=models.CASCADE,
        related_name="agent_links",
    )

    is_active = models.BooleanField(default=True, db_index=True)

    config = models.JSONField(
        default=dict,
        blank=True,
        help_text="Agent-specific MCP config, tool allowlist, limits, etc.",
    )

    class Meta:
        db_table = "intelligence_ai_agent_mcp_server"
        constraints = [
            models.UniqueConstraint(
                fields=["agent", "mcp_server"],
                name="uniq_ai_agent_mcp_server",
            )
        ]

    def __str__(self):
        return f"{self.agent} -> {self.mcp_server}"