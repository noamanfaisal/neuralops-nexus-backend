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


async def test_audit_tells_the_complete_story_of_a_tool_run(harness, tmp_path):
    """Owner's ruling 2026-10-31 — the log is a COMPLETE diagnostic story.
    One history message, a read_file call, then the answer: the record now
    also carries (1) the TRIMMING story — window, reply cap, target and every
    ingredient with its token estimate and kept/dropped; (2) the history TEXT
    as sent; (3) the exact final instructions string; (4) the TOOL LOOP turn
    by turn — the call with its args, the tool's real result, the model's
    final text; (5) how many model calls the run made."""
    (tmp_path / "data.txt").write_text("STORY-FILE-CONTENT-77")
    harness.nucleus.persona = make_persona(
        openai_model(harness),
        capabilities=[{"id": "cap1", "name": "defaults",
                       "capability_config": {"filesystem": {"root_dir": str(tmp_path)}}}],
    )
    harness.nucleus.history = [{
        "id": "h1", "sender_type": "human", "sender_name": "Noaman",
        "content": "EARLIER-HISTORY-LINE", "render_as": "text", "output_type": "text",
        "stopped": False, "sequence": 1, "status": "COMPLETED",
    }]
    harness.provider.script.steps = [
        {"kind": "tool_call", "call_id": "call_s1", "name": "read_file", "args": {"path": "data.txt"}},
        {"kind": "text", "text": "The file holds STORY-FILE-CONTENT-77."},
    ]
    events = await harness.trigger()
    assert events[-1]["type"] == "message_done"

    post = next(p for p in harness.nucleus.audit_posts if p["role"] == "STANDARD")
    b = post["breakdown"]
    # (1) the trimming story
    trim = b["trim"]
    assert trim["context_window"] > 0 and trim["reply_cap"] > 0 and trim["target"] > 0
    whats = [i["what"] for i in trim["items"]]
    assert "section: persona_prompt" in whats and "the current message" in whats
    assert any(w.startswith("history #1") for w in whats)
    assert all("tokens" in i and "kept" in i for i in trim["items"])
    # (2) history as sent
    assert [h["text"] for h in b["history"]] == ["EARLIER-HISTORY-LINE"]
    # (3) the exact final instructions
    assert "PERSONA-PROMPT-MARKER" in b["final_instructions"]
    # (4) the tool loop, in order
    steps = [(t["step"], t.get("tool")) for t in b["transcript"]]
    assert ("tool_call", "read_file") in steps and ("tool_result", "read_file") in steps
    assert steps.index(("tool_call", "read_file")) < steps.index(("tool_result", "read_file"))
    [result] = [t for t in b["transcript"] if t["step"] == "tool_result"]
    assert "STORY-FILE-CONTENT-77" in result["content"]
    [call] = [t for t in b["transcript"] if t["step"] == "tool_call"]
    assert "data.txt" in call["args"]
    assert b["transcript"][-1]["step"] == "model_text"
    # (5) the run made two model calls (tool turn + answer)
    assert b["model_calls"] == 2
    # (7) the memory step's chapter lands as its OWN entry on the same message
    # (fire-and-forget after message_done — wait for it, so it can't leak
    # into the next test's records)
    import asyncio
    for _ in range(50):
        memory = [p for p in harness.nucleus.audit_posts if p["role"] == "memory"]
        if memory:
            break
        await asyncio.sleep(0.1)
    [memory] = memory
    assert memory["msg_id"] == "msg-1" and memory["topic_id"] == "t1"
    assert "memory_pass" in memory["breakdown"]


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

    [post] = [p for p in harness.nucleus.audit_posts if p["role"] != "memory"]
    assert post["status"] == "failed"
    assert post["error"]
    assert post["response"] == ""
    assert "persona_prompt" in _section_kinds(post)
    assert post["breakdown"]["message"] == "current question"
