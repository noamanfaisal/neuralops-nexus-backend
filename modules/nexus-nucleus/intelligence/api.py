"""
AI Intelligence API — AIModel, MCPServer, Persona, PromptTemplate, CompanyAIConfig.
All endpoints require Supabase JWT auth and are company-scoped.
"""
from typing import List
from ninja import Router
from ninja.errors import HttpError

from authn.auth import SupabaseBearer
from .schema import (
    AIModelIn, AIModelOut, AIModelPatchIn,
    MCPServerIn, MCPServerOut,
    PersonaIn, PersonaPatchIn, PersonaOut,
    PromptTemplateOut,
    CompanyAIConfigIn, CompanyAIConfigOut,
    AIRequestLogOut,
    AgentIn, AgentOut,
    TestResultOut,
)
from . import services as svc

router = Router(tags=["Intelligence"], auth=SupabaseBearer())


def _company(request):
    company = svc.get_company()
    if not company:
        raise HttpError(503, "Server not initialised.")
    return company


def _model_out(model) -> AIModelOut:
    return AIModelOut(
        id=str(model.id),
        name=model.name,
        provider=model.provider,
        model_id=model.model_id,
        api_base=model.api_base,
        secret_ref=model.secret_ref,
        description=model.description,
        licence_accepted=model.licence_accepted,
        temperature=model.temperature,
        max_tokens=model.max_tokens,
        context_window=model.context_window,
        supports_tools=model.supports_tools,
        supports_streaming=model.supports_streaming,
        supports_vision=model.supports_vision,
        supports_audio=model.supports_audio,
        config=model.config,
        is_active=model.is_active,
        has_api_key=bool(model.api_key_encrypted),
    )


def _mcp_out(server) -> MCPServerOut:
    return MCPServerOut(
        id=str(server.id),
        name=server.name,
        description=server.description,
        server_type=server.server_type,
        transport=server.transport,
        url=server.url,
        command=server.command,
        docker_image=server.docker_image,
        config=server.config,
        timeout_seconds=server.timeout_seconds,
        max_retries=server.max_retries,
        is_active=server.is_active,
    )


def _persona_out(persona) -> PersonaOut:
    from .schema import PromptOut
    prompt = None
    if hasattr(persona, "prompt") and persona.prompt:
        p = persona.prompt
        prompt = PromptOut(
            id=str(p.id),
            system_prompt=p.system_prompt,
            output_type=p.output_type,
            context_scope=p.context_scope,
            template_id=str(p.template_id) if p.template_id else None,
        )
    return PersonaOut(
        id=str(persona.id),
        name=persona.name,
        description=persona.description,
        source_type=persona.source_type,
        model_id=str(persona.model_id) if persona.model_id else None,
        agent_id=str(persona.agent_id) if persona.agent_id else None,
        prompt=prompt,
        is_active=persona.is_active,
    )


# ── AIModel endpoints ─────────────────────────────────────────────────────────

@router.get("/ai-models/", response=List[AIModelOut])
def list_ai_models(request):
    company = _company(request)
    return [_model_out(m) for m in svc.list_ai_models(company)]


@router.post("/ai-models/", response=AIModelOut)
def create_ai_model(request, payload: AIModelIn):
    company = _company(request)
    if not payload.licence_accepted:
        raise HttpError(400, "You must accept the provider's terms of service.")
    data = payload.dict()
    try:
        model = svc.create_ai_model(company, request.auth, data)
    except Exception as e:
        msg = str(e)
        if "unique" in msg.lower() or "duplicate" in msg.lower():
            raise HttpError(409, f"A model named '{payload.name}' already exists.")
        raise HttpError(400, msg)
    return _model_out(model)


@router.patch("/ai-models/{model_id}/", response=AIModelOut)
def patch_ai_model(request, model_id: str, payload: AIModelPatchIn):
    company = _company(request)
    model = svc.patch_ai_model(company, model_id, payload.dict(exclude_none=True))
    if not model:
        raise HttpError(404, "AI model not found.")
    return _model_out(model)


@router.delete("/ai-models/{model_id}/", response={204: None})
def delete_ai_model(request, model_id: str):
    company = _company(request)
    if not svc.delete_ai_model(company, model_id):
        raise HttpError(404, "AI model not found.")
    return 204, None


