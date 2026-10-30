"""
1.3.0 — the AI audit log (owner's ask, 2026-10-29: "i want to know in log …
how every prompt is building, vector db + system prompt + context + file").

Through the running service: every model RUN of a reply POSTs one record to
nucleus's /internal/ai-request-logs/ carrying the prompt ANATOMY — the
sections instructions= was built from (system prompt, project brief, tool
catalog, …), the extra instructions (router bench / hand-over note), the
history count, the user message — plus the outcome (status, response, error,
tokens, latency) and the topic/project scope the viewer filters by.
"""
from __future__ import annotations

import pytest

from conftest import openai_model
from fake_nucleus import make_model, make_persona

pytestmark = pytest.mark.asyncio


def _section_kinds(post: dict) -> list[str]:
    return [s["kind"] for s in post["breakdown"]["sections"]]


async def test_audit_plain_reply_records_the_prompt_anatomy(harness, tmp_path):
    """1.3.0 — one audit record per plain reply, carrying the full anatomy.
    A persona with tools answers in text → exactly one POST lands on
    /ai-request-logs/: scoped (msg/topic/project), seat STANDARD, status done,
    the model named; breakdown.sections holds the persona prompt (full text)
    and the tool catalog, breakdown.message is the user's message, and the
    response is the reply's text."""
    harness.nucleus.persona = make_persona(
        openai_model(harness),
        capabilities=[{"id": "cap1", "name": "defaults",
                       "capability_config": {"filesystem": {"root_dir": str(tmp_path)}}}],
    )
    harness.provider.script.steps = [{"kind": "text", "text": "Tokyo is UTC+9."}]
    events = await harness.trigger()
    assert events[-1]["type"] == "message_done"

    [post] = harness.nucleus.audit_posts
    assert post["msg_id"] == "msg-1"
    assert post["topic_id"] == "t1" and post["project_id"] == "pr1"
    assert post["role"] == "STANDARD" and post["status"] == "done"
    assert post["provider"] == "openai" and post["model_name"] == "Fake openai"
    assert "UTC+9" in post["response"]
    assert post["error"] is None

    kinds = _section_kinds(post)
    assert "persona_prompt" in kinds and "tool_catalog" in kinds
    [prompt_section] = [s for s in post["breakdown"]["sections"] if s["kind"] == "persona_prompt"]
    assert "PERSONA-PROMPT-MARKER" in prompt_section["text"]
    assert prompt_section["chars"] == len(prompt_section["text"])
    assert post["breakdown"]["message"] == "current question"
    assert post["breakdown"]["history_count"] == 0
    assert post["breakdown"]["resume"] is False
    assert post["breakdown"]["fallback_attempt"] == 0


async def test_audit_escalation_writes_router_and_deep_rows(harness):
    """1.3.0 — a hand-over is TWO runs, so two audit records that say so.
    Router escalates → deep answers: the first record is seat ROUTER with
    status escalated and the router bench in extra_instructions; the second is
    seat DEEP with status done, the hand-over note in ITS extra_instructions,
    and the deep answer as its response. Both carry the same msg/topic."""
    harness.nucleus.persona = make_persona(
        openai_model(harness),
        router_model=openai_model(harness, config_id="m-router", model_id="fake-router"),
        deep_model=openai_model(harness, config_id="m-deep", model_id="fake-deep"),
    )
    harness.provider.script.steps = [
        {"kind": "tool_call", "call_id": "call_esc", "name": "final_result",
         "args": {"task": "do the deep work", "summary": "hard one",
                  "expected_output": "a full answer", "tool_hints": []}},
        {"kind": "text", "text": "Deep answer with full reasoning."},
    ]
    events = await harness.trigger()
    assert events[-1]["type"] == "message_done"

    router, deep = harness.nucleus.audit_posts
    assert router["role"] == "ROUTER" and router["status"] == "escalated"
    assert router["model_id"] == "fake-router"
    assert router["breakdown"]["extra_instructions"]  # the bench rode along
    assert deep["role"] == "DEEP" and deep["status"] == "done"
    assert deep["model_id"] == "fake-deep"
    assert "do the deep work" in deep["breakdown"]["extra_instructions"]  # the hand-over note
    assert "Deep answer" in deep["response"]
    assert router["topic_id"] == deep["topic_id"] == "t1"
    assert router["msg_id"] == deep["msg_id"] == "msg-1"


async def test_audit_failed_run_still_lands_with_status_failed(harness):
    """1.3.0 — a run that errors still writes its audit record.
    The persona's only model points at a dead endpoint → the reply ends in
    message_error, and ONE audit record lands with status failed, a non-empty
    error, an empty response — the anatomy (sections, message) intact, so the
    log answers "what was sent" even when nothing came back."""
    harness.nucleus.persona = make_persona(
        make_model("openai", "http://127.0.0.1:9/v1"))
    events = await harness.trigger()
    assert events[-1]["type"] == "message_error"

    [post] = harness.nucleus.audit_posts
    assert post["status"] == "failed"
    assert post["error"]
    assert post["response"] == ""
    assert "persona_prompt" in _section_kinds(post)
    assert post["breakdown"]["message"] == "current question"
