"""
Layer 1 — the end-to-end MCP dial (closes the gap recorded with items 3+1+2):
a REAL MCP server (tests/fake_mcp.py, pinned mcp 2.x over streamable HTTP) is
dialed by the module, its tools arrive prefixed, annotations flow, and the
gate's rules apply to real MCP tools exactly as to natives.
"""
from __future__ import annotations

import pytest

from conftest import openai_model
from fake_mcp import make_mcp_app
from fake_nucleus import make_persona
from fake_provider import ServedApp

from ai_engine.pydantic_ai_system.tools.toolset_builder import _bearer_token

pytestmark = pytest.mark.asyncio


@pytest.fixture(scope="module")
def mcp_server():
    served = ServedApp(make_mcp_app()).start()
    yield served
    served.stop()


class _AuthRecorder:
    """ASGI wrapper: records the Authorization header of every HTTP request
    the fake MCP server receives — the dial test asserts on the real wire."""

    def __init__(self, app):
        self.app = app
        self.seen: list[str | None] = []

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
            self.seen.append(headers.get("authorization"))
        await self.app(scope, receive, send)


@pytest.fixture()
def recording_mcp_server():
    recorder = _AuthRecorder(make_mcp_app())
    served = ServedApp(recorder).start()
    served.auth_seen = recorder.seen
    yield served
    served.stop()


def _server_row(mcp_server, tools: list[dict] | None) -> dict:
    row = {
        "id": "s1", "name": "GitHub", "server_type": "custom", "transport": "http",
        "url": mcp_server.url + "/mcp", "command": None, "config": {},
        "secrets": {}, "is_first_party": False, "embed_output": False,
        "needs_reauth": False, "auth_type": "static_secrets",
        "token_env_var": "OAUTH_ACCESS_TOKEN",
    }
    if tools is not None:
        row["tools"] = tools
    return row


def _mcp_persona(harness, mcp_server, tools: list[dict] | None) -> dict:
    return make_persona(openai_model(harness),
                        mcp_servers=[_server_row(mcp_server, tools)])


STORED = [{"name": "search", "description": "Search code", "read_only": True},
          {"name": "create_issue", "description": "Open an issue", "read_only": False}]


async def test_mcp_read_tool_executes_against_the_real_server(harness, mcp_server):
    """E2E MCP — a stored-read tool is dialed, executed, and its REAL result returns.
    The model calls github__search (prefixed exactly as the catalog promises);
    the module dials the live server, the tool runs there, and the server's
    actual answer ("MCP-RESULT: …") reaches the model as the tool result — no
    pause, because the stored catalog says read_only=true."""
    harness.nucleus.persona = _mcp_persona(harness, mcp_server, STORED)
    harness.provider.script.steps = [
        {"kind": "tool_call", "call_id": "call_m1", "name": "github__search",
         "args": {"query": "auth bug"}},
        {"kind": "text", "text": "Found it."},
    ]
    events = await harness.trigger(
        harness.job(topic_tools=["mcp:s1/search", "mcp:s1/create_issue"]))
    types = [e["type"] for e in events]
    assert "approval_requested" not in types and types[-1] == "message_done"

    first = harness.provider.requests[0]
    names = [t["function"]["name"] for t in first.get("tools", [])]
    assert "github__search" in names and "github__create_issue" in names
    body = harness.provider.requests[-1]
    tool_msgs = [m for m in body["messages"] if m.get("role") == "tool"]
    assert any("MCP-RESULT: auth bug" in m["content"] for m in tool_msgs)
    # item 19 applies to MCP tools too
    [end] = [e for e in events if e["type"] == "tool_call_end"]
    assert end["tool_result"]["name"] == "github__search" and end["tool_result"]["ok"]


async def test_mcp_unlabeled_write_pauses(harness, mcp_server):
    """E2E MCP — a stored write (read_only=false) pauses before touching the server.
    github__create_issue is loaded but a write: the run pauses with the
    approval card carrying the prefixed name; nothing was executed server-side
    (the pause happens before the dial-out of that call)."""
    harness.nucleus.persona = _mcp_persona(harness, mcp_server, STORED)
    harness.provider.script.steps = [
        {"kind": "tool_call", "call_id": "call_m2", "name": "github__create_issue",
         "args": {"title": "new bug"}},
    ]
    events = await harness.trigger(
        harness.job(topic_tools=["mcp:s1/search", "mcp:s1/create_issue"]))
    types = [e["type"] for e in events]
    assert types[-1] == "message_paused"
    [req] = [e for e in events if e["type"] == "approval_requested"]
    assert req["approval"]["tool"] == "github__create_issue"
    assert "new bug" in req["approval"]["args_preview"]


