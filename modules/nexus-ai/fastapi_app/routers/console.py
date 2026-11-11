"""
Project console v1 (docs/MISSING.md "project console") — the data bus.

POST /api/v1/console/run executes ONE typed line from the project console
CLI. Nucleus is the only caller: it holds both gates (Project.console_enabled
and the caller's mcp.playground right), decrypts the project's MCP secrets,
ships the server rows + the project folder path here, and writes the audit
row. No model is involved — the human IS the caller — so there is no
approval gate and no tokens are spent.

Grammar (one line):

    server.tool({"key": "value"})      call a tool with literal JSON args
    server.tool()                      no args
    server.tool(other.tool2({...}))    ONE nesting level: the inner result
                                       becomes the outer args (a dict passes
                                       as-is; anything else arrives wrapped
                                       as {"input": value})
    server.tool(@/path.json)           args loaded from the project folder
    server.tool(_)                     args = the last result (the CLI keeps
                                       it and sends it as last_result)
    ... > /path.json                   save the full result in the project
                                       folder (size-capped)

Paths are project-folder-relative. `..` and symlink escapes are refused —
the project folder (workspace_root, the same path nucleus puts in the
Filesystem capability's root_dir) is the whole world.

Errors are split by who must fix them: a malformed line, an unknown server
or a bad path is a 422 (the CLI prints the detail); a dial failure or a
tool-reported error is a 200 with ok=false — in a REPL those are results,
not transport faults.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from fastapi_app.routers.mcp_tools import _dial_imports
from fastapi_app.routers.trigger import _verify_key

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["console"])

CALL_TIMEOUT_SECONDS = 60          # one HTTP tool call, generous for reports
STDIO_CALL_TIMEOUT_SECONDS = 120   # npx/uvx fetch the package on first spawn
LOAD_MAX_BYTES = 2_000_000         # @/path args file
SAVE_MAX_BYTES = 20_000_000        # > /path result file
INLINE_MAX_BYTES = 800_000         # bigger results must be saved, not echoed


# ---------------------------------------------------------------- the grammar

class ConsoleParseError(ValueError):
    """The line itself is wrong — a 422, the CLI shows the message."""


@dataclass
class Call:
    server: str
    tool: str
    args_json: dict | None = None   # literal {...}
    args_file: str | None = None    # @/path
    args_last: bool = False         # _
    inner: "Call | None" = None     # one nested call


@dataclass
class ParsedLine:
    call: Call
    save_to: str | None = None      # > /path


_HEAD = re.compile(r"([A-Za-z0-9][A-Za-z0-9_-]*)\s*\.\s*([A-Za-z0-9_][A-Za-z0-9_-]*)\s*\(")


def _find_close(text: str, start: int) -> int:
    """Index of the ')' closing the '(' just before `start`. Parens inside
    JSON strings don't count (a query may contain ')')."""
    depth, i, in_str, esc = 1, start, False, False
    while i < len(text):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise ConsoleParseError("unbalanced parentheses")


def _parse_call(text: str, depth: int = 0) -> Call:
    match = _HEAD.match(text)
    if not match:
        raise ConsoleParseError(
            "expected server.tool({...}) — e.g. github.search({\"query\": \"bug\"})")
    close = _find_close(text, match.end())
    if text[close + 1:].strip():
        raise ConsoleParseError(f"unexpected text after ')': {text[close + 1:].strip()!r}")
    call = Call(server=match.group(1), tool=match.group(2))
    body = text[match.end():close].strip()
    if not body:
        call.args_json = {}
    elif body == "_":
        call.args_last = True
    elif body.startswith("@"):
        path = body[1:].strip()
        if not path:
            raise ConsoleParseError("'@' needs a path, e.g. @/issues/open.json")
        call.args_file = path
    elif body.startswith("{"):
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError as exc:
            raise ConsoleParseError(f"bad JSON args: {exc}") from exc
        if not isinstance(parsed, dict):
            raise ConsoleParseError("tool args must be a JSON object")
        call.args_json = parsed
    else:
        if depth >= 1:
            raise ConsoleParseError("only one nesting level is allowed")
        call.inner = _parse_call(body, depth + 1)
    return call


def parse_line(line: str) -> ParsedLine:
    line = line.strip()
    match = _HEAD.match(line)
    if not match:
        raise ConsoleParseError(
            "expected server.tool({...}) — e.g. github.search({\"query\": \"bug\"})")
    close = _find_close(line, match.end())
    rest = line[close + 1:].strip()
    save_to = None
    if rest:
        if not rest.startswith(">"):
            raise ConsoleParseError(f"unexpected trailing text: {rest!r}")
        save_to = rest[1:].strip()
        if not save_to:
            raise ConsoleParseError("'>' needs a path, e.g. > /issues/open.json")
    return ParsedLine(call=_parse_call(line[:close + 1]), save_to=save_to)