# ── MCPServer endpoints ───────────────────────────────────────────────────────

@router.get("/ai-models/{model_id}/mcp-servers/", response=List[MCPServerOut])
def list_mcp_servers(request, model_id: str):
    company = _company(request)
    return [_mcp_out(s) for s in svc.list_mcp_servers(company, model_id)]


@router.post("/ai-models/{model_id}/mcp-servers/", response=MCPServerOut)
def create_mcp_server(request, model_id: str, payload: MCPServerIn):
    company = _company(request)
    try:
        server = svc.create_mcp_server(company, model_id, payload.dict())
    except ValueError as e:
        raise HttpError(404, str(e))
    return _mcp_out(server)


@router.delete("/ai-models/{model_id}/mcp-servers/{server_id}/", response={204: None})
def delete_mcp_server(request, model_id: str, server_id: str):
    company = _company(request)
    if not svc.delete_mcp_server(company, model_id, server_id):
        raise HttpError(404, "MCP server not found.")
    return 204, None


# ── Persona endpoints ─────────────────────────────────────────────────────────

@router.get("/personas/", response=List[PersonaOut])
def list_personas(request):
    company = _company(request)
    return [_persona_out(p) for p in svc.list_personas(company)]


@router.post("/personas/", response=PersonaOut)
def create_persona(request, payload: PersonaIn):
    company = _company(request)
    try:
        persona = svc.create_persona(company, request.auth, payload.dict())
    except Exception as e:
        msg = str(e)
        if "unique" in msg.lower() or "duplicate" in msg.lower():
            raise HttpError(409, f"A persona named '{payload.name}' already exists.")
        raise HttpError(400, msg)
    return _persona_out(persona)


@router.patch("/personas/{persona_id}/", response=PersonaOut)
def patch_persona(request, persona_id: str, payload: PersonaPatchIn):
    company = _company(request)
    persona = svc.patch_persona(company, persona_id, payload.dict(exclude_none=True))
    if not persona:
        raise HttpError(404, "Persona not found.")
    return _persona_out(persona)


@router.delete("/personas/{persona_id}/", response={204: None})
def delete_persona(request, persona_id: str):
    company = _company(request)
    if not svc.delete_persona(company, persona_id):
        raise HttpError(404, "Persona not found.")
    return 204, None


# ── PromptTemplate endpoints ──────────────────────────────────────────────────

@router.get("/prompt-templates/", response=List[PromptTemplateOut])
def list_prompt_templates(request):
    company = _company(request)
    return [
        PromptTemplateOut(
            id=str(t.id),
            title=t.title,
            description=t.description,
            system_prompt=t.system_prompt,
            output_type=t.output_type,
            tags=t.tags,
            is_featured=t.is_featured,
        )
        for t in svc.list_prompt_templates(company)
    ]


# ── CompanyAIConfig endpoints ─────────────────────────────────────────────────

@router.get("/ai-config/", response=CompanyAIConfigOut)
def get_ai_config(request):
    company = _company(request)
    config = svc.get_ai_config(company)
    return CompanyAIConfigOut(
        embedding_provider=config.embedding_provider,
        embedding_model=config.embedding_model,
        embedding_base_url=config.embedding_base_url,
        default_llm_model=config.default_llm_model,
    )


@router.get("/ai-request-logs/", response=List[AIRequestLogOut])
def list_ai_request_logs(request):
    """Return the last 200 AI request logs, newest first."""
    from nucleus.models import AIRequestLog
    company = _company(request)
    logs = (
        AIRequestLog.objects.filter(company=company)
        .order_by("-created_at")[:200]
    )
    return [
        AIRequestLogOut(
            id=str(log.id),
            job_id=log.job_id,
            msg_id=log.msg_id,
            persona_id=str(log.persona_id) if log.persona_id else None,
            model_id=log.model_id,
            provider=log.provider,
            prompt=log.prompt,
            response=log.response,
            prompt_tokens=log.prompt_tokens,
            completion_tokens=log.completion_tokens,
            latency_ms=log.latency_ms,
            status=log.status,
            error=log.error,
            created_at=log.created_at.isoformat(),
        )
        for log in logs
    ]


