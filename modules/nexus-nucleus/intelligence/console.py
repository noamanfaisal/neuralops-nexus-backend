"""
Project console v1 (docs/MISSING.md "project console") — nucleus's half.

The console is a data bus: a person types `server.tool({json})` lines in the
`neuralops-console` CLI, nucleus relays each one to the engine's
POST /console/run, and the engine dials the named project MCP server and
pipes results through the project folder (`> /path`, `@/path`). No model is
involved and no approval card fires — the human IS the caller — so the two
gates live HERE, checked on every line by the API layer before run_line is
reached:

    1. Project.console_enabled — the project's own switch (project.update
       holders flip it in project settings).
    2. mcp.playground — the caller's right (Admin-tier, like
       project.terminal).

This module does the rest: turns the project's active external MCP rows into
engine ConsoleServer rows (slugged names, decrypted secrets — the same trust
boundary as the trigger job, container-to-container only), points the engine
at the project folder, relays the line, and writes the ConsoleLog audit row
whatever happened.
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# What the CLI user types before the dot. Same rule as the engine's registry
# slug (ai_engine/.../registry.py server_slug): lowercase, runs of anything
# non-alphanumeric become one underscore.
def server_slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_") or "mcp"


def _bearer_for_dial(server) -> str | None:
    """The same rule the tool-refresh dial applies (intelligence/api.py):
    oauth2 servers send the user access token, static ones client_secret."""
    secrets = server.get_secrets()
    if server.auth_type == "oauth2":
        return secrets.get((server.oauth_config or {}).get("token_env_var", "OAUTH_ACCESS_TOKEN"))
    return secrets.get("client_secret")


def console_rows(project) -> list[dict]:
    """The project's dialable external servers as engine ConsoleServer rows.
    Internal capability rows (Filesystem/Shell/Setup) are not MCP servers —
    the console reaches the project folder through `>`/`@` instead."""
    rows = []
    for server in project.mcp_servers.filter(is_active=True, is_internal=False).order_by("name"):
        if server.transport == "stdio" and server.command:
            rows.append({"name": server_slug(server.name), "command": server.command,
                         "env": server.get_secrets() or None, "server_id": str(server.id)})
        elif server.transport in ("http", "sse") and server.url:
            rows.append({"name": server_slug(server.name), "url": server.url,
                         "bearer_token": _bearer_for_dial(server)})
    return rows


def list_servers(project) -> list[dict]:
    """What the CLI's `servers` command prints: each dialable server's console
    name and its STORED tool list (names + one-liners, the Refresh-tools
    catalog) — no dial, no secrets."""
    out = []
    for server in project.mcp_servers.filter(is_active=True, is_internal=False).order_by("name"):
        dialable = bool((server.transport == "stdio" and server.command)
                        or (server.transport in ("http", "sse") and server.url))
        if not dialable:
            continue
        out.append({
            "name": server_slug(server.name),
            "title": server.name,
            "transport": server.transport,
            "tools": [{"name": t.get("name", ""), "description": t.get("description", ""),
                       "read_only": t.get("read_only")}
                      for t in (server.tools or []) if t.get("name")],
        })
    return out


def run_line(company, user, project, line: str, last_result=None) -> tuple[int, dict | str]:
    """One console line, relayed to the engine. Gates are the CALLER's job
    (workspace/api.py checks console_enabled + mcp.playground before this).
    Answers (status, body) — 200 with the engine's result dict (ok=false is
    a REPL result riding inside it), 4xx/502 with a worded detail. The
    ConsoleLog audit row is written whatever happened."""
    from django.conf import settings
    import os

    from chat.nexus_ai import NexusAIClient
    from nucleus.models import ConsoleLog
    from workspace.services import get_project_folder_name

    line = (line or "").strip()
    if not line:
        return 422, "empty line"

    workspace_root = os.path.join(settings.PROJECTS_ROOT, get_project_folder_name(project))
    payload = {
        "line": line,
        "servers": console_rows(project),
        "workspace_root": workspace_root,
        "last_result": last_result,
    }
    status, body = NexusAIClient().console_run(payload)

    result = body if isinstance(body, dict) else {}
    ConsoleLog.objects.create(
        company=company, project=project, user=user,
        line=line[:2000],
        server=(result.get("server") or "")[:255],
        tool=(result.get("tool") or "")[:255],
        ok=bool(result.get("ok")) if status == 200 else False,
        error=(result.get("error") or "") if status == 200 else str(body)[:2000],
        saved_to=(result.get("saved_to") or "")[:512],
        duration_ms=int(result.get("duration_ms") or 0),
    )
    logger.info("[console] user=%s project=%s status=%s line=%r",
                user.id, project.id, status, line[:120])
    return status, body