# ── the Bearer scheme (bug found live 2026-10-27, docs/MISSING.md) ───────────
# The pinned framework copies authorization_token VERBATIM into the
# Authorization header, so _bearer_token must carry the scheme itself.

async def test_bearer_token_shapes():
    """Every stored-secret shape maps to a correct Authorization value."""
    static = lambda secret: {"auth_type": "static_secrets",
                             "secrets": {"client_secret": secret}}
    assert _bearer_token(static("raw")) == "Bearer raw"
    assert _bearer_token(static("Bearer raw")) == "Bearer raw"      # no double prefix
    assert _bearer_token(static("bearer raw")) == "bearer raw"      # any case, kept verbatim
    assert _bearer_token(static("  raw  ")) == "Bearer raw"         # padding stripped
    assert _bearer_token(static("")) is None
    assert _bearer_token(static(None)) is None
    assert _bearer_token({"auth_type": "static_secrets", "secrets": {}}) is None
    assert _bearer_token({"auth_type": "static_secrets"}) is None


async def test_bearer_token_oauth2_shapes():
    """The oauth2 branch gets the same scheme handling."""
    assert _bearer_token({
        "auth_type": "oauth2", "token_env_var": "OAUTH_ACCESS_TOKEN",
        "secrets": {"OAUTH_ACCESS_TOKEN": "usertok"},
    }) == "Bearer usertok"
    # a custom env-var name is honoured, and the default name fills in
    assert _bearer_token({
        "auth_type": "oauth2", "token_env_var": "GH_TOKEN",
        "secrets": {"GH_TOKEN": "ghtok"},
    }) == "Bearer ghtok"
    assert _bearer_token({
        "auth_type": "oauth2", "token_env_var": None,
        "secrets": {"OAUTH_ACCESS_TOKEN": "Bearer kept"},
    }) == "Bearer kept"
    assert _bearer_token({"auth_type": "oauth2", "secrets": {}}) is None


async def test_mcp_dial_sends_bearer_header_on_the_wire(harness, recording_mcp_server):
    """E2E — a raw stored secret arrives at the server as 'Bearer <token>'.
    The server row stores the token the way the UI saves it (no scheme); the
    fake server records the Authorization header of every request it serves
    and each one must carry the exact prefixed value."""
    row = _server_row(recording_mcp_server, STORED)
    row["secrets"] = {"client_secret": "tok-123"}
    harness.nucleus.persona = make_persona(openai_model(harness), mcp_servers=[row])
    harness.provider.script.steps = [
        {"kind": "tool_call", "call_id": "call_b1", "name": "github__search",
         "args": {"query": "auth"}},
        {"kind": "text", "text": "Done."},
    ]
    events = await harness.trigger(
        harness.job(topic_tools=["mcp:s1/search", "mcp:s1/create_issue"]))
    assert [e["type"] for e in events][-1] == "message_done"
    seen = recording_mcp_server.auth_seen
    assert seen, "the fake MCP server saw no requests"
    assert all(value == "Bearer tok-123" for value in seen), seen


async def test_mcp_annotation_passthrough_without_stored_list(harness, mcp_server):
    """E2E MCP — Open (c) resolved: a live readOnlyHint reaches the gate.
    The server row carries NO stored tool list (today's nucleus): the whole
    server is loaded (mcp:s1), tool names come only from the live dial, and
    search — whose only read marker is the server's own readOnlyHint
    annotation — runs WITHOUT asking. The annotation therefore survives the
    pinned MCP capability into ToolDefinition.metadata."""
    harness.nucleus.persona = _mcp_persona(harness, mcp_server, tools=None)
    harness.provider.script.steps = [
        {"kind": "tool_call", "call_id": "call_m3", "name": "github__search",
         "args": {"query": "ping"}},
        {"kind": "text", "text": "Done."},
    ]
    events = await harness.trigger(harness.job(topic_tools=["mcp:s1"]))
    types = [e["type"] for e in events]
    assert "approval_requested" not in types and types[-1] == "message_done"
    body = harness.provider.requests[-1]
    tool_msgs = [m for m in body["messages"] if m.get("role") == "tool"]
    assert any("MCP-RESULT: ping" in m["content"] for m in tool_msgs)
