"""
B7 (fix round 2026-10-28) — the honesty check for invented tool ATTEMPTS.

Found live 2026-10-27: after three real auth failures in one topic, a reply
twice wrote "Attempted now: aaf_analytics__get_schema → missing or invalid
bearer token" with no tool call behind it. Two defences ship together:
the prompt rule (prompts/layout.py — asserted here on the wire) and the
after-the-fact detector (core/honesty.py) that appends a visible correction.
The detector is deliberately narrow: a false flag on an honest reply would be
worse than a missed slip, so most tests here are about what it must NOT flag.
"""
from __future__ import annotations

import json

import pytest

from ai_engine.core.honesty import honesty_note, phantom_tool_claims

TOOLS = ["aaf_analytics__get_schema", "aaf_analytics__run_sql", "web_search"]


# ── the detector flags the observed fabrication ──────────────────────────────

def test_the_live_fabrication_is_flagged():
    text = ("I'll verify the connection.\n"
            "Attempted now: aaf_analytics__get_schema → missing or invalid bearer token\n"
            "So the credentials are still broken.")
    assert phantom_tool_claims(text, TOOLS, used_names=[]) == ["aaf_analytics__get_schema"]


def test_past_tense_claims_are_flagged_and_deduplicated_in_order():
    text = ("I ran aaf_analytics__run_sql and it failed.\n"
            "Then I tried web_search as well.\n"
            "I ran aaf_analytics__run_sql again.")
    assert phantom_tool_claims(text, TOOLS, used_names=[]) == [
        "aaf_analytics__run_sql", "web_search",
    ]


# ── what it must NOT flag ────────────────────────────────────────────────────

def test_a_tool_that_really_ran_is_never_flagged():
    text = "Attempted now: aaf_analytics__get_schema → 12 tables found."
    assert phantom_tool_claims(text, TOOLS, used_names=["aaf_analytics__get_schema"]) == []


def test_intent_and_offers_are_spared():
    for line in (
        "I can call aaf_analytics__run_sql if you want the exact numbers.",
        "I will run web_search for the latest figures.",
        "Next I am going to call aaf_analytics__get_schema.",
        "You could use web_search for this.",
    ):
        assert phantom_tool_claims(line, TOOLS, used_names=[]) == [], line


def test_remembered_work_and_honest_inability_are_spared():
    for line in (
        "Earlier we ran aaf_analytics__run_sql and it listed 48 churned users.",
        "In the previous reply aaf_analytics__get_schema failed with an auth error.",
        "I couldn't call web_search — it is not enabled for me this turn.",
        "web_search is unavailable here, so these figures are from memory.",
        "# not executed: aaf_analytics__run_sql (no approval given)",
    ):
        assert phantom_tool_claims(line, TOOLS, used_names=[]) == [], line


def test_a_plain_mention_without_a_claim_is_spared():
    text = "The schema lives behind aaf_analytics__get_schema; ask @Analyst to pull it."
    assert phantom_tool_claims(text, TOOLS, used_names=[]) == []


def test_empty_inputs_are_quiet():
    assert phantom_tool_claims("", TOOLS, used_names=[]) == []
    assert phantom_tool_claims("I ran everything.", [], used_names=[]) == []


# ── the correction wording ───────────────────────────────────────────────────

def test_the_note_names_the_tools_and_counts_them():
    one = honesty_note(["web_search"])
    assert "web_search" in one and "no such tool call happened" in one
    two = honesty_note(["a__x", "b__y"])
    assert "a__x, b__y" in two and "no such tool calls happened" in two


# ── end to end: the slip is corrected on the wire ────────────────────────────

@pytest.mark.asyncio
async def test_e2e_a_claimed_but_unrun_tool_gets_a_visible_correction(harness):
    from conftest import openai_model
    from fake_nucleus import make_persona

    persona = make_persona(openai_model(harness))
    persona["capabilities"] = [{"id": "cap1", "name": "defaults",
                                "capability_config": {"web_search": {"local": "duckduckgo"}}}]
    harness.nucleus.persona = persona
    harness.provider.script.text = "Attempted now: web_search → network refused. Nothing came back."
    events = await harness.trigger()
    done = [e for e in events if e["type"] == "message_done"]
    assert done, events
    content = done[0]["content"]
    # The fabricated claim is still there (never silently rewritten), with the
    # correction appended so no reader believes a run happened.
    assert "Attempted now: web_search" in content
    assert "Correction (added automatically)" in content
    assert "web_search" in content.rsplit("Correction", 1)[1]
    # The prompt rule rode along in the catalog section.
    body = harness.provider.requests[-1]
    assert "never say a tool was called, attempted or failed" in json.dumps(body["messages"])


@pytest.mark.asyncio
async def test_e2e_an_honest_reply_is_untouched(harness):
    from conftest import openai_model
    from fake_nucleus import make_persona

    persona = make_persona(openai_model(harness))
    persona["capabilities"] = [{"id": "cap1", "name": "defaults",
                                "capability_config": {"web_search": {"local": "duckduckgo"}}}]
    harness.nucleus.persona = persona
    harness.provider.script.text = "I can run web_search for that if you'd like — say the word."
    events = await harness.trigger()
    done = [e for e in events if e["type"] == "message_done"]
    assert done, events
    assert "Correction" not in done[0]["content"]
