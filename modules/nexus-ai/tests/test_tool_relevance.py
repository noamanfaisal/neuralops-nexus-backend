"""
Tool relevance (owner, 2026-11-01) — which tools fit the message.

Found live: a GitHub persona's first reply loaded the first 12 tools in
catalog order (add_comment…, create_branch, delete_file…) and hid
list_commits, so "show the last 5 commits" got "I have no tool for that";
the next turn (the set held per topic) failed the same way because the model
never searched. Two fixes inside narrow-once-and-hold: the first reply loads
the best matches, and a later turn's prompt names hidden matches.
"""
from __future__ import annotations

import json

import pytest

from ai_engine.core.specs import ToolCatalogEntry
from ai_engine.pydantic_ai_system.tools import relevance
from conftest import openai_model
from fake_mcp import make_mcp_app
from fake_nucleus import make_persona
from fake_provider import ServedApp

pytestmark = pytest.mark.asyncio

# GitHub's own first tools, alphabetical — the order that went wrong live.
GITHUB = [
    ("add_comment_to_pending_review", "Add review comment to the requester's latest pending pull request review.", False),
    ("add_issue_comment", "Add a comment to a specific issue in a GitHub repository.", False),
    ("create_branch", "Create a new branch in a GitHub repository.", False),
    ("create_or_update_file", "Create or update a single file in a GitHub repository.", False),
    ("create_pull_request", "Create a new pull request in a GitHub repository.", False),
    ("delete_file", "Delete a file from a GitHub repository.", False),
    ("fork_repository", "Fork a GitHub repository to your account or organization.", False),
    ("get_commit", "Get details for a commit from a GitHub repository.", True),
    ("get_file_contents", "Get the contents of a file or directory from a GitHub repository.", True),
    ("list_commits", "Get list of commits of a branch in a GitHub repository.", True),
    ("list_issues", "List issues in a GitHub repository.", True),
    ("search_repositories", "Find GitHub repositories by name, description, readme, topics or other metadata.", True),
]


def _catalog(natives: tuple[str, ...] = ("web_search",)) -> list[ToolCatalogEntry]:
    out = [ToolCatalogEntry(tool_id=n, model_name=n, source_id=n, source_kind="native",
                            one_line="Search the web", read_only=True) for n in natives]
    out += [ToolCatalogEntry(tool_id=f"mcp:gh/{name}", model_name=f"github__{name}", source_id="gh",
                             source_kind="mcp", one_line=line, read_only=ro)
            for name, line, ro in GITHUB]
    return out


def test_tr1_singular_and_plural_meet():
    """The stemmer maps the forms people type to the forms tools are named."""
    assert relevance.words("commits") == relevance.words("commit") == {"commit"}
    assert relevance.words("issues") == relevance.words("issue")
    assert relevance.words("repositories") == relevance.words("repository")
    assert relevance.words("branches") == relevance.words("branch")
    assert "github" in relevance.words("github__list_commits")


def test_tr2_the_first_reply_loads_what_the_message_asks_for():
    """The live case: with a cap of 6, "show the last 5 commits" loads
    list_commits and get_commit (natives stay in front), not the alphabetical
    write tools; a message nothing matches keeps catalog order exactly."""
    catalog = _catalog()
    loaded = relevance.first_reply_set(catalog, "show the last 5 commits in mapax-io/neuralops-oauth-relay", 6)
    assert loaded[0] == "web_search"
    assert "mcp:gh/list_commits" in loaded and "mcp:gh/get_commit" in loaded
    assert loaded.index("mcp:gh/list_commits") < loaded.index("mcp:gh/add_issue_comment") \
        if "mcp:gh/add_issue_comment" in loaded else True
    repos = relevance.first_reply_set(catalog, "list my GitHub repositories", 4)
    assert "mcp:gh/search_repositories" in repos
    plain = relevance.first_reply_set(catalog, "hello there", 5)
    assert plain == tuple(e.tool_id for e in catalog[:5])


