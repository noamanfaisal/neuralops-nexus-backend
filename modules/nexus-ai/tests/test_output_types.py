"""
Layer 4, item 23 — output types and rendering
(docs/NEXUS-AI-REVAMP.md Layer 4 decision 2 + verification notes; ported from
0.8.0's apps/output_types, all six files read; built 2026-10-13).

Resolution: explicit non-auto wins → classifier → text. The chosen type's
contract rides as a prompt section; the finished reply is parsed, recovered
when unmarked, VALIDATED (a broken claim falls back to text), and message_done
carries clean content + output_type + render_as + embed_description.
"""
from __future__ import annotations

import json

import pytest

from ai_engine.output_types.markers import parse_output_markers
from ai_engine.output_types.recovery import finalise_reply

pytestmark = pytest.mark.asyncio

CHART = json.dumps({"type": "bar", "title": "Sales", "labels": ["Q1"],
                    "datasets": [{"label": "sales", "data": [1]}],
                    "source": "test", "basis": "provided"})


def _by_type(events, kind):
    return [e for e in events if e["type"] == kind]


# ── unit: markers and recovery ────────────────────────────────────────────────

def test_ot1_markers_parse_and_tolerate_mangling():
    """Item 23 — markers name the type; a mangled closer never loses the block.
    A marked chart parses to (clean JSON, 'chart'); the EMBED block becomes the
    embed description and leaves the content; a reply whose closer is missing
    entirely still parses (0.8.0: a live reply lost its chart over one '>')."""
    raw = f"<<<EMBED>>>\nQ1 sales chart.\n<<<END_EMBED>>>\n<<<OUTPUT:chart>>>\n{CHART}\n<<<END_OUTPUT>>>"
    clean, kind, embed = parse_output_markers(raw)
    assert kind == "chart" and clean == CHART and embed == "Q1 sales chart."
    clean, kind, _ = parse_output_markers(f"<<<OUTPUT:chart>>>\n{CHART}")  # no closer
    assert kind == "chart" and clean == CHART
    clean, kind, _ = parse_output_markers("just words, no markers")
    assert kind == "text" and clean == "just words, no markers"


def test_ot10_a_glued_opener_after_a_sentence_still_counts():
    """Found live 2026-10-27 (docs/MISSING.md): the model wrote a sentence,
    called a tool, then opened the marker — and the pieces arrived joined with
    no line break, so the opener sat mid-line and the whole reply rendered as
    raw text (the markdown renderer even autolinked `<OUTPUT:chart>`). An
    opener straight after sentence punctuation now counts for EVERY type; a
    marker merely mentioned mid-sentence stays prose."""
    glued = f"I'll pull the revenue report by month.<<<OUTPUT:chart>>>\n{CHART}\n<<<END_OUTPUT>>>"
    clean, kind, _ = parse_output_markers(glued)
    assert kind == "chart" and clean == CHART
    # the live 20:49 case: a two-bracket table opener after the sentence
    page = "<!DOCTYPE html>\n<html><body>dash</body></html>"
    glued_table = f"I need to run the daily dashboard data pulls fresh in this reply.<<OUTPUT:table>>\n{page}\n<<END_OUTPUT>>"
    clean, kind, _ = parse_output_markers(glued_table)
    assert kind == "table" and clean == page
    # and end-to-end through finalise_reply: the glued chart renders as a chart
    clean, kind, render, _ = finalise_reply(glued, "chart")
    assert (kind, render) == ("chart", "chart") and json.loads(clean)["type"] == "bar"
    # a mention mid-sentence (no sentence punctuation before it) stays text
    mention = "The <<<OUTPUT:chart>>> marker names the reply's type."
    clean, kind, _ = parse_output_markers(mention)
    assert kind == "text" and clean == mention
    # a colon lead-in with no real payload claims the type but doesn't hold —
    # decision 2's validation still lands it on text
    _, kind, render, _ = finalise_reply("Markers look like this: <<<OUTPUT:chart>>>", "chart")
    assert (kind, render) == ("text", "text")


