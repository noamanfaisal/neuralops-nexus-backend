"""
Step 6 (docs/NUCLEUS-REVAMP.md, handoff change 6) — list a live MCP server's
tools.

POST /api/v1/mcp/tools/ {url?, bearer_token?} or {command?, env?, server_id?}
→ {"tools": [{name, one_line, read_only}]}. Nucleus calls this when an admin
attaches/saves an external MCP server, and from the "Refresh tools" button;
the answer lands on the server row and later ships back to triggers as
MCPServerInternal.tools (the stored catalog the approval policy reads).

stdio (2026-11-08): a command instead of a url dials by SPAWNING it — the
spawn spec (allowlisted argv, child-only secret env, SSH key file) comes
from ai_engine/pydantic_ai_system/tools/stdio_mcp.py, shared with the
toolset builder. The
first dial of an npx/uvx server downloads the package, so stdio gets a
longer leash than HTTP.

read_only comes ONLY from the server's own readOnlyHint annotation; a tool
without one answers null, and nucleus treats null as a write (asks first) —
the safe default the owner settled.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from fastapi_app.routers.trigger import _verify_key

router = APIRouter(prefix="/api/v1", tags=["mcp"])

DIAL_TIMEOUT_SECONDS = 20
STDIO_DIAL_TIMEOUT_SECONDS = 90  # npx/uvx fetch the package on first spawn


class ToolListRequest(BaseModel):
    url: str | None = None
    bearer_token: str | None = None
    # stdio road (either url or command must be given)
    command: str | None = None
    env: dict[str, str] | None = None
    server_id: str | None = None  # names the per-server SSH key file


class ToolOut(BaseModel):
    name: str
    one_line: str = ""
    read_only: bool | None = None


class ToolListResponse(BaseModel):
    tools: list[ToolOut]


def _dial_imports():
    """The pinned mcp 2.x client pieces (verified live against the installed
    package, 2026-10-15): streamable_http_client(url, *, http_client=None, …)
    yields (read_stream, write_stream); headers/auth travel on a pre-built
    httpx2.AsyncClient passed as http_client. Imported lazily so a package
    layout shift surfaces as the 502's reason, not an import crash at boot."""
    import httpx2  # noqa: PLC0415 — the mcp 2.x client's own HTTP library
    from mcp import ClientSession  # noqa: PLC0415
    from mcp.client.streamable_http import streamable_http_client  # noqa: PLC0415
    return ClientSession, streamable_http_client, httpx2


def read_only_hint(annotations) -> bool | None:
    """The server's readOnlyHint, whichever spelling the installed mcp
    library uses: 1.x models expose it as `readOnlyHint`, 2.x as
    `read_only_hint` (found live 2026-10-31: reading only the old name made
    EVERY tool unknown — draw.io's three read-only tools all asked first).
    Accepts the model object or a plain dict."""
    if not annotations:
        return None
    for name in ("read_only_hint", "readOnlyHint"):
        value = (annotations.get(name) if isinstance(annotations, dict)
                 else getattr(annotations, name, None))
        if value is not None:
            return bool(value)
    return None


@router.post("/mcp/tools/", response_model=ToolListResponse)
async def list_mcp_tools(req: ToolListRequest, _: str = Depends(_verify_key)) -> ToolListResponse:
    """One dial: initialize, list tools, hang up. Any failure — unreachable,
    refused auth, not an MCP server, a refused spawn — is one answer: 502
    with the reason, so nucleus can show it verbatim next to the Refresh
    button."""
    if not req.url and not req.command:
        raise HTTPException(status_code=422, detail="either url or command is required")

    if req.command:
        import asyncio  # noqa: PLC0415

        from fastmcp.client import Client  # noqa: PLC0415

        from ai_engine.pydantic_ai_system.tools.stdio_mcp import transport_for  # noqa: PLC0415
        try:
            transport = transport_for(req.server_id or req.command, req.command, req.env)
            async with asyncio.timeout(STDIO_DIAL_TIMEOUT_SECONDS):
                async with Client(transport) as client:
                    listed = await client.list_tools()
        except Exception as exc:  # noqa: BLE001 — every dial failure is the same 502 + why
            raise HTTPException(status_code=502,
                                detail=f"could not list tools: {type(exc).__name__}: {exc}")
        return ToolListResponse(tools=_to_tool_out(listed))

    headers = {"Authorization": f"Bearer {req.bearer_token}"} if req.bearer_token else {}
    try:
        ClientSession, streamable_http_client, httpx2 = _dial_imports()
        async with httpx2.AsyncClient(headers=headers, timeout=DIAL_TIMEOUT_SECONDS) as http_client:
            async with streamable_http_client(req.url, http_client=http_client) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.list_tools()
    except Exception as exc:  # noqa: BLE001 — every dial failure is the same 502 + why
        raise HTTPException(status_code=502,
                            detail=f"could not list tools: {type(exc).__name__}: {exc}")

    return ToolListResponse(tools=_to_tool_out(result.tools))


def _to_tool_out(tools_in) -> list[ToolOut]:
    """One mapping for both roads — the mcp SDK's ListToolsResult.tools and
    the fastmcp client's stdio list both yield objects with name/
    description/annotations."""
    tools: list[ToolOut] = []
    for tool in tools_in:
        read_only = read_only_hint(getattr(tool, "annotations", None))
        description = (tool.description or "").strip()
        one_line = description.splitlines()[0][:200] if description else ""
        tools.append(ToolOut(name=tool.name, one_line=one_line, read_only=read_only))
    return tools
