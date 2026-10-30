"""
Chains v2, ruling 2 — the model transform endpoint
(POST /api/v1/models/transform/): one bare model call for a chain's "model"
step — prompt in, text + priced usage out; no tools, no approvals.
"""
from __future__ import annotations

import httpx
import pytest

from conftest import INTERNAL_KEY

pytestmark = pytest.mark.asyncio


async def _transform(harness, payload: dict) -> dict:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{harness.app_url}/api/v1/models/transform/",
            json=payload, headers={"X-Internal-Key": INTERNAL_KEY},
        )
        assert response.status_code == 200
        return response.json()


async def test_tr1_a_transform_returns_the_text_and_the_priced_usage(harness):
    """Ruling 2 — a model step's whole life: the prompt goes out through the
    SAME ModelFactory a persona run uses, the text comes back whole, and the
    usage block carries the priced token counts (UsageReader's semantics) for
    nucleus to bill as kind=chat_reply."""
    harness.provider.script.text = "A tighter draft."
    result = await _transform(harness, {
        "provider": "openai", "model_id": "fake-model",
        "api_key": "k", "api_base": harness.provider_url + "/v1",
        "prompt": "Tighten the draft.",
    })
    assert result["ok"] is True, result
    assert result["text"] == "A tighter draft."
    usage = result["usage"]
    assert usage["input_tokens"] == 10 and usage["output_tokens"] == 5  # the fake's defaults
    assert usage["uncached_input_tokens"] == 10
    assert isinstance(result["latency_ms"], int) and result["latency_ms"] >= 0
    # The prompt actually reached the provider, as the user message.
    body = harness.provider.requests[-1]
    assert any("Tighten the draft." in str(m.get("content")) for m in body["messages"])


async def test_tr2_generation_settings_ride_the_call(harness):
    """Ruling 2 — the step's model card settings (max_tokens, temperature)
    ride the transform call exactly as they ride a reply."""
    harness.provider.script.text = "ok"
    result = await _transform(harness, {
        "provider": "openai", "model_id": "fake-model",
        "api_key": "k", "api_base": harness.provider_url + "/v1",
        "prompt": "p", "max_tokens": 123, "temperature": 0.2,
    })
    assert result["ok"] is True, result
    body = harness.provider.requests[-1]
    sent = {k: body.get(k) for k in ("max_tokens", "max_completion_tokens", "temperature")}
    assert 123 in (sent["max_tokens"], sent["max_completion_tokens"])
    assert sent["temperature"] == 0.2


async def test_tr3_failures_are_worded_answers_never_500s(harness):
    """Ruling 2 — an unknown provider, and a dead endpoint, both answer 200
    with ok=false and model_check's error_code vocabulary; a chain's step then
    fails under its own on_failure rule with a worded reason."""
    result = await _transform(harness, {"provider": "banana", "model_id": "x", "prompt": "p"})
    assert (result["ok"], result["error_code"]) == (False, "unsupported_provider")
    result = await _transform(harness, {
        "provider": "openai", "model_id": "dead",
        "api_key": "k", "api_base": "http://127.0.0.1:9/v1", "prompt": "p",
    })
    assert result["ok"] is False
    assert result["error_code"] in ("model_failure", "error")
    assert result["error"]
