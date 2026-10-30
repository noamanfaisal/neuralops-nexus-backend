"""
POST /api/v1/models/check/ (item 40, Layer 2) — verify a model with its key
before nucleus saves it. Internal only; 0.8.0's path and answer shape, kept,
so nucleus's Register/Edit dialogs work unchanged.

POST /api/v1/models/transform/ (Chains v2, ruling 2) — one bare model call:
a chain's "model" step is a text-only transform, no tools, no approvals.
Internal only, same key.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ai_engine.pydantic_ai_system.model_check import check_model
from ai_engine.pydantic_ai_system.model_transform import transform_model
from fastapi_app.routers.trigger import _verify_key

router = APIRouter(prefix="/api/v1", tags=["models"])


class ModelCheckIn(BaseModel):
    provider: str
    model_id: str
    api_key: str | None = None
    api_base: str | None = None


@router.post("/models/check/")
async def check(payload: ModelCheckIn, _: str = Depends(_verify_key)) -> dict:
    return await check_model(payload.provider, payload.model_id,
                             payload.api_key, payload.api_base)


class ModelTransformIn(BaseModel):
    provider: str
    model_id: str
    api_key: str | None = None
    api_base: str | None = None
    prompt: str
    system: str | None = None
    max_tokens: int | None = None
    temperature: float | None = None


@router.post("/models/transform/")
async def transform(payload: ModelTransformIn, _: str = Depends(_verify_key)) -> dict:
    return await transform_model(
        payload.provider, payload.model_id, payload.api_key, payload.api_base,
        payload.prompt, system=payload.system,
        max_tokens=payload.max_tokens, temperature=payload.temperature,
    )
