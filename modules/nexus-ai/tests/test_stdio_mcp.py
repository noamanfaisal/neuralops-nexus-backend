"""
The stdio spawn spec (ai_engine/pydantic_ai_system/tools/stdio_mcp.py, landed
2026-11-08) and the
refresh dial's stdio road (fastapi_app/routers/mcp_tools.py): allowlisted
argv, child-only secret env, the SSH key materialized to a 0600 file - and a
REAL spawned server (tests/fake_mcp.py over stdio) listing its tools through
the route handler.
"""
from __future__ import annotations

import stat
import sys
from pathlib import Path

import pytest

from ai_engine.pydantic_ai_system.tools.stdio_mcp import (
    KEY_FILE_PLACEHOLDER,
    SSH_KEY_SECRET,
    build_spec,
)

FAKE_MCP = Path(__file__).with_name("fake_mcp.py")
PYTHON = Path(sys.executable).name


def _allow_python(monkeypatch):
    monkeypatch.setenv("MCP_STDIO_ALLOWED_COMMANDS", f"ssh,npx,uvx,{PYTHON}")


def _keys_in(monkeypatch, tmp_path):
    monkeypatch.setenv("MCP_KEY_DIR", str(tmp_path / "keys"))


def test_empty_command_is_refused():
    with pytest.raises(ValueError, match="no command"):
        build_spec("s1", "   ", {})


def test_executables_outside_the_allowlist_are_refused():
    with pytest.raises(ValueError, match="allowlist"):
        build_spec("s1", "bash -c evil", {})


def test_the_allowlist_env_extends_it(monkeypatch):
    _allow_python(monkeypatch)
    spec = build_spec("s1", f"{PYTHON} server.py", {})
    assert spec.command == PYTHON and spec.args == ["server.py"]


def test_default_allowlist_covers_the_catalog_and_ssh():
    for line in ("ssh user@host uvx mcp-shell-server",
                 "uvx mcp-server-git",
                 "npx -y @modelcontextprotocol/server-filesystem /data"):
        spec = build_spec("s1", line, {})
        assert spec.command == line.split()[0]


def test_secrets_become_child_env_only_and_the_key_never_does(monkeypatch, tmp_path):
    _keys_in(monkeypatch, tmp_path)
    spec = build_spec("s1", "ssh -i {SSH_KEY_FILE} user@host run",
                      {"TOKEN": "t1", SSH_KEY_SECRET: "KEYMATERIAL"})
    assert spec.env == {"TOKEN": "t1"}


def test_key_is_materialized_0600_and_substituted(monkeypatch, tmp_path):
    _keys_in(monkeypatch, tmp_path)
    spec = build_spec("server-9", "ssh -i {SSH_KEY_FILE} user@host run",
                      {SSH_KEY_SECRET: "-----BEGIN KEY-----abc"})
    key_arg = spec.args[spec.args.index("-i") + 1]
    path = Path(key_arg)
    assert KEY_FILE_PLACEHOLDER not in " ".join([spec.command, *spec.args])
    assert path.read_text() == "-----BEGIN KEY-----abc\n"  # the newline ssh demands
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


def test_a_rotated_key_rewrites_the_same_file(monkeypatch, tmp_path):
    _keys_in(monkeypatch, tmp_path)
    first = build_spec("s1", "ssh -i {SSH_KEY_FILE} u@h run", {SSH_KEY_SECRET: "old"})
    second = build_spec("s1", "ssh -i {SSH_KEY_FILE} u@h run", {SSH_KEY_SECRET: "new"})
    p1 = first.args[first.args.index("-i") + 1]
    p2 = second.args[second.args.index("-i") + 1]
    assert p1 == p2 and Path(p2).read_text() == "new\n"


def test_placeholder_without_a_stored_key_is_refused(monkeypatch, tmp_path):
    _keys_in(monkeypatch, tmp_path)
    with pytest.raises(ValueError, match="SSH_PRIVATE_KEY"):
        build_spec("s1", "ssh -i {SSH_KEY_FILE} u@h run", {})


# -- the refresh dial's stdio road, against a REAL spawned server ------------

@pytest.mark.asyncio
async def test_refresh_dial_spawns_and_lists_tools(monkeypatch):
    _allow_python(monkeypatch)
    from fastapi_app.routers.mcp_tools import ToolListRequest, list_mcp_tools
    resp = await list_mcp_tools(
        ToolListRequest(command=f"{sys.executable} {FAKE_MCP}", server_id="dial-1"),
        _="key")
    by_name = {t.name: t for t in resp.tools}
    assert set(by_name) == {"search", "create_issue", "env_probe"}
    assert by_name["search"].read_only is True        # annotation survives the pipe
    assert by_name["create_issue"].read_only is None  # unlabeled stays unknown


@pytest.mark.asyncio
async def test_refresh_dial_refuses_an_unlisted_executable():
    from fastapi import HTTPException

    from fastapi_app.routers.mcp_tools import ToolListRequest, list_mcp_tools
    with pytest.raises(HTTPException) as err:
        await list_mcp_tools(ToolListRequest(command="bash evil.sh"), _="key")
    assert err.value.status_code == 502 and "allowlist" in err.value.detail


@pytest.mark.asyncio
async def test_refresh_dial_requires_url_or_command():
    from fastapi import HTTPException

    from fastapi_app.routers.mcp_tools import ToolListRequest, list_mcp_tools
    with pytest.raises(HTTPException) as err:
        await list_mcp_tools(ToolListRequest(), _="key")
    assert err.value.status_code == 422