def test_tr3_reads_win_a_tie():
    """Equal scores: the read-only tool ranks first (the safer one to load)."""
    catalog = [
        ToolCatalogEntry(tool_id="w", model_name="gh__update_issue", source_id="gh", source_kind="mcp",
                         one_line="Update an issue", read_only=False),
        ToolCatalogEntry(tool_id="r", model_name="gh__get_issue", source_id="gh", source_kind="mcp",
                         one_line="Get an issue", read_only=True),
    ]
    assert [e.tool_id for _, e in relevance.ranked(catalog, "the issue")] == ["r", "w"]


def test_tr4_hidden_matches_need_a_name_hit_and_skip_loaded_ones():
    """Only tools whose NAME fits are named (a stray description word never
    is), loaded ones are skipped, natives are never hinted."""
    catalog = _catalog()
    loaded = ("web_search", "mcp:gh/get_commit")
    hidden = relevance.hidden_matches(catalog, loaded, "show the last 5 commits")
    assert [e.model_name for e in hidden] == ["github__list_commits"]
    assert relevance.hidden_matches(catalog, loaded, "what is the weather") == []
    text = relevance.hint_text(hidden)
    assert "github__list_commits" in text and "search_tools" in text


@pytest.fixture(scope="module")
def mcp_server():
    served = ServedApp(make_mcp_app()).start()
    yield served
    served.stop()


def _persona(harness, mcp_server):
    row = {
        "id": "s1", "name": "GitHub", "server_type": "custom", "transport": "http",
        "url": mcp_server.url + "/mcp", "command": None, "config": {}, "secrets": {},
        "is_first_party": False, "embed_output": False, "needs_reauth": False,
        "auth_type": "static_secrets", "token_env_var": "OAUTH_ACCESS_TOKEN",
        # the fake server serves search + create_issue; the stored list is
        # what the catalog (and so the matching) sees
        "tools": [{"name": "create_issue", "description": "Open an issue", "read_only": False},
                  {"name": "search", "description": "Search code in the repository", "read_only": True}],
    }
    return make_persona(openai_model(harness), mcp_servers=[row])


async def test_tr5_a_first_reply_loads_the_matching_tool_end_to_end(harness, mcp_server):
    """Through the running service with a cap of 1: "search the code for the
    auth bug" loads github__search (the match), not create_issue (first in
    catalog order) — its schema rides the very first provider request."""
    import os
    os.environ["MAX_LOADED_TOOLS"] = "1"
    try:
        harness.nucleus.persona = _persona(harness, mcp_server)
        harness.provider.script.text = "Searching."
        await harness.trigger(harness.job(message="search the code for the auth bug"))
    finally:
        del os.environ["MAX_LOADED_TOOLS"]
    names = [t["function"]["name"] for t in harness.provider.requests[0].get("tools", [])]
    assert "github__search" in names and "github__create_issue" not in names


async def test_tr6_a_held_set_gets_a_hint_for_the_hidden_match(harness, mcp_server):
    """A later turn (topic set held without the search tool): the tool list is
    NOT changed, but the prompt names github__search and says to load it with
    search_tools; a turn whose match is already loaded carries no hint."""
    harness.nucleus.persona = _persona(harness, mcp_server)
    harness.provider.script.text = "Ok."
    await harness.trigger(harness.job(message="search the code for the auth bug",
                                      topic_tools=["mcp:s1/create_issue"]))
    body = harness.provider.requests[-1]
    sent = json.dumps(body)
    assert "not loaded yet: github__search" in sent
    names = [t["function"]["name"] for t in body.get("tools", [])]
    assert "github__search" not in names            # still hidden: the list is untouched
    await harness.trigger(harness.job(message="search the code for the auth bug",
                                      topic_tools=["mcp:s1/create_issue", "mcp:s1/search"]))
    assert "not loaded yet" not in json.dumps(harness.provider.requests[-1])
