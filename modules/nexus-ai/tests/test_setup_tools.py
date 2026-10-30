"""
Setup-copilot — the gateway's admin tools mounted INSIDE for personas
(docs/MISSING.md setup-copilot entry: the InternalActor door, rights as the
asking person, writes still gated by approvals, keys never through chat).
"""
from __future__ import annotations

import inspect
import json

import pytest

from ai_engine.pydantic_ai_system.tools.setup_tools import setup_toolset
from conftest import openai_model
from fake_nucleus import make_persona

pytestmark = pytest.mark.asyncio

EXPECTED_TOOLS = {
    "list_models", "create_model", "update_model",
    "list_personas", "create_persona", "update_persona",
    "list_users", "get_topic_messages", "create_topic", "update_topic",
}


def _setup_persona(harness) -> dict:
    return make_persona(
        openai_model(harness),
        capabilities=[{"id": "cap-setup", "name": "Server setup",
                       "capability_config": {"setup": {}}}],
    )


async def test_st1_a_read_tool_reaches_the_gateway_as_the_asking_person(harness):
    """Setup inside — list_models flows to nucleus's gateway AS the person.
    A persona whose capability row carries the `setup` key gets the tools; a
    list call runs silently (no approval), the fake gateway records the
    InternalActor headers — X-NeuralOps-User is the job's user_id, the
    internal key rides — and the gateway's answer returns as the tool result."""
    harness.nucleus.persona = _setup_persona(harness)
    harness.nucleus.mcp_results["list_models"] = {
        "content": [{"type": "text", "text": '[{"name": "House GPT", "has_api_key": true}]'}],
        "isError": False,
    }
    harness.provider.script.steps = [
        {"kind": "tool_call", "call_id": "call_st1", "name": "list_models", "args": {}},
        {"kind": "text", "text": "You have one model."},
    ]
    events = await harness.trigger(harness.job(topic_tools=["setup"]))
    types = [e["type"] for e in events]
    assert "approval_requested" not in types and types[-1] == "message_done"

    [call] = harness.nucleus.mcp_calls
    assert call["method"] == "tools/call" and call["name"] == "list_models"
    assert call["user"] == "u1"                       # the job's user_id, verbatim
    assert call["internal_key"] == "test-internal-key"
    # the gateway's text reached the model as the tool result
    body = harness.provider.requests[-1]
    tool_msgs = [m for m in body["messages"] if m.get("role") == "tool"]
    assert any("House GPT" in m["content"] for m in tool_msgs)
    # and the catalog offered the whole set under their bare names
    first = harness.provider.requests[0]
    names = {t["function"]["name"] for t in first.get("tools", [])}
    assert EXPECTED_TOOLS <= names


async def test_st2_a_write_tool_pauses_for_approval_first(harness):
    """Setup inside — a WRITE (create_persona) pauses on the approval card.
    ACTING_NATIVE_TOOLS["setup"] marks the six writes: the run pauses with
    approval_requested (tool name + args preview) and message_paused, and the
    gateway is NEVER called — nothing changed before a person says yes."""
    harness.nucleus.persona = _setup_persona(harness)
    harness.provider.script.steps = [
        {"kind": "tool_call", "call_id": "call_st2", "name": "create_persona",
         "args": {"project_id": "pr1", "name": "Scout",
                  "system_prompt": "You are Scout.", "model_config_id": "m1"}},
    ]
    events = await harness.trigger(harness.job(topic_tools=["setup"]))
    types = [e["type"] for e in events]
    assert types[-1] == "message_paused"
    [req] = [e for e in events if e["type"] == "approval_requested"]
    assert req["approval"]["tool"] == "create_persona"
    assert "Scout" in req["approval"]["args_preview"]
    assert harness.nucleus.mcp_calls == []            # nothing ran


async def test_st3_an_unattended_run_refuses_the_write_in_words(harness):
    """Setup inside — a schedule's run refuses a write instead of pausing.
    interactive=false (nobody can answer a card): the model hears the worded
    'needs a person's approval' refusal, the gateway is never called, and the
    reply still completes."""
    harness.nucleus.persona = _setup_persona(harness)
    harness.provider.script.steps = [
        {"kind": "tool_call", "call_id": "call_st3", "name": "update_topic",
         "args": {"topic_id": "t1", "archive": True}},
        {"kind": "text", "text": "I could not archive it without someone to approve."},
    ]
    events = await harness.trigger(harness.job(topic_tools=["setup"], interactive=False))
    types = [e["type"] for e in events]
    assert "approval_requested" not in types and types[-1] == "message_done"
    assert harness.nucleus.mcp_calls == []
    body = harness.provider.requests[-1]
    tool_msgs = [m for m in body["messages"] if m.get("role") == "tool"]
    assert any("needs a person's approval" in m["content"] for m in tool_msgs)