@router.put("/ai-config/", response=CompanyAIConfigOut)
def update_ai_config(request, payload: CompanyAIConfigIn):
    company = _company(request)
    config = svc.update_ai_config(company, request.auth, payload.dict())
    return CompanyAIConfigOut(
        embedding_provider=config.embedding_provider,
        embedding_model=config.embedding_model,
        embedding_base_url=config.embedding_base_url,
        default_llm_model=config.default_llm_model,
    )


# ── AIAgent endpoints (M9) ──────────────────────────────────────────────────

def _agent_out(agent) -> AgentOut:
    return AgentOut(
        id=str(agent.id),
        name=agent.name,
        description=agent.description,
        agent_type=agent.agent_type,
        model_id=str(agent.model_id) if agent.model_id else None,
        mcp_server_id=str(agent.mcp_server_id) if agent.mcp_server_id else None,
        external_url=agent.external_url,
        system_prompt=agent.system_prompt,
        safety_mode=agent.safety_mode,
        max_steps=agent.max_steps,
        allow_parallel_tools=agent.allow_parallel_tools,
        has_api_key=bool(agent.api_key_encrypted),
        is_active=agent.is_active,
    )


@router.get("/agents/", response=List[AgentOut])
def list_agents(request):
    company = _company(request)
    return [_agent_out(a) for a in svc.list_agents(company)]


@router.post("/agents/", response=AgentOut)
def create_agent(request, payload: AgentIn):
    company = _company(request)
    try:
        agent = svc.create_agent(company, payload.dict())
    except Exception as e:
        raise HttpError(400, str(e))
    return _agent_out(agent)


@router.delete("/agents/{agent_id}/", response={204: None})
def delete_agent(request, agent_id: str):
    company = _company(request)
    if not svc.delete_agent(company, agent_id):
        raise HttpError(404, "Agent not found.")
    return 204, None


# ── Standalone MCP Server endpoints (M9) ─────────────────────────────────────

@router.get("/mcp-servers/", response=List[MCPServerOut])
def list_all_mcp_servers(request):
    company = _company(request)
    return [_mcp_out(s) for s in svc.list_all_mcp_servers(company)]


@router.post("/mcp-servers/", response=MCPServerOut)
def create_mcp_server_standalone(request, payload: MCPServerIn):
    company = _company(request)
    try:
        server = svc.create_standalone_mcp_server(company, payload.dict())
    except Exception as e:
        msg = str(e)
        if "unique" in msg.lower() or "duplicate" in msg.lower():
            raise HttpError(409, f"An MCP server named '{payload.name}' already exists.")
        raise HttpError(400, msg)
    return _mcp_out(server)


@router.delete("/mcp-servers/{server_id}/", response={204: None})
def delete_mcp_server_standalone(request, server_id: str):
    company = _company(request)
    if not svc.delete_standalone_mcp_server(company, server_id):
        raise HttpError(404, "MCP server not found.")
    return 204, None


# ── Test endpoints (M9) ───────────────────────────────────────────────────────────

def _call_nexus_ai_test(path: str, body: dict) -> TestResultOut:
    """
    Proxy a test request to nexus-ai's /api/v1/test/* endpoint.
    Returns a TestResultOut regardless of success/failure.
    """
    import httpx
    from django.conf import settings

    base_url = getattr(settings, "NEXUS_AI_URL", "").rstrip("/")
    if not base_url:
        return TestResultOut(ok=False, error="NEXUS_AI_URL is not configured.")

    try:
        r = httpx.post(
            f"{base_url}{path}",
            json=body,
            timeout=30,
        )
        data = r.json()
        return TestResultOut(
            ok=data.get("ok", False),
            response=data.get("response"),
            tools=data.get("tools", []),
            latency_ms=data.get("latency_ms", 0),
            error=data.get("error"),
        )
    except Exception as exc:
        return TestResultOut(ok=False, error=str(exc))


@router.post("/ai-models/{model_id}/test/", response=TestResultOut)
def test_ai_model(request, model_id: str):
    """Send a hello message to the model and return the response."""
    company = _company(request)
    model = svc.get_ai_model(company, model_id)
    if not model:
        raise HttpError(404, "AI model not found.")
    return _call_nexus_ai_test("/api/v1/test/model/", {
        "provider": model.provider,
        "model_id": model.model_id,
        "api_key": model.get_api_key(),
        "api_base": model.api_base,
        "temperature": model.temperature,
        "max_tokens": 128,
    })