def test_ot11_text_parts_around_tool_calls_get_a_line_break():
    """The other half of the glue (same finding): the event mapper now joins a
    run's SECOND text part to the first with a line break, so an opener that
    starts a fresh part lands at a line start even without punctuation."""
    from types import SimpleNamespace as NS

    from pydantic_ai.messages import PartDeltaEvent, PartStartEvent, TextPart, TextPartDelta

    from ai_engine.pydantic_ai_system.event_mapper import EventMapper

    mapper = EventMapper(msg_id="m1", persona=NS(id="p1", name="T"))
    mapper.map(PartStartEvent(index=0, part=TextPart(content="Pulling the data now")))
    mapper.map(PartDeltaEvent(index=0, delta=TextPartDelta(content_delta=" — one moment")))
    # (tool call happens here; a NEW text part opens the marker)
    mapper.map(PartStartEvent(index=1, part=TextPart(content="<<<OUTPUT:chart>>>")))
    mapper.map(PartDeltaEvent(index=1, delta=TextPartDelta(content_delta="\n" + CHART)))
    assert mapper.text() == f"Pulling the data now — one moment\n<<<OUTPUT:chart>>>\n{CHART}"
    clean, kind, _ = parse_output_markers(mapper.text())
    assert kind == "chart" and clean == CHART
    # a first part that already ends with a newline gets no second one
    mapper2 = EventMapper(msg_id="m2", persona=NS(id="p1", name="T"))
    mapper2.map(PartStartEvent(index=0, part=TextPart(content="Done.\n")))
    mapper2.map(PartStartEvent(index=1, part=TextPart(content="Next part")))
    assert mapper2.text() == "Done.\nNext part"


async def test_ot12_persona_default_answer_format_is_respected():
    """Found live 2026-10-27 (docs/MISSING.md): @Analyst set to Text answered
    "compare … per currency" with a chart — the persona's setting was never
    consulted. Order now: directive in the message → persona default (not
    auto) → classifier → text."""
    from unittest.mock import AsyncMock, patch

    from ai_engine.output_types import classifier
    from ai_engine.output_types.resolver import resolve_output_spec

    # The default decides — and the classifier is NOT consulted at all.
    with patch.object(classifier, "classify_output_type", new_callable=AsyncMock) as classify:
        name, spec = await resolve_output_spec(
            None, "how did revenue compare with September, per currency?", (),
            persona_default="text")
        assert name == "text" and spec is not None
        classify.assert_not_awaited()

    # A directive in the message still wins over the default.
    name, _ = await resolve_output_spec(
        "chart", "compare revenue", (), persona_default="text")
    assert name == "chart"

    # "auto" (and case/space noise) hands the choice to the classifier.
    with patch.object(classifier, "classify_output_type",
                      new_callable=AsyncMock, return_value="chart") as classify:
        name, _ = await resolve_output_spec(None, "compare revenue", (),
                                            persona_default=" Auto ")
        assert name == "chart"
        classify.assert_awaited_once()

    # An unknown default never breaks the turn — the classifier takes over.
    with patch.object(classifier, "classify_output_type",
                      new_callable=AsyncMock, return_value="text"):
        name, _ = await resolve_output_spec(None, "hello", (),
                                            persona_default="hologram")
        assert name == "text"


async def test_ot13_persona_default_rides_the_whole_trigger(harness):
    """E2E: the fake persona's prompt carries output_type='text', so a turn
    with NO directive resolves to text without ever touching the classifier
    (which would need an embedder this harness doesn't run)."""
    harness.provider.script.text = "Plain words, no chart."
    events = await harness.trigger(harness.job(output_type="auto"))
    [done] = _by_type(events, "message_done")
    assert done["output_type"] == "text" and done["render_as"] == "text"
    assert done["content"] == "Plain words, no chart."


def test_ot2_unmarked_chart_recovered_only_when_asked():
    """Item 23 — recovery files an unmarked chart ONLY on a chart turn.
    The whole-object JSON shaped as a chart: on resolved_type='chart' it is the
    chart (markers were dropped by the model); on resolved_type='text' it stays
    text — recovery never invents a type the resolver did not pick."""
    clean, kind, render, _ = finalise_reply(CHART, "chart")
    assert kind == "chart" and render == "chart" and json.loads(clean)
    _, kind, render, _ = finalise_reply(CHART, "text")
    assert kind == "text" and render == "text"


