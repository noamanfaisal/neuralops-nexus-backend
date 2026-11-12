"""The forgiving web_fetch road + the current-date prompt section.

Live finding 2026-11-12 (Contabo, job 4a563c44): a persona fetched
timeanddate.com to learn the date, the site answered 403 twice, the tool's
max_retries tripped and UnexpectedModelBehavior killed the WHOLE reply.
Two fixes, two halves of this file:
- toolset_builder._forgiving_web_fetch — a failed fetch comes back as a
  worded RESULT the model can route around, never an exception;
- PromptLayout — the persona is told today's date (volatile section, last),
  so it has no reason to fetch clock sites at all.
"""
from types import SimpleNamespace as NS

import pytest

from ai_engine.pydantic_ai_system.tools.toolset_builder import _forgiving_web_fetch

pytestmark = pytest.mark.asyncio


async def test_a_refused_fetch_is_a_worded_result_not_an_exception():
    # The blocked-domains road raises ModelRetry inside the library tool —
    # the same exception class the 403 road raises — with no network needed.
    fetch = _forgiving_web_fetch(blocked_domains=["refused.example"])
    result = await fetch("https://refused.example/page")
    assert result["fetch_failed"] is True
    assert result["url"] == "https://refused.example/page"
    assert "refused.example" in result["reason"]
    assert "Do not fetch" in result["guidance"]


async def test_nothing_a_url_does_raises_out_of_the_wrapper():
    # A private address with allow_local_urls=False is refused by the SSRF
    # guard — a different exception family, same worded landing.
    fetch = _forgiving_web_fetch()
    result = await fetch("http://127.0.0.1:1/nothing")
    assert result["fetch_failed"] is True
    assert result["reason"]


async def test_the_allowed_road_still_enforces_the_list():
    fetch = _forgiving_web_fetch(allowed_domains=["only.example"])
    result = await fetch("https://other.example/")
    assert result["fetch_failed"] is True


async def test_the_persona_is_told_todays_date_after_the_stable_prefix():
    from datetime import datetime, timezone

    from ai_engine.prompts.layout import PromptLayout
    from ai_engine.prompts.templates import PromptTemplates

    plan = PromptLayout(PromptTemplates()).build(
        NS(project_brief="", system_prompt="You are T."), NS(history=()), "hi",
        catalog=[NS(model_name="shell", one_line="run commands")],
    )
    [section] = [s for s in plan.instructions if s.kind == "current_date"]
    assert section.stable is False  # volatile → joined LAST, cache prefix intact
    assert datetime.now(timezone.utc).strftime("%Y-%m-%d") in section.text
    assert "Never fetch clock or calendar websites" in section.text

    # and the joined instructions put it after every stable section
    from ai_engine.pydantic_ai_system.message_converter import MessageConverter
    joined = MessageConverter().instructions(plan)
    assert joined.rstrip().endswith("say it is not known.")