async def test_st4_no_api_key_parameter_exists_inside():
    """Setup inside — the key rule holds BY SHAPE: no tool takes an api_key.
    The inside copies of create_model/update_model have no api_key parameter
    at all (keys never travel through chat — free-LLM hard rule), and the
    toolset is exactly the owner's ten tools."""
    ts = setup_toolset("http://nucleus.test", "key", "u1")
    assert set(ts.tools) == EXPECTED_TOOLS
    for name, tool in ts.tools.items():
        fn = getattr(tool, "function", None) or getattr(tool, "func", None)
        assert fn is not None, f"{name}: no function attribute on {type(tool)}"
        assert "api_key" not in inspect.signature(fn).parameters, name


async def test_st6_the_key_card_secret_rides_resume_metadata_to_the_gateway(harness):
    """WP3 — the key typed on the CARD reaches the gateway; the chat never sees it.
    create_model pauses like every setup write; the resume's approval carries
    secret=sk-card-secret (ApprovalDecisionIn.secret → DeferredToolResults.
    metadata → ctx.tool_call_metadata): the forwarded gateway call gains
    api_key, the reply finishes, and the secret appears in NO provider
    request — not in the history, not in any tool args the model sees."""
    harness.nucleus.persona = _setup_persona(harness)
    harness.nucleus.mcp_results["create_model"] = {
        "content": [{"type": "text", "text": '{"name": "Groq Llama", "has_api_key": true, "checked": true}'}],
        "isError": False,
    }
    harness.provider.script.steps = [
        {"kind": "tool_call", "call_id": "call_st6", "name": "create_model",
         "args": {"name": "Groq Llama", "provider": "openai_compatible",
                  "model_id": "llama-3.3-70b-versatile",
                  "api_base": "https://api.groq.com/openai/v1",
                  "accept_provider_terms": True}},
        {"kind": "text", "text": "Registered Groq Llama."},
    ]
    events = await harness.trigger(harness.job(topic_tools=["setup"]))
    assert [e["type"] for e in events][-1] == "message_paused"
    [pause] = harness.nucleus.pause_posts
    assert harness.nucleus.mcp_calls == []     # held — nothing ran before the card

    job = harness.job(topic_tools=["setup"],
                      resume={"state": pause["state"],
                              "approvals": {"call_st6": {"decision": "allow",
                                                         "secret": "sk-card-secret"}}})
    events = await harness.trigger(job)
    assert [e["type"] for e in events][-1] == "message_done"
    [call] = harness.nucleus.mcp_calls
    assert call["name"] == "create_model" and call["user"] == "u1"
    assert call["arguments"]["api_key"] == "sk-card-secret"   # the gateway got it
    assert call["arguments"]["accept_provider_terms"] is True
    # … and the model never saw it: no provider request carries the secret
    for body in harness.provider.requests:
        assert "sk-card-secret" not in json.dumps(body)


async def test_st5_a_gateway_refusal_returns_as_honest_text(harness):
    """Setup inside — a rights refusal comes back as plain words, not an error.
    The gateway refuses (isError, e.g. a Member without model rights): the
    model's tool result says 'refused … Nothing changed.' and the reply still
    completes — told only 'error', a model invents outcomes."""
    harness.nucleus.persona = _setup_persona(harness)
    harness.nucleus.mcp_results["list_users"] = {
        "content": [{"type": "text", "text": "You don't have permission to list members."}],
        "isError": True,
    }
    harness.provider.script.steps = [
        {"kind": "tool_call", "call_id": "call_st5", "name": "list_users", "args": {}},
        {"kind": "text", "text": "I can't list the members for you."},
    ]
    events = await harness.trigger(harness.job(topic_tools=["setup"]))
    assert [e["type"] for e in events][-1] == "message_done"
    body = harness.provider.requests[-1]
    tool_msgs = [m for m in body["messages"] if m.get("role") == "tool"]
    assert any("list_users refused" in m["content"] and "Nothing changed" in m["content"]
               for m in tool_msgs)