def resolve_project_path(workspace_root: str, user_path: str) -> Path:
    """A console path, pinned inside the project folder. Leading '/' means
    the project root; '..' and symlinks that escape are refused."""
    root = Path(workspace_root).resolve()
    rel = user_path.strip().lstrip("/")
    if not rel:
        raise ConsoleParseError("empty path")
    candidate = (root / rel).resolve()
    if candidate != root and root not in candidate.parents:
        raise ConsoleParseError(f"path escapes the project folder: {user_path!r}")
    return candidate


# ---------------------------------------------------------------- the wire

class ConsoleServer(BaseModel):
    name: str
    url: str | None = None
    bearer_token: str | None = None
    command: str | None = None
    env: dict[str, str] | None = None
    server_id: str | None = None


class ConsoleRunRequest(BaseModel):
    line: str
    servers: list[ConsoleServer] = []
    workspace_root: str | None = None   # the project folder; needed for > and @
    last_result: Any = None             # the CLI's `_` buffer


class ConsoleRunResponse(BaseModel):
    ok: bool
    server: str | None = None
    tool: str | None = None
    result: Any = None            # structured JSON when the tool offered it
    text: str | None = None       # text blocks (or a preview when truncated)
    truncated: bool = False
    saved_to: str | None = None
    saved_bytes: int | None = None
    duration_ms: int | None = None
    error: str | None = None


# ---------------------------------------------------------------- execution

def _extract(res) -> tuple[Any, str | None, bool]:
    """(structured, text, is_error) from a CallToolResult — both the fastmcp
    client's spelling (structured_content/is_error) and the mcp 2.x SDK's
    (structuredContent/isError)."""
    def attr(snake: str, camel: str):
        # probe the camelCase spelling only when snake_case is ABSENT — the
        # fastmcp result keeps both and warns on the deprecated one
        return getattr(res, snake) if hasattr(res, snake) else getattr(res, camel, None)

    is_error = bool(attr("is_error", "isError"))
    structured = attr("structured_content", "structuredContent")
    texts = [t for t in (getattr(block, "text", None)
                         for block in (getattr(res, "content", None) or [])) if t]
    return structured, ("\n".join(texts) or None), is_error


def _as_args(value: Any) -> dict:
    """A result reused as args. A JSON-object text result parses into args
    (some servers answer dicts as JSON text, not structured content); the
    SDKs' {"result": X} scalar wrapper is unwrapped; a dict passes as-is;
    anything else arrives as {"input": value} so the outer tool still gets
    an object."""
    if isinstance(value, str) and value.lstrip().startswith("{"):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            value = parsed
    if isinstance(value, dict) and set(value) == {"result"}:
        value = value["result"]
    return value if isinstance(value, dict) else {"input": value}


async def _dial_and_call(server: ConsoleServer, tool: str,
                         args: dict) -> tuple[Any, str | None, bool]:
    """One dial, one tool call, hang up — the same two roads /mcp/tools/
    drives (stdio spawn via the shared spawn spec; streamable HTTP via the
    pinned mcp 2.x client)."""
    if server.command:
        from fastmcp.client import Client  # noqa: PLC0415

        from ai_engine.pydantic_ai_system.tools.stdio_mcp import transport_for  # noqa: PLC0415
        transport = transport_for(server.server_id or server.command,
                                  server.command, server.env)
        async with asyncio.timeout(STDIO_CALL_TIMEOUT_SECONDS):
            async with Client(transport) as client:
                res = await client.call_tool(tool, args)
        return _extract(res)
    if not server.url:
        raise HTTPException(status_code=422,
                            detail=f"server {server.name!r} has neither url nor command")
    ClientSession, streamable_http_client, httpx2 = _dial_imports()
    headers = {"Authorization": f"Bearer {server.bearer_token}"} if server.bearer_token else {}
    async with httpx2.AsyncClient(headers=headers, timeout=CALL_TIMEOUT_SECONDS) as http_client:
        async with streamable_http_client(server.url, http_client=http_client) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                res = await session.call_tool(tool, arguments=args)
    return _extract(res)


def _pick_server(name: str, servers: list[ConsoleServer]) -> ConsoleServer:
    for row in servers:
        if row.name == name:
            return row
    known = ", ".join(sorted(row.name for row in servers)) or "none"
    raise HTTPException(status_code=422,
                        detail=f"unknown server {name!r} (this project has: {known})")


