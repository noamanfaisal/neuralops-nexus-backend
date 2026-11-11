"""
Project console v1 (docs/MISSING.md "project console") — the data bus.

POST /api/v1/console/run takes ONE typed line, dials the named project MCP
server, and answers the result — no model, no tokens, no approval gate (the
human is the caller; nucleus holds both gates and the audit). These tests
drive the REAL fake MCP server over streamable HTTP, exactly the transport
project rows use, plus the grammar and the project-folder sandbox.
"""
from __future__ import annotations

import json

import httpx
import pytest

from conftest import INTERNAL_KEY
from fake_mcp import make_mcp_app
from fake_provider import ServedApp

async def _run(harness, payload, key=INTERNAL_KEY):
    async with httpx.AsyncClient(timeout=60.0) as client:
        return await client.post(f"{harness.app_url}/api/v1/console/run", json=payload,
                                 headers={"X-Internal-Key": key} if key else {})


@pytest.fixture()
def fake_server():
    served = ServedApp(make_mcp_app()).start()
    yield served
    served.stop()


def _rows(served):
    return [{"name": "fake", "url": served.url + "/mcp"}]


# ------------------------------------------------------------- the grammar

def test_c1_the_grammar_parses_every_line_shape_and_refuses_the_rest():
    """The console grammar — calls, '>', '@', '_', one nesting level.
    JSON strings may contain ')' and '>' without confusing the scanner; a
    second nesting level, trailing junk, non-object args and unbalanced
    parens are parse errors the CLI shows verbatim."""
    from fastapi_app.routers.console import ConsoleParseError, parse_line

    line = parse_line('github.search({"query": "fix(scope) > main"})')
    assert (line.call.server, line.call.tool) == ("github", "search")
    assert line.call.args_json == {"query": "fix(scope) > main"}
    assert line.save_to is None

    assert parse_line("fs.list_dir()").call.args_json == {}

    line = parse_line('github.search({"q": "x"}) > /issues/open.json')
    assert line.save_to == "/issues/open.json"

    line = parse_line("vercel.deploy(@/payloads/deploy.json)")
    assert line.call.args_file == "/payloads/deploy.json"

    assert parse_line("graph.ingest(_)").call.args_last is True

    line = parse_line('graph.ingest(github.search({"q": "y"}))')
    assert line.call.inner and line.call.inner.server == "github"
    assert line.call.inner.args_json == {"q": "y"}

    for bad in ('a.b(c.d(e.f({"x": 1})))',       # two nesting levels
                'a.b({"x": 1}) trailing',         # junk after the call
                'a.b({"x": 1}',                   # unbalanced
                'a.b([1, 2])',                    # args must be an object
                'a.b({"x": 1}) >',                # '>' without a path
                "just words"):
        with pytest.raises(ConsoleParseError):
            parse_line(bad)


def test_c2_paths_are_pinned_inside_the_project_folder(tmp_path):
    """The sandbox — '/x.json' means <project>/x.json; '..' escapes are
    refused however they are spelled."""
    from fastapi_app.routers.console import ConsoleParseError, resolve_project_path

    inside = resolve_project_path(str(tmp_path), "/reports/out.json")
    assert inside == tmp_path.resolve() / "reports" / "out.json"
    assert resolve_project_path(str(tmp_path), "plain.json").name == "plain.json"

    for evil in ("/../evil.json", "../evil.json", "/a/../../evil.json"):
        with pytest.raises(ConsoleParseError):
            resolve_project_path(str(tmp_path), evil)


# ------------------------------------------------------- against a real MCP

@pytest.mark.asyncio
async def test_c3_a_line_dials_the_real_server_and_answers_the_result(harness, fake_server):
    """The happy line — fake.search({...}) dials the REAL fake MCP server
    over streamable HTTP and answers the tool's result; no key is a 401, an
    unknown server names the rows the project actually has (422)."""
    response = await _run(harness, {"line": 'fake.search({"query": "ping"})',
                                    "servers": _rows(fake_server)})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True
    assert (body["server"], body["tool"]) == ("fake", "search")
    assert "MCP-RESULT: ping" in json.dumps(body["result"]) + (body["text"] or "")

    response = await _run(harness, {"line": "fake.search({})"}, key=None)
    assert response.status_code == 401

    response = await _run(harness, {"line": "nope.search({})",
                                    "servers": _rows(fake_server)})
    assert response.status_code == 422
    assert "fake" in response.json()["detail"]


