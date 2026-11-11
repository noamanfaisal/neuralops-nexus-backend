"""
9b part 2 (owner, 2026-11-03: "the Vercel experience") — the per-server
repository allow-list, ENFORCED BY NEURALOPS: a GitHub-shaped tool call that
names a repo outside the server row's list is refused with a worded reason,
reads included, interactive or not — the fence that gives GitHub2 → repo-a,
GitHub3 → repo-b on the same account while the vendor app is still an OAuth
App (whose token reaches every repo the account can).
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from pydantic_ai.exceptions import SkipToolExecution

from ai_engine.pydantic_ai_system.tools.approval_gate import ApprovalGate
from ai_engine.pydantic_ai_system.tools.approval_policy import (
    ApprovalPolicy,
    ToolSource,
    named_repo,
)

def test_r1_named_repo_reads_every_common_spelling():
    """The repo a call names — owner+repo params (the GitHub MCP server's
    shape), or one repo/repository/repo_full_name holding "owner/name"; a
    call naming none (search tools) answers None; junk never raises."""
    assert named_repo({"owner": "mapax-io", "repo": "csv-mcp"}) == "mapax-io/csv-mcp"
    assert named_repo(json.dumps({"owner": "a", "repo": "b"})) == "a/b"
    assert named_repo({"repo": "mapax-io/csv-mcp"}) == "mapax-io/csv-mcp"
    assert named_repo({"repository": "a/b"}) == "a/b"
    assert named_repo({"repo_full_name": "a/b"}) == "a/b"
    assert named_repo({"query": "language:python stars:>100"}) is None
    assert named_repo({"owner": "a"}) is None          # half an identity
    assert named_repo({"repo": "a/b/c"}) is None       # not owner/name
    assert named_repo("not json {") is None
    assert named_repo(None) is None
    assert named_repo([1, 2]) is None


def _gate(allowed=("mapax-io/csv-mcp",), interactive=True):
    source = ToolSource(kind="mcp", cap_key="mcp:s1", source_id="s1",
                        slug="github", allowed_repos=tuple(allowed))
    return ApprovalGate(ApprovalPolicy(), {"prefixed-s1": source}, {},
                        interactive=interactive)


def _tool(name="github__get_file_contents"):
    return SimpleNamespace(name=name, capability_id="prefixed-s1", metadata=None)


@pytest.mark.asyncio
async def test_r2_a_call_outside_the_list_is_refused_with_the_reason():
    """The fence: an outside repo never runs — the refusal names the list and
    the repo, so the model says so instead of inventing output. Case folds
    (GitHub names are case-insensitive)."""
    gate = _gate()
    call = SimpleNamespace(tool_name="github__get_file_contents")
    with pytest.raises(SkipToolExecution) as exc:
        await gate.before_tool_execute(
            None, call=call, tool_def=_tool(),
            args={"owner": "mapax-io", "repo": "neuralops-nexus"})
    # SkipToolExecution carries the TOOL RESULT the model reads — .result
    assert "mapax-io/csv-mcp" in exc.value.result
    assert "mapax-io/neuralops-nexus" in exc.value.result
    assert "did not run" in exc.value.result

    # inside the list — runs, whatever the letter case
    out = await gate.before_tool_execute(
        None, call=call, tool_def=_tool(),
        args={"owner": "Mapax-IO", "repo": "CSV-MCP"})
    assert out == {"owner": "Mapax-IO", "repo": "CSV-MCP"}


@pytest.mark.asyncio
async def test_r3_no_repo_named_and_no_list_both_pass():
    """A search tool that names no repo runs under a fence; a server with an
    EMPTY list (every repo the token reaches — today's behaviour) is
    untouched; and the fence holds in unattended runs too (reads included),
    where its wording — not the approval wording — is the answer."""
    gate = _gate()
    call = SimpleNamespace(tool_name="github__search_repositories")
    out = await gate.before_tool_execute(
        None, call=call, tool_def=_tool("github__search_repositories"),
        args={"query": "csv"})
    assert out == {"query": "csv"}

    unfenced = _gate(allowed=())
    out = await unfenced.before_tool_execute(
        None, call=call, tool_def=_tool(),
        args={"owner": "anyone", "repo": "anything"})
    assert out["owner"] == "anyone"

    # unattended: the repo refusal wins over the "nobody can approve" text
    hands_off = _gate(interactive=False)
    with pytest.raises(SkipToolExecution) as exc:
        await hands_off.before_tool_execute(
            None, call=call, tool_def=_tool(),
            args=json.dumps({"owner": "x", "repo": "y"}))
    assert "repositories" in exc.value.result


@pytest.mark.asyncio
async def test_r4_the_list_rides_the_server_row_into_the_source():
    """ToolsetBuilder carries the row's allowed_repos onto the ToolSource,
    lowercased and deduped — an older nucleus that sends no field builds an
    unfenced source."""
    from ai_engine.core.specs import PersonaSpec, ToolCatalogEntry
    from ai_engine.pydantic_ai_system.tools.toolset_builder import ToolsetBuilder
    from ai_engine.core.specs import LoadedSet

    def persona(servers):
        return PersonaSpec(
            id="p1", name="P", company_id="c", project_id="pr",
            system_prompt="x", project_brief=None, output_type="text",
            context_scope=None, temperature=0.5, max_output_tokens=100,
            max_steps=5, models=(), advisor_model=None, utility_model=None,
            tool_levels={}, mcp_servers=tuple(servers), capabilities=())

    entry = ToolCatalogEntry(tool_id="mcp:s1/get_file_contents",
                             model_name="github__get_file_contents", one_line="",
                             source_kind="mcp", source_id="s1", read_only=True)
    row = {"id": "s1", "name": "GitHub", "url": "http://x/mcp",
           "allowed_repos": ["Mapax-IO/csv-mcp", "mapax-io/csv-mcp", "  "]}
    caps = ToolsetBuilder().build(
        LoadedSet(tool_ids=("mcp:s1/get_file_contents",), catalog_hash="h"), [entry],
        persona([row]))
    gate = next(c for c in caps if isinstance(c, ApprovalGate))
    source = gate._sources["prefixed-s1"]
    assert source.allowed_repos == ("mapax-io/csv-mcp",)

    row_old = {"id": "s1", "name": "GitHub", "url": "http://x/mcp"}
    caps = ToolsetBuilder().build(
        LoadedSet(tool_ids=("mcp:s1/get_file_contents",), catalog_hash="h"), [entry],
        persona([row_old]))
    gate = next(c for c in caps if isinstance(c, ApprovalGate))
    assert gate._sources["prefixed-s1"].allowed_repos == ()
