"""
Model transform (Chains v2, ruling 2) — ONE bare model call: a prompt in, text
out, with the usage counted the same way a reply's is. No tools, no approvals,
no streaming back to a reader — a chain's "model" step is a text transform, and
this is the whole of it.

The model is built by the SAME ModelFactory a persona run uses (model_check's
spec helper), so "the transform ran" means "a persona on this model would run".
The usage block mirrors UsageReader's counting semantics (verified on the
pinned pydantic-ai 2.55.0): input_tokens includes cache read + write,
output_tokens includes reasoning, the 1h cache write rides an undeclared field
or the details cross-check. Nucleus prices the counts on arrival, as always.

The answer is a plain dict, model_check's shape family: ok with text + usage +
latency, or not ok with the raw error (for nucleus to word, never shown raw),
the HTTP status when there is one, and the same error_code vocabulary.
"""
from __future__ import annotations

import asyncio
import logging
import time

from pydantic_ai import Agent
from pydantic_ai.messages import ModelResponse

from ai_engine.pydantic_ai_system.model_check import (
    SUPPORTED_PROVIDERS,
    _is_model_failure,
    _spec_for_check,
)
from ai_engine.pydantic_ai_system.model_factory import ModelFactory

log = logging.getLogger(__name__)

TRANSFORM_TIMEOUT = 150.0


def _usage_block(result) -> dict:
    """The priced token counts from the run's FINAL model response — the same
    reads UsageReader makes, without a UsageRecord to fill."""
    response = next(
        (m for m in reversed(result.all_messages()) if isinstance(m, ModelResponse)),
        None,
    )
    usage = response.usage if response is not None else None
    details = (usage.details or {}) if usage else {}
    input_tokens = usage.input_tokens if usage else 0
    cache_read = usage.cache_read_tokens if usage else 0
    cache_write = usage.cache_write_tokens if usage else 0
    output_tokens = usage.output_tokens if usage else 0
    cache_write_1h = (getattr(usage, "cache_write_1h_tokens", 0) if usage else 0) \
        or int(details.get("ephemeral_1h_input_tokens") or 0)
    reasoning = (getattr(usage, "output_reasoning_tokens", 0) if usage else 0) \
        or int(details.get("reasoning_tokens") or 0)
    return {
        "input_tokens": input_tokens,
        "uncached_input_tokens": max(input_tokens - cache_read - cache_write, 0),
        "cache_read_tokens": cache_read,
        "cache_write_5m_tokens": max(cache_write - cache_write_1h, 0),
        "cache_write_1h_tokens": cache_write_1h,
        "output_tokens": output_tokens,
        "reasoning_tokens": reasoning,
        "finish_reason": response.finish_reason if response is not None else None,
        "provider_response_id": response.provider_response_id if response is not None else None,
        # UsageReader's estimated rule, so nucleus can flag the counts.
        "estimated": bool(
            response is None
            or not response.finish_reason
            or (input_tokens == 0 and output_tokens == 0)
        ),
    }


async def transform_model(
    provider: str,
    model_id: str,
    api_key: str | None,
    api_base: str | None,
    prompt: str,
    system: str | None = None,
    max_tokens: int | None = None,
    temperature: float | None = None,
    timeout: float = TRANSFORM_TIMEOUT,
) -> dict:
    if provider.lower() not in SUPPORTED_PROVIDERS:
        return {"ok": False, "error_code": "unsupported_provider",
                "error": f"provider '{provider}' is not supported by this worker"}
    settings: dict = {}
    if max_tokens:
        settings["max_tokens"] = int(max_tokens)
    if temperature is not None:
        settings["temperature"] = float(temperature)
    started = time.monotonic()
    try:
        spec = _spec_for_check(provider, model_id, api_key, api_base)
        agent = Agent(model=ModelFactory().build(spec), system_prompt=system or ())

        async def _one_call():
            # Streamed, like every reply (and model_check): the providers — and
            # the test fake — all speak the streaming wire.
            async with agent.run_stream(prompt, model_settings=settings or None) as stream:
                text = await stream.get_output()
                return text, stream

        output, result = await asyncio.wait_for(_one_call(), timeout)
    except (asyncio.TimeoutError, TimeoutError):
        return {"ok": False, "error_code": "timeout",
                "error": f"the model did not answer within {timeout:.0f}s (timed out)"}
    except Exception as exc:  # noqa: BLE001 — every failure becomes a worded answer
        status = getattr(exc, "status_code", None)
        log.info("[model_transform] %s:%s failed: %s %s", provider, model_id,
                 type(exc).__name__, status or "")
        return {
            "ok": False,
            "error_code": "model_failure" if _is_model_failure(exc) else "error",
            "error": str(exc),
            "status_code": status if isinstance(status, int) else None,
        }
    # Streaming joins word deltas as sent, trailing whitespace included; a
    # step's output is a value other steps build on, so hand it back clean.
    text = (output if isinstance(output, str) else str(output)).strip()
    return {
        "ok": True,
        "text": text,
        "usage": _usage_block(result),
        "latency_ms": int((time.monotonic() - started) * 1000),
    }