def test_ot9_tool_output_is_never_invented():
    """Live finding 2026-10-22 — a persona "ran" date and ls and invented both
    transcripts (wrong date, files that don't exist). Two guards now exist and
    must never regress: the terminal type's instruction demands REAL
    run_command output (the 0.8.0 wording "show realistic output" — an
    explicit invitation to fabricate — is gone), and the tool catalog carries
    the ground-truth rule for every tooled persona, appended AFTER the lines
    so the stable cache prefix is unchanged."""
    from types import SimpleNamespace as NS

    from ai_engine.output_types.registry import OutputTypeRegistry
    from ai_engine.prompts.layout import PromptLayout
    from ai_engine.prompts.templates import PromptTemplates

    spec = OutputTypeRegistry.get("terminal")
    assert "realistic" not in spec.system_instruction
    assert "run_command" in spec.system_instruction
    assert "not executed" in spec.system_instruction
    assert "NEVER invent" in spec.system_instruction

    plan = PromptLayout(PromptTemplates()).build(
        NS(project_brief="", system_prompt="You are T."), NS(history=()), "hi",
        catalog=[NS(model_name="shell", one_line="run commands")],
    )
    [section] = [s for s in plan.instructions if s.kind == "tool_catalog"]
    assert section.text.startswith("Tools available in this conversation:\n- shell: run commands")
    assert "only ground truth" in section.text and "never invent" in section.text
    # and a tool-less persona gets no catalog section at all — unchanged
    bare = PromptLayout(PromptTemplates()).build(
        NS(project_brief="", system_prompt="You are T."), NS(history=()), "hi")
    assert not [s for s in bare.instructions if s.kind == "tool_catalog"]


def test_ot3_broken_claims_fall_back_to_text():
    """Decision 2 — a claimed type whose content doesn't hold renders as text.
    'html' markers around something that is not an HTML page, and 'chart'
    markers around non-JSON, both downgrade to text/text instead of handing the
    renderer something broken."""
    _, kind, render, _ = finalise_reply("<<<OUTPUT:html>>>\nnot a page at all\n<<<END_OUTPUT>>>", "html")
    assert (kind, render) == ("text", "text")
    _, kind, render, _ = finalise_reply("<<<OUTPUT:chart>>>\noops not json\n<<<END_OUTPUT>>>", "chart")
    assert (kind, render) == ("text", "text")
    clean, kind, render, _ = finalise_reply(
        "<<<OUTPUT:html>>>\n<!DOCTYPE html>\n<html><body>hi</body></html>\n<<<END_OUTPUT>>>", "html")
    assert (kind, render) == ("html", "html") and clean.startswith("<!DOCTYPE")


# ── e2e: through the trigger ─────────────────────────────────────────────────

async def test_ot4_explicit_type_reaches_prompt_and_done(harness):
    """Item 23 — an explicit output_type wins: contract in, typed reply out.
    job.output_type='chart' puts the chart contract (and the choice exception)
    into the instructions; the model's marked reply lands on message_done as
    clean JSON with output_type='chart', render_as='chart', and the EMBED text
    as embed_description (item 44's input for rendered replies)."""
    harness.provider.script.text = f"<<<EMBED>>>\nSales by quarter.\n<<<END_EMBED>>>\n<<<OUTPUT:chart>>>\n{CHART}\n<<<END_OUTPUT>>>"
    events = await harness.trigger(harness.job(output_type="chart"))
    [done] = _by_type(events, "message_done")
    assert done["output_type"] == "chart" and done["render_as"] == "chart"
    assert json.loads(done["content"])["type"] == "bar"
    assert done["embed_description"] == "Sales by quarter."
    sent = str(harness.provider.requests[-1])
    assert "OUTPUT FORMAT INSTRUCTION" in sent and "<<<OUTPUT:chart>>>" in sent
    assert "choice prompt" in sent  # the standing exception rides along


async def test_ot5_plain_text_turn_is_untouched(harness):
    """Item 23 — auto + a plain answer: the Layer 0 stream, byte for byte.
    The classifier resolves an ordinary question to 'text'; the reply's content
    equals the streamed deltas exactly (T1's contract survives parsing), with
    output_type='text' and no embed_description."""
    harness.provider.script.text = "Nothing fancy here."
    events = await harness.trigger()
    [done] = _by_type(events, "message_done")
    deltas = "".join(e["delta"] for e in _by_type(events, "message_delta"))
    assert done["content"] == deltas
    assert done["output_type"] == "text" and done["render_as"] == "text"
    assert done.get("embed_description") is None


async def test_ot6_typed_turn_skips_the_router(harness):
    """Layer 4 design point 1 — a typed turn goes straight to a capable model.
    A persona WITH a router seat gets an explicit chart job: the router never
    runs (no kind='router' usage record); the reply is the chart, answered on
    the standard seat."""
    from conftest import openai_model
    from fake_nucleus import make_persona
    harness.nucleus.persona = make_persona(
        openai_model(harness),
        router_model=openai_model(harness, config_id="m-router", model_id="router-model"),
    )
    harness.provider.script.text = f"<<<OUTPUT:chart>>>\n{CHART}\n<<<END_OUTPUT>>>"
    events = await harness.trigger(harness.job(output_type="chart"))
    [done] = _by_type(events, "message_done")
    assert done["output_type"] == "chart"
    records = await harness.wait_for_usage(1)
    assert all(r.get("kind") != "router" for r in records)