async def _resolve_args(call: Call, req: ConsoleRunRequest) -> dict:
    if call.args_json is not None:
        return call.args_json
    if call.args_last:
        if req.last_result is None:
            raise HTTPException(status_code=422, detail="no last result to use for '_'")
        return _as_args(req.last_result)
    if call.args_file:
        if not req.workspace_root:
            raise HTTPException(status_code=422,
                                detail="'@' needs a project folder (workspace_root)")
        path = resolve_project_path(req.workspace_root, call.args_file)
        if not path.is_file():
            raise HTTPException(status_code=422, detail=f"no such file: {call.args_file}")
        if path.stat().st_size > LOAD_MAX_BYTES:
            raise HTTPException(status_code=422,
                                detail=f"args file over {LOAD_MAX_BYTES} bytes")
        try:
            return _as_args(json.loads(path.read_text()))
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=422,
                                detail=f"args file is not JSON: {exc}") from exc
    # a nested call — its failure is the line's failure
    inner_server = _pick_server(call.inner.server, req.servers)
    inner_args = await _resolve_args(call.inner, req)
    structured, text, is_error = await _dial_and_call(inner_server, call.inner.tool, inner_args)
    if is_error:
        raise _InnerCallFailed(f"{call.inner.server}.{call.inner.tool} failed: "
                               f"{text or structured}")
    return _as_args(structured if structured is not None else text)


class _InnerCallFailed(Exception):
    """The nested call errored — the whole line answers ok=false with why."""


@router.post("/console/run", response_model=ConsoleRunResponse)
async def console_run(req: ConsoleRunRequest,
                      _: str = Depends(_verify_key)) -> ConsoleRunResponse:
    try:
        parsed = parse_line(req.line)
    except ConsoleParseError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    outer = parsed.call
    server = _pick_server(outer.server, req.servers)

    # the save path is validated BEFORE the call — a typo shouldn't cost a dial
    save_path: Path | None = None
    if parsed.save_to:
        if not req.workspace_root:
            raise HTTPException(status_code=422,
                                detail="'>' needs a project folder (workspace_root)")
        try:
            save_path = resolve_project_path(req.workspace_root, parsed.save_to)
        except ConsoleParseError as exc:
            raise HTTPException(status_code=422, detail=str(exc))

    started = time.monotonic()
    try:
        args = await _resolve_args(outer, req)
        structured, text, is_error = await _dial_and_call(server, outer.tool, args)
    except HTTPException:
        raise
    except _InnerCallFailed as exc:
        return ConsoleRunResponse(ok=False, server=outer.server, tool=outer.tool,
                                  error=str(exc),
                                  duration_ms=int((time.monotonic() - started) * 1000))
    except Exception as exc:  # noqa: BLE001 — every dial/tool failure is a REPL result
        return ConsoleRunResponse(ok=False, server=outer.server, tool=outer.tool,
                                  error=f"{type(exc).__name__}: {exc}",
                                  duration_ms=int((time.monotonic() - started) * 1000))
    duration_ms = int((time.monotonic() - started) * 1000)

    if is_error:
        return ConsoleRunResponse(ok=False, server=outer.server, tool=outer.tool,
                                  error=text or json.dumps(structured),
                                  duration_ms=duration_ms)

    result_value = structured if structured is not None else (
        {"text": text} if text is not None else None)

    saved_to = saved_bytes = None
    if save_path is not None:
        payload = json.dumps(result_value, indent=2, ensure_ascii=False,
                             default=str).encode()
        if len(payload) > SAVE_MAX_BYTES:
            return ConsoleRunResponse(ok=False, server=outer.server, tool=outer.tool,
                                      error=f"result is {len(payload)} bytes — over the "
                                            f"{SAVE_MAX_BYTES}-byte save cap",
                                      duration_ms=duration_ms)
        save_path.parent.mkdir(parents=True, exist_ok=True)
        save_path.write_bytes(payload)
        saved_to = "/" + str(save_path.relative_to(Path(req.workspace_root).resolve()))
        saved_bytes = len(payload)

    # big results must travel as files, not chat-sized JSON
    truncated = False
    inline_result: Any = result_value
    inline_text = text
    serialized = json.dumps(result_value, default=str) if result_value is not None else ""
    if len(serialized) > INLINE_MAX_BYTES:
        truncated = True
        inline_result = None
        inline_text = serialized[:2000] + (
            f"… [{len(serialized)} bytes — rerun with > /path.json to save the full result]"
            if saved_to is None else f"… [{len(serialized)} bytes — full result in {saved_to}]")

    logger.info("console: %s.%s ok=%s bytes=%s saved=%s",
                outer.server, outer.tool, True, len(serialized), saved_to)
    return ConsoleRunResponse(ok=True, server=outer.server, tool=outer.tool,
                              result=inline_result, text=inline_text, truncated=truncated,
                              saved_to=saved_to, saved_bytes=saved_bytes,
                              duration_ms=duration_ms)