@router.post("/mcp-servers/{server_id}/test/", response=TestResultOut)
def test_mcp_server(request, server_id: str):
    """Connect to the MCP server and list its tools."""
    company = _company(request)
    server = svc.list_all_mcp_servers(company).filter(id=server_id).first()
    if not server:
        raise HttpError(404, "MCP server not found.")
    return _call_nexus_ai_test("/api/v1/test/mcp/", {
        "transport": server.transport,
        "url": server.url,
        "command": server.command,
        "timeout_seconds": server.timeout_seconds,
    })


@router.post("/agents/{agent_id}/test/", response=TestResultOut)
def test_agent(request, agent_id: str):
    """Test an agent: for internal agents test the model; for external agents ping the URL."""
    company = _company(request)
    agent = svc.get_agent(company, agent_id)
    if not agent:
        raise HttpError(404, "Agent not found.")

    if agent.agent_type == "internal" and agent.model:
        m = agent.model
        return _call_nexus_ai_test("/api/v1/test/model/", {
            "provider": m.provider,
            "model_id": m.model_id,
            "api_key": m.get_api_key(),
            "api_base": m.api_base,
            "temperature": m.temperature,
            "max_tokens": 128,
        })

    elif agent.agent_type == "external" and agent.external_url:
        # Ping external agent with a simple health/hello request
        import httpx, time
        headers = {}
        api_key = agent.get_api_key()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        t0 = time.monotonic()
        try:
            r = httpx.post(
                agent.external_url,
                json={"messages": [{"role": "user", "content": "Hello! Reply in one sentence."}]},
                headers=headers,
                timeout=15,
            )
            latency_ms = int((time.monotonic() - t0) * 1000)
            data = r.json()
            reply = data.get("content") or data.get("response") or str(data)[:200]
            return TestResultOut(ok=r.is_success, response=reply, latency_ms=latency_ms)
        except Exception as exc:
            latency_ms = int((time.monotonic() - t0) * 1000)
            return TestResultOut(ok=False, error=str(exc), latency_ms=latency_ms)

    return TestResultOut(ok=False, error="Agent is not configured (no model or external URL).")


@router.post("/personas/{persona_id}/test/", response=TestResultOut)
def test_persona(request, persona_id: str):
    """Test a persona by routing to its underlying model or agent."""
    company = _company(request)
    persona = svc.get_persona(company, persona_id)
    if not persona:
        raise HttpError(404, "Persona not found.")

    if persona.source_type == "model" and persona.model:
        m = persona.model
        return _call_nexus_ai_test("/api/v1/test/model/", {
            "provider": m.provider,
            "model_id": m.model_id,
            "api_key": m.get_api_key(),
            "api_base": m.api_base,
            "temperature": m.temperature,
            "max_tokens": 128,
        })

    elif persona.source_type == "agent" and persona.agent and persona.agent.model:
        m = persona.agent.model
        return _call_nexus_ai_test("/api/v1/test/model/", {
            "provider": m.provider,
            "model_id": m.model_id,
            "api_key": m.get_api_key(),
            "api_base": m.api_base,
            "temperature": m.temperature,
            "max_tokens": 128,
        })

    return TestResultOut(ok=False, error="Persona has no model or agent configured.")


# ── Output Types (M7) ─────────────────────────────────────────────────────────

@router.get("/output-types/")
def list_output_types(request):
    """
    Return all available AI output types.
    Used by the frontend @mention picker to show output type directives.
    These match the types registered in nexus-ai/apps/output_types/types.py.
    """
    _company(request)  # auth check
    return [
        {"name": "text",     "label": "Text",      "icon": "align-left",    "render_as": "text"},
        {"name": "code",     "label": "Code",      "icon": "code-2",        "render_as": "code"},
        {"name": "chart",    "label": "Chart",     "icon": "bar-chart-2",   "render_as": "html"},
        {"name": "table",    "label": "Table",     "icon": "table",         "render_as": "html"},
        {"name": "diagram",  "label": "Diagram",   "icon": "git-branch",    "render_as": "html"},
        {"name": "form",     "label": "Form",      "icon": "clipboard-list","render_as": "html"},
        {"name": "html",     "label": "HTML Page", "icon": "globe",         "render_as": "html"},
        {"name": "terminal", "label": "Terminal",  "icon": "terminal",      "render_as": "terminal"},
    ]
