"""
Test router — fire-once model/MCP tests for the /command configuration system (M9).

POST /api/v1/test/model/   → send "hello" to a model, return response + latency
POST /api/v1/test/mcp/     → connect to MCP server, return tools list
"""
import time
import logging
from fastapi import APIRouter
from pydantic import BaseModel

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/test", tags=["Test"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class ModelTestRequest(BaseModel):
    provider: str           # "litellm" | "local"
    model_id: str           # e.g. "openai/gpt-4o-mini"
    api_key: str | None = None
    api_base: str | None = None
    temperature: float = 0.7
    max_tokens: int = 256


class ModelTestResponse(BaseModel):
    ok: bool
    response: str | None = None
    latency_ms: int = 0
    error: str | None = None


class MCPTestRequest(BaseModel):
    transport: str          # "http" | "stdio" | "sse"
    url: str | None = None
    command: str | None = None
    timeout_seconds: int = 15


class MCPTestResponse(BaseModel):
    ok: bool
    tools: list[str] = []
    error: str | None = None


# ── Model test ────────────────────────────────────────────────────────────────

@router.post("/model/", response_model=ModelTestResponse)
async def test_model(payload: ModelTestRequest) -> ModelTestResponse:
    """
    Send a single "hello" message to the model (non-streaming).
    Returns the response text and latency, or an error message.
    """
    import litellm
    from apps.core.config import settings

    kwargs: dict = {
        "model": payload.model_id,
        "messages": [{"role": "user", "content": "Hello! Please reply in one short sentence."}],
        "max_tokens": payload.max_tokens,
        "temperature": payload.temperature,
        "stream": False,
    }

    if payload.provider == "local":
        base = payload.api_base or f"{settings.OLLAMA_BASE_URL}/v1"
        kwargs["api_base"] = base
        kwargs["api_key"] = "local"
    elif payload.api_key:
        kwargs["api_key"] = payload.api_key
    if payload.api_base and payload.provider != "local":
        kwargs["api_base"] = payload.api_base

    t0 = time.monotonic()
    try:
        response = await litellm.acompletion(**kwargs)
        latency_ms = int((time.monotonic() - t0) * 1000)
        text = response.choices[0].message.content or ""
        return ModelTestResponse(ok=True, response=text.strip(), latency_ms=latency_ms)
    except Exception as exc:
        latency_ms = int((time.monotonic() - t0) * 1000)
        log.warning("[test/model] error: %s", exc)
        return ModelTestResponse(ok=False, error=str(exc), latency_ms=latency_ms)


# ── MCP test ──────────────────────────────────────────────────────────────────

@router.post("/mcp/", response_model=MCPTestResponse)
async def test_mcp(payload: MCPTestRequest) -> MCPTestResponse:
    """
    Connect to an MCP server and return the list of tool names.
    """
    try:
        if payload.transport == "stdio":
            from pydantic_ai.mcp import MCPServerStdio
            cmd_parts = (payload.command or "").split()
            if not cmd_parts:
                return MCPTestResponse(ok=False, error="No command provided for stdio transport.")
            server = MCPServerStdio(cmd_parts[0], args=cmd_parts[1:])
        else:
            from pydantic_ai.mcp import MCPServerStreamableHTTP
            if not payload.url:
                return MCPTestResponse(ok=False, error="No URL provided for HTTP transport.")
            server = MCPServerStreamableHTTP(payload.url)

        # List tools via the MCP client
        async with server:
            tools = await server.list_tools()
            tool_names = [t.name for t in tools]
            return MCPTestResponse(ok=True, tools=tool_names)

    except Exception as exc:
        log.warning("[test/mcp] error: %s", exc)
        return MCPTestResponse(ok=False, error=str(exc))
