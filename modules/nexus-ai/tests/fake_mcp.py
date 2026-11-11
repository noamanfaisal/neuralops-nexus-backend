"""
A REAL MCP server for the dial test (pinned mcp 2.x) — two tools:

    search(query)        annotated readOnlyHint=True  → "MCP-RESULT: <query>"
    create_issue(title)  no annotations               → "created: <title>"

Served over streamable HTTP (the transport our MCPServerInternal rows use) by
the same ServedApp the other fakes use. This is the instrument that closes
Layer 1's "no server was ever dialed" gap: pydantic-ai's MCP capability dials
THIS, lists its tools live, and executes against it.

stdio road (landed 2026-11-08): `python tests/fake_mcp.py` serves the SAME
two tools over stdio — the spawn target for the stdio dial tests. The
`env_probe` tool exists for those: it answers with FAKE_SECRET from the
process environment, proving the engine delivered the row's secrets to the
CHILD process (and only there).
"""
from __future__ import annotations

import os

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations


def make_mcp_server() -> MCPServer:
    server = MCPServer("fake-github")

    @server.tool(annotations=ToolAnnotations(readOnlyHint=True))
    def search(query: str) -> str:
        """Search the fake code base."""
        return f"MCP-RESULT: {query}"

    @server.tool()
    def create_issue(title: str) -> str:
        """Open an issue (a write — no readOnlyHint on purpose)."""
        return f"created: {title}"

    @server.tool(annotations=ToolAnnotations(readOnlyHint=True))
    def make_payload(title: str) -> dict:
        """Answer a search-args object — the console nesting test's inner
        tool (its dict result becomes the outer call's args)."""
        return {"query": f"made:{title}"}

    @server.tool(annotations=ToolAnnotations(readOnlyHint=True))
    def env_probe() -> str:
        """Answer the FAKE_SECRET env var — the stdio tests' proof that
        secrets arrive as child env."""
        return "env=" + os.environ.get("FAKE_SECRET", "MISSING")

    return server


def make_mcp_app():
    return make_mcp_server().streamable_http_app(stateless_http=True)


if __name__ == "__main__":
    make_mcp_server().run()  # stdio