@pytest.mark.asyncio
async def test_c4_save_and_load_round_trip_through_the_project_folder(
        harness, fake_server, tmp_path):
    """'>' writes the full result into the project folder; '@' feeds a saved
    file back in as args — the whole point of the data bus. An escaping save
    path is refused BEFORE any dial (422)."""
    response = await _run(harness, {
        "line": 'fake.search({"query": "kept"}) > /out/search.json',
        "servers": _rows(fake_server), "workspace_root": str(tmp_path)})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] and body["saved_to"] == "/out/search.json"
    saved = json.loads((tmp_path / "out" / "search.json").read_text())
    assert "kept" in json.dumps(saved)

    (tmp_path / "args.json").write_text(json.dumps({"query": "loaded"}))
    response = await _run(harness, {"line": "fake.search(@/args.json)",
                                    "servers": _rows(fake_server),
                                    "workspace_root": str(tmp_path)})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] and "MCP-RESULT: loaded" in json.dumps(body["result"]) + (body["text"] or "")

    response = await _run(harness, {"line": 'fake.search({"query": "x"}) > /../evil.json',
                                    "servers": _rows(fake_server),
                                    "workspace_root": str(tmp_path)})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_c5_nesting_and_the_last_result_buffer(harness, fake_server):
    """One nesting level live — make_payload's dict result becomes search's
    args; '_' replays the CLI's last result as args; '_' with nothing to
    replay is a 422."""
    response = await _run(harness, {
        "line": 'fake.search(fake.make_payload({"title": "abc"}))',
        "servers": _rows(fake_server)})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"], body
    assert "MCP-RESULT: made:abc" in json.dumps(body["result"]) + (body["text"] or "")

    response = await _run(harness, {"line": "fake.search(_)",
                                    "servers": _rows(fake_server),
                                    "last_result": {"query": "from-last"}})
    body = response.json()
    assert body["ok"] and "MCP-RESULT: from-last" in json.dumps(body["result"]) + (body["text"] or "")

    response = await _run(harness, {"line": "fake.search(_)",
                                    "servers": _rows(fake_server)})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_c5b_the_stdio_road_spawns_and_secrets_reach_the_child(monkeypatch):
    """The console's first real user is the SSH/stdio road — a row with a
    command SPAWNS it through the same spawn spec as the toolset builder,
    and the row's secrets arrive as CHILD env (env_probe answers them).
    Called in-process so the allowlist monkeypatch holds."""
    import sys
    from pathlib import Path

    from fastapi_app.routers.console import ConsoleRunRequest, ConsoleServer, console_run

    monkeypatch.setenv("MCP_STDIO_ALLOWED_COMMANDS",
                       f"ssh,npx,uvx,{Path(sys.executable).name}")
    fake_path = Path(__file__).with_name("fake_mcp.py")
    req = ConsoleRunRequest(
        line="node.env_probe()",
        servers=[ConsoleServer(name="node", command=f"{sys.executable} {fake_path}",
                               env={"FAKE_SECRET": "sealed"}, server_id="console-1")])
    body = await console_run(req, _="key")
    assert body.ok, body.error
    assert "env=sealed" in json.dumps(body.result) + (body.text or "")


@pytest.mark.asyncio
async def test_c6_tool_failures_are_repl_results_not_transport_faults(harness, fake_server):
    """A tool-level failure (bad args) answers 200 ok=false with the reason —
    in a REPL that's a printable result; so is a dead server (nothing
    listening on the url)."""
    response = await _run(harness, {"line": 'fake.search({"wrong_arg": 1})',
                                    "servers": _rows(fake_server)})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is False and body["error"]

    response = await _run(harness, {
        "line": 'dead.search({"query": "x"})',
        "servers": [{"name": "dead", "url": "http://127.0.0.1:9/mcp"}]})
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False and body["error"]
