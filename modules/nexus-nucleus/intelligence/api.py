"""
AI Intelligence API — ModelConfig, MCPServer, Persona, PromptTemplate,
CompanyAIConfig. All endpoints require Supabase JWT auth and are
company-scoped.

── Removed in the AIAgent collapse ───────────────────────────────────────
Seven endpoints are gone:
    GET/POST/PATCH/DELETE  /agents/...
    GET/POST/DELETE        /ai-models/{id}/mcp-servers/...   (legacy nested)

The legacy nested POST had been returning 500 on every call -- it passed
project_id and client_secret into MCPServer(**data), which has neither
field -- and when it did work it created an AIAgent with no project
attached, invisible to everyone under row-level visibility.

/ai-models/ is now /model-configs/, and PATCH /model-configs/{id}/ is new:
rotating an API key used to require delete-and-recreate, and delete is
refused while any persona references the row.
"""
from typing import List, Optional
from ninja import Router, Schema
from ninja.errors import HttpError
from pathlib import Path
import base64
import binascii
import logging

from nucleus.models import Project, Persona, AIRequestLog, ModelConfig

logger = logging.getLogger(__name__)
from authn.auth import SupabaseBearer
from authn.permissions.checker import PermissionChecker
from .schema import (
    ModelCheckIn, ModelCheckOut,
    ModelConfigIn, ModelConfigPatchIn, ModelConfigOut, ModelConfigRef,
    MCPServerIn, MCPServerPatchIn, MCPServerOut, MCPServerRef,
    MCPOAuthAuthorizeOut,
    PersonaIn, PersonaPatchIn, PersonaOut,
    PromptTemplateOut,
    CompanyAIConfigIn, CompanyAIConfigOut,
    AIRequestLogOut,
    AuditEntryOut, AuditEntryDetailOut,
    ListTemplatePrompts,
    TemplatePromptContent,
)
from . import services as svc
from .schema import RoutineIn, RoutinePatchIn, RoutineOut
from .schema import MCPCatalogEntryOut, ModelPresetOut, PersonaCatalogEntryOut
from intelligence import mcp_catalog as mcp_catalog_content
from intelligence import model_presets as model_presets_content
from intelligence import persona_catalog as persona_catalog_content

router = Router(tags=["Intelligence"], auth=SupabaseBearer())

PROMPTS_DIR = (Path(__file__).resolve().parent / 'prompts').resolve()


def _company(request):
    company = svc.get_company()
    if not company:
        raise HttpError(503, "Server not initialised.")
    return company


# ── Serialisers ───────────────────────────────────────────────────────────────

def _oauth_connected(server) -> bool:
    """
    True iff signed in: a refresh token is stored, or a non-expiring access
    token (GitHub OAuth Apps) -- oauth_client.has_usable_token. Only decrypts
    for oauth2 servers --
    get_secrets() is a Fernet decrypt, and doing it for every static-secrets
    server in a list would be pure waste.
    """
    # Internal rows have auth_type forced to "none", so they short-circuit
    # here too -- an in-process pydantic-ai capability has nothing to connect.
    if server.auth_type != "oauth2":
        return False
    from intelligence.oauth_client import has_usable_token
    return has_usable_token(server)


def _model_config_out(config, utility_id: str | None = None) -> ModelConfigOut:
    return ModelConfigOut(
        is_utility=str(config.id) == utility_id,
        id=str(config.id),
        name=config.name,
        provider=config.provider,
        model_id=config.model_id,
        qualified_id=config.qualified_id,
        api_base=config.api_base,
        description=config.description,
        licence_accepted=config.licence_accepted,
        context_window=config.context_window,
        max_output_tokens=config.max_output_tokens,
        temperature=config.temperature,
        routing_notes=config.routing_notes,
        supports_tools=config.supports_tools,
        supports_streaming=config.supports_streaming,
        supports_vision=config.supports_vision,
        supports_audio=config.supports_audio,
        config=config.config,
        is_active=config.is_active,
        has_api_key=bool(config.api_key_encrypted),
        last_check_ok_at=config.last_check_ok_at.isoformat() if config.last_check_ok_at else None,
        project_ids=[
            str(pid) for pid in config.projects.filter(is_active=True).values_list("id", flat=True)
        ],
    )


def _model_config_ref(config) -> ModelConfigRef:
    return ModelConfigRef(
        id=str(config.id),
        name=config.name,
        provider=config.provider,
        model_id=config.model_id,
        qualified_id=config.qualified_id,
        supports_tools=config.supports_tools,
    )


# ── Stored tool lists (Step 6, handoff change 6) ───────────────────────

def _bearer_for_dial(server) -> str | None:
    """The same rule the engine applies at trigger time (toolset_builder):
    oauth2 servers send the user access token, static ones client_secret."""
    secrets = server.get_secrets()
    if server.auth_type == "oauth2":
        return secrets.get((server.oauth_config or {}).get("token_env_var", "OAUTH_ACCESS_TOKEN"))
    return secrets.get("client_secret")


def _refresh_server_tools(server) -> tuple[bool, str]:
    """
    Dial the server through the engine and store its tool list on the row
    (fetched at attach/save + the Refresh button — no background syncing,
    owner's ruling 7). (True, "") on success; (False, reason) on a failed
    dial. Internal rows and non-HTTP transports keep an empty list — that
    is not an error (stdio tool lists arrive when stdio dialing lands).
    """
    from chat.nexus_ai import NexusAIClient

    if server.is_internal or server.transport not in ("http", "sse") or not server.url:
        return True, ""
    ok, result = NexusAIClient().list_mcp_tools(server.url, _bearer_for_dial(server))
    if not ok:
        return False, str(result)
    server.tools = [
        {"name": t.get("name", ""), "description": t.get("one_line", ""),
         "read_only": t.get("read_only")}
        for t in result if t.get("name")
    ]
    server.save(update_fields=["tools"])
    return True, ""


def _mcp_out(server) -> MCPServerOut:
    return MCPServerOut(
        id=str(server.id),
        name=server.name,
        description=server.description,
        project_id=str(server.project_id),
        is_internal=server.is_internal,
        capability_config=server.capability_config,
        is_protected=server.is_protected,
        is_default=server.is_default,
        server_type=server.server_type,
        transport=server.transport,
        url=server.url,
        command=server.command,
        docker_image=server.docker_image,
        docker_command=server.docker_command,
        kubernetes_service=server.kubernetes_service,
        config=server.config,
        timeout_seconds=server.timeout_seconds,
        max_retries=server.max_retries,
        is_first_party=server.is_first_party,
        embed_output=server.embed_output,
        is_active=server.is_active,
        auth_type=server.auth_type,
        oauth_connected=_oauth_connected(server),
        oauth_config=server.oauth_config,
        tools=server.tools or [],
    )


def _mcp_ref(server) -> MCPServerRef:
    return MCPServerRef(
        id=str(server.id),
        name=server.name,
        is_internal=server.is_internal,
        transport=server.transport,
        auth_type=server.auth_type,
        oauth_connected=_oauth_connected(server),
    )


def _persona_out(persona) -> PersonaOut:
    from .schema import PromptOut
    # The deep BENCH (smart router): read through the ordered through rows;
    # deep_model stays the bench's first entry for clients built against the
    # single seat.
    deep_bench = svc.deep_models_of(persona)
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
        project_id=str(persona.project_id),
        model=_model_config_ref(persona.model),
        advisor_model=_model_config_ref(persona.advisor_model) if persona.advisor_model_id else None,
        router_model=_model_config_ref(persona.router_model) if persona.router_model_id else None,
        deep_models=[_model_config_ref(m) for m in deep_bench],
        deep_model=_model_config_ref(deep_bench[0]) if deep_bench else None,
        fallback_models=[_model_config_ref(m) for m in svc.fallback_models_of(persona)],
        mcp_servers=[_mcp_ref(s) for s in persona.mcp_servers.all() if s.is_active],
        temperature=persona.temperature,
        max_tokens=persona.max_tokens,
        max_steps=persona.max_steps,
        acts_after_approval=persona.acts_after_approval,
        tool_levels=persona.tool_levels or {},
        prompt=prompt,
        is_active=persona.is_active,
        avatar=(
            persona.identity_user.avatar.url
            if persona.identity_user_id and persona.identity_user.avatar
            else None
        ),
    )


# ── ModelConfig endpoints ─────────────────────────────────────────────────────
# Rights: model_config.list / .create / .update / .delete — COMPANY scope only
# (AI infrastructure has no project boundary). model_config.attach is PROJECT
# scope: attaching an existing config never touches its API key, so it is a
# lighter action reachable by that project's own Admin.

@router.get("/model-configs/", response=List[ModelConfigOut])
def list_model_configs(request):
    company = _company(request)
    utility = svc.utility_model_of(company)
    utility_id = str(utility.id) if utility else None
    return [_model_config_out(m, utility_id) for m in svc.list_model_configs(company, request.auth)]


@router.post("/model-configs/", response=ModelConfigOut)
def create_model_config(request, payload: ModelConfigIn):
    company = _company(request)
    if not PermissionChecker.can(request.auth, "model_config.create", company=company):
        raise HttpError(403, "You don't have permission to create model configs.")
    if not payload.licence_accepted:
        raise HttpError(400, "You must accept the provider's terms of service.")
    try:
        config = svc.create_model_config(company, request.auth, payload.dict())
    except ValueError as e:
        raise HttpError(400, str(e))
    return _model_config_out(config)


@router.post("/model-configs/check/", response=ModelCheckOut)
def check_model_config(request, payload: ModelCheckIn):
    """
    Verify a model with the provider before the dialog saves it: one tiny
    call through the worker. Whoever may register or edit models may check.
    """
    company = _company(request)
    if not (PermissionChecker.can(request.auth, "model_config.create", company=company)
            or PermissionChecker.can(request.auth, "model_config.update", company=company)):
        raise HttpError(403, "You don't have permission to check model configs.")
    try:
        return svc.check_model_config(company, payload.dict())
    except ValueError as e:
        raise HttpError(400, str(e))
    except svc.WorkerUnavailable as e:
        raise HttpError(e.status, str(e))


@router.get("/model-configs/defaults/", response=dict)
def model_defaults(request, provider: str, model_id: str):
    """
    What the price catalog knows about a model BEFORE it is registered — the
    register dialog prefills Context window and Max reply tokens from this
    (owner's ruling 2026-10-21: defaults live in a DB the daily catalog
    refresh updates, never in a hardcoded table). Unknown → nulls; the dialog
    then falls back to its built-in offline guesses. Exact (provider,
    model_id) first; a bare-id match covers openai_compatible proxies of a
    known model. Same right as the pre-save model check.
    """
    from nucleus.models import ModelPrice
    company = _company(request)
    if not (PermissionChecker.can(request.auth, "model_config.create", company=company)
            or PermissionChecker.can(request.auth, "model_config.update", company=company)):
        raise HttpError(403, "You don't have permission to register models.")
    bare = (model_id or "").strip()
    row = None
    if bare:
        row = (ModelPrice.objects.filter(provider=provider, model_id=bare).first()
               or ModelPrice.objects.filter(model_id=bare).first())
    return {
        "context_window": row.context_window if row else None,
        "max_output_tokens": row.max_output_tokens if row else None,
        "source": row.source if row else None,
    }


@router.patch("/model-configs/{config_id}/", response=ModelConfigOut)
def patch_model_config(request, config_id: str, payload: ModelConfigPatchIn):
    company = _company(request)
    if not PermissionChecker.can(request.auth, "model_config.update", company=company):
        raise HttpError(403, "You don't have permission to edit model configs.")
    try:
        config = svc.update_model_config(company, config_id, payload.dict(exclude_none=True))
    except ValueError as e:
        raise HttpError(400, str(e))
    if not config:
        raise HttpError(404, "Model config not found.")
    utility = svc.utility_model_of(company)
    return _model_config_out(config, str(utility.id) if utility else None)


@router.post("/model-configs/{config_id}/utility/", response=ModelConfigOut)
def set_utility_model(request, config_id: str):
    """Make this config the server's utility model (one per server)."""
    company = _company(request)
    if not PermissionChecker.can(request.auth, "model_config.update", company=company):
        raise HttpError(403, "You don't have permission to choose the utility model.")
    try:
        config = svc.set_utility_model(company, request.auth, config_id)
    except LookupError:
        raise HttpError(404, "Model config not found.")
    return _model_config_out(config, str(config.id))


@router.delete("/model-configs/{config_id}/utility/", response=ModelConfigOut)
def clear_utility_model(request, config_id: str):
    """Stop using this config as the utility model (personas' own models take over)."""
    company = _company(request)
    if not PermissionChecker.can(request.auth, "model_config.update", company=company):
        raise HttpError(403, "You don't have permission to choose the utility model.")
    config = svc.get_model_config(company, config_id)
    if not config:
        raise HttpError(404, "Model config not found.")
    utility = svc.utility_model_of(company)
    if utility and str(utility.id) == config_id:
        svc.set_utility_model(company, request.auth, None)
    return _model_config_out(config, None)


@router.delete("/model-configs/{config_id}/", response={204: None})
def delete_model_config(request, config_id: str):
    company = _company(request)
    if not PermissionChecker.can(request.auth, "model_config.delete", company=company):
        raise HttpError(403, "You don't have permission to delete model configs.")
    try:
        deleted = svc.delete_model_config(company, config_id)
    except ValueError as e:
        raise HttpError(409, str(e))
    if not deleted:
        raise HttpError(404, "Model config not found.")
    return 204, None


# ── ModelConfig <-> Project attachment (visibility gate) ──────────────────────

@router.post("/projects/{project_id}/model-configs/{config_id}/attach/", response={200: dict})
def attach_model_config(request, project_id: str, config_id: str):
    company = _company(request)
    project = Project.objects.filter(company=company, id=project_id, is_active=True).first()
    if not project:
        raise HttpError(404, "Project not found.")
    if not PermissionChecker.can(request.auth, "model_config.attach", obj=project):
        raise HttpError(403, "You don't have permission to attach model configs to this project.")
    if not svc.attach_model_config_to_project(company, config_id, project_id):
        raise HttpError(404, "Model config not found.")
    return {"ok": True}


@router.delete("/projects/{project_id}/model-configs/{config_id}/attach/", response={200: dict})
def detach_model_config(request, project_id: str, config_id: str):
    company = _company(request)
    project = Project.objects.filter(company=company, id=project_id, is_active=True).first()
    if not project:
        raise HttpError(404, "Project not found.")
    if not PermissionChecker.can(request.auth, "model_config.attach", obj=project):
        raise HttpError(403, "You don't have permission to detach model configs from this project.")
    try:
        detached = svc.detach_model_config_from_project(company, config_id, project_id)
    except ValueError as e:
        raise HttpError(409, str(e))
    if not detached:
        raise HttpError(404, "Model config not found.")
    return {"ok": True}


# ── MCPServer endpoints ───────────────────────────────────────────────────────
# mcp_server.list is COMPANY scope (ordinary project members reach the list
# through the visible_mcp_servers() row-visibility fallback, not by holding
# this right directly). create/update/delete are PROJECT scope — a server
# belongs to exactly one project, and that project's own Admin can manage it.

@router.get("/mcp-servers/", response=List[MCPServerOut])
def list_mcp_servers_all(request):
    company = _company(request)
    return [_mcp_out(s) for s in svc.list_mcp_servers_all(company, request.auth)]


@router.post("/mcp-servers/", response=MCPServerOut)
def create_mcp_server_standalone(request, payload: MCPServerIn):
    company = _company(request)
    project = Project.objects.filter(company=company, id=payload.project_id, is_active=True).first()
    if not project:
        raise HttpError(404, "Project not found.")
    if not PermissionChecker.can(request.auth, "mcp_server.create", obj=project):
        raise HttpError(403, "You don't have permission to create MCP servers in this project.")
    try:
        server = svc.create_mcp_server_standalone(company, payload.dict())
    except ValueError as e:
        raise HttpError(400, str(e))
    # Step 6 (change 6): fetch the tool list at attach time, best-effort — a
    # dead/slow server never fails the create; the Refresh button retries.
    ok, reason = _refresh_server_tools(server)
    if not ok:
        import logging
        logging.getLogger(__name__).info("[mcp] tool list not fetched for %s: %s", server.name, reason)
    return _mcp_out(server)


@router.patch("/mcp-servers/{server_id}/", response=MCPServerOut)
def patch_mcp_server_standalone(request, server_id: str, payload: MCPServerPatchIn):
    company = _company(request)
    server = svc.get_mcp_server_standalone(company, server_id)
    if not server:
        raise HttpError(404, "MCP server not found.")
    if not PermissionChecker.can(request.auth, "mcp_server.update", obj=server):
        raise HttpError(403, "You don't have permission to edit this MCP server.")
    try:
        server = svc.update_mcp_server_standalone(company, server_id, payload.dict(exclude_none=True))
    except ValueError as e:
        raise HttpError(400, str(e))
    # Step 6 (change 6): a save may have changed the URL or credentials —
    # refresh the stored list, best-effort.
    _refresh_server_tools(server)
    return _mcp_out(server)


@router.delete("/mcp-servers/{server_id}/", response={204: None})
def delete_mcp_server_standalone(request, server_id: str):
    company = _company(request)
    server = svc.get_mcp_server_standalone(company, server_id)
    if not server:
        raise HttpError(404, "MCP server not found.")
    if not PermissionChecker.can(request.auth, "mcp_server.delete", obj=server):
        raise HttpError(403, "You don't have permission to delete this MCP server.")
    try:
        svc.delete_mcp_server_standalone(company, server_id)
    except ValueError as e:
        raise HttpError(409, str(e))
    return 204, None


# MCPServer has no attach/detach endpoints -- it is single-project-owned via
# a real FK now, assigned once at creation via payload.project_id and not
# transferable. Unlike ModelConfig, which is genuinely shared across projects.


@router.post("/mcp-servers/{server_id}/tools/refresh/", response={200: dict})
def refresh_mcp_server_tools(request, server_id: str):
    """
    Step 6 (change 6): the "Refresh tools" button — re-dial the server through
    the engine and store its current tool list. 502 carries the dial's own
    reason, to show verbatim next to the button.
    """
    company = _company(request)
    server = svc.get_mcp_server_standalone(company, server_id)
    if not server:
        raise HttpError(404, "MCP server not found.")
    if not PermissionChecker.can(request.auth, "mcp_server.update", obj=server):
        raise HttpError(403, "You don't have permission to edit this MCP server.")
    ok, reason = _refresh_server_tools(server)
    if not ok:
        raise HttpError(502, reason)
    return {"tools": server.tools or []}


# ── MCPServer OAuth2 ───────────────────────────────────────────────────────────

@router.get("/mcp-servers/{server_id}/oauth/authorize/", response=MCPOAuthAuthorizeOut)
def mcp_oauth_authorize(request, server_id: str, frontend_origin: str):
    from nucleus.models import MCPServer
    from . import oauth_client

    company = _company(request)
    server = svc.get_mcp_server_standalone(company, server_id)
    if not server:
        raise HttpError(404, "MCP server not found.")
    if not PermissionChecker.can(request.auth, "mcp_server.update", obj=server):
        raise HttpError(403, "You don't have permission to connect this MCP server.")
    if server.auth_type != MCPServer.AuthType.OAUTH2:
        raise HttpError(400, "This MCP server is not configured for OAuth2.")
    # Step 6 Part C: the dynamic-registration road. When nothing is pasted,
    # discover the server's OAuth metadata and register this install as a
    # public client, right now, on the Connect click. Pasted/preset configs
    # (client_id + endpoints already present) pass straight through.
    ok, reason = oauth_client.ensure_client(server)
    if not ok:
        raise HttpError(502, reason)
    return {"authorize_url": oauth_client.build_authorize_url(server, frontend_origin)}


@router.get("/mcp-servers/oauth/callback/", auth=None)
def mcp_oauth_callback(request, code: str = None, state: str = None, error: str = None):
    """
    Public -- the OAuth provider redirects the browser here directly, no
    Authorization header available. Returns a tiny self-closing HTML page
    that posts the result back to window.opener (standard OAuth popup
    pattern) -- there's no frontend route for this at all.
    """
    from django.core import signing
    from django.http import HttpResponse
    from . import oauth_client
    import json

    def html(ok: bool, origin: str | None, err: str = "", server_id: str = "") -> HttpResponse:
        payload = json.dumps({"type": "mcp-oauth-result", "ok": ok, "server_id": server_id, "error": err})
        target = json.dumps(origin) if origin else "'*'"
        body = "Connected. You can close this window." if ok else f"Connection failed: {err}"
        return HttpResponse(
            f"<!doctype html><html><body><script>"
            f"if (window.opener) {{ window.opener.postMessage({payload}, {target}); }}"
            f"window.close();</script>{body}</body></html>"
        )

    if error or not code or not state:
        return html(False, None, err=error or "missing_code")
    try:
        result = oauth_client.complete_callback(code, state)
    except (signing.BadSignature, ValueError) as exc:
        return html(False, None, err=str(exc))
    return html(True, result["frontend_origin"], server_id=result["server_id"])


# ── Persona endpoints ─────────────────────────────────────────────────────────
# persona.list is COMPANY scope; create/update/delete are PROJECT scope --
# a persona belongs to exactly one project and that project's own Admin
# manages it. Distinct from "persona.mention" (TOPIC-scoped, chat/api.py).

@router.get("/personas/", response=List[PersonaOut])
def list_personas(request, project_id: str):
    """
    Personas are project-owned -- always listed for one project, never
    company-wide. Visibility is via visible_personas().
    """
    company = _company(request)
    project = Project.objects.filter(company=company, id=project_id, is_active=True).first()
    if not project:
        raise HttpError(404, "Project not found.")
    return [_persona_out(p) for p in svc.list_personas(project, request.auth)]


@router.post("/personas/", response=PersonaOut)
def create_persona(request, payload: PersonaIn):
    company = _company(request)
    project = Project.objects.filter(company=company, id=payload.project_id, is_active=True).first()
    if not project:
        raise HttpError(404, "Project not found.")
    if not PermissionChecker.can(request.auth, "persona.create", obj=project):
        raise HttpError(403, "You don't have permission to create personas in this project.")
    try:
        persona = svc.create_persona(company, request.auth, payload.dict())
    except ValueError as e:
        raise HttpError(400, str(e))
    return _persona_out(persona)


@router.patch("/personas/{persona_id}/", response=PersonaOut)
def patch_persona(request, persona_id: str, payload: PersonaPatchIn):
    company = _company(request)
    persona_obj = Persona.objects.filter(
        company=company, id=persona_id, is_active=True
    ).select_related("project").first()
    if not persona_obj:
        raise HttpError(404, "Persona not found.")
    if not PermissionChecker.can(request.auth, "persona.update", obj=persona_obj.project):
        raise HttpError(403, "You don't have permission to edit this persona.")

    # exclude_none keeps `mcp_server_ids: []` (detach all) distinct from
    # "not sent", which is why clear_advisor exists as a separate flag --
    # a nullable FK has no equivalent distinct value.
    data = payload.dict(exclude_none=True)
    try:
        persona = svc.patch_persona(company, persona_id, data)
    except ValueError as e:
        raise HttpError(400, str(e))
    if not persona:
        raise HttpError(404, "Persona not found.")
    return _persona_out(persona)


@router.delete("/personas/{persona_id}/", response={204: None})
def delete_persona(request, persona_id: str):
    company = _company(request)
    persona_obj = Persona.objects.filter(
        company=company, id=persona_id, is_active=True
    ).select_related("project").first()
    if not persona_obj:
        raise HttpError(404, "Persona not found.")
    if not PermissionChecker.can(request.auth, "persona.delete", obj=persona_obj.project):
        raise HttpError(403, "You don't have permission to delete this persona.")

    svc.delete_persona(company, persona_id)
    return 204, None


# ── PromptTemplate endpoints ──────────────────────────────────────────────────

# ── Routine endpoints (W4) ───────────────────────────────────────────────────
def _routine_out(routine) -> RoutineOut:
    return RoutineOut(
        id=str(routine.id), project_id=str(routine.project_id), name=routine.name, title=routine.title,
        purpose=routine.purpose or "", instructions=routine.instructions, allowed_capabilities=routine.allowed_capabilities,
        model=_model_config_ref(routine.model_config) if routine.model_config_id and routine.model_config and routine.model_config.is_active else None,
        is_builtin=routine.is_builtin, created_by_id=str(routine.created_by_id) if routine.created_by_id else None,
    )


def _routine_project(request, project_id: str, right: str):
    """The project a routine route acts on, under `right` -- 404 when it is not this company's."""
    company = _company(request)
    project = Project.objects.filter(company=company, id=project_id, is_active=True).first()
    if not project:
        raise HttpError(404, "Project not found.")
    if not PermissionChecker.can(request.auth, right, obj=project):
        raise HttpError(403, "You don't have permission to manage routines here." if right == "routine.manage" else "You don't have access to this project.")
    return company, project


@router.get("/projects/{project_id}/routines/", response=List[RoutineOut])
def list_routines(request, project_id: str):
    """Whoever reads the project sees what `/` offers; defining routines is routine.manage."""
    _company_, project = _routine_project(request, project_id, "topic.list")
    return [_routine_out(r) for r in svc.list_routines(project)]


@router.post("/projects/{project_id}/routines/", response=RoutineOut)
def create_routine(request, project_id: str, payload: RoutineIn):
    company, project = _routine_project(request, project_id, "routine.manage")
    try:
        return _routine_out(svc.create_routine(company, project, request.auth, payload.dict()))
    except ValueError as e:
        raise HttpError(400, str(e))


@router.patch("/projects/{project_id}/routines/{routine_id}/", response=RoutineOut)
def patch_routine(request, project_id: str, routine_id: str, payload: RoutinePatchIn):
    company, project = _routine_project(request, project_id, "routine.manage")
    try:
        routine = svc.patch_routine(company, project, routine_id, payload.dict(exclude_none=True))
    except ValueError as e:
        raise HttpError(400, str(e))
    if not routine:
        raise HttpError(404, "Routine not found.")
    return _routine_out(routine)


@router.delete("/projects/{project_id}/routines/{routine_id}/", response={204: None})
def delete_routine(request, project_id: str, routine_id: str):
    """A built-in is editable but stays -- every project has the four."""
    _company_, project = _routine_project(request, project_id, "routine.manage")
    routine = svc.get_routine(project, routine_id)
    if not routine:
        raise HttpError(404, "Routine not found.")
    if routine.is_builtin:
        raise HttpError(409, "Built-in routines can be edited but not deleted.")
    svc.delete_routine(project, routine_id)
    return 204, None


@router.get("/prompt-templates", response=ListTemplatePrompts)
def get_prompts(request):
    files = {
        base64.urlsafe_b64encode(rel_path.encode()).decode().rstrip('='): rel_path
        for f in PROMPTS_DIR.rglob('*') if f.is_file()
        for rel_path in [str(f.relative_to(PROMPTS_DIR))]
    }
    return ListTemplatePrompts(prompts=files)


@router.get("/prompt-templates/{id}", response=TemplatePromptContent)
def get_prompt(request, id: str):
    try:
        padding_needed = 4 - (len(id) % 4)
        padded_id = id + ("=" * padding_needed)

        rel_path_str = base64.urlsafe_b64decode(padded_id).decode()

        target_path = (PROMPTS_DIR / rel_path_str).resolve()

        if not target_path.is_relative_to(PROMPTS_DIR) or not target_path.is_file():
            raise HttpError(404, "File not found")

        return TemplatePromptContent(content=target_path.read_text(encoding="utf-8"))

    except (ValueError, binascii.Error, UnicodeDecodeError):
        raise HttpError(400, "Invalid file ID format")


# ── CompanyAIConfig endpoints ─────────────────────────────────────────────────

def _ai_config_out(config) -> CompanyAIConfigOut:
    utility = config.utility_model if config.utility_model_id else None
    return CompanyAIConfigOut(
        embedding_provider=config.embedding_provider,
        embedding_model=config.embedding_model,
        embedding_base_url=config.embedding_base_url,
        default_llm_model=config.default_llm_model,
        utility_model_id=str(utility.id) if utility and utility.is_active else None,
    )


@router.get("/ai-config/", response=CompanyAIConfigOut)
def get_ai_config(request):
    company = _company(request)
    return _ai_config_out(svc.get_ai_config(company))


@router.put("/ai-config/", response=CompanyAIConfigOut)
def update_ai_config(request, payload: CompanyAIConfigIn):
    company = _company(request)
    # Server-wide model settings are model-config editing; this route had no
    # gate at all before the utility model joined it.
    if not PermissionChecker.can(request.auth, "model_config.update", company=company):
        raise HttpError(403, "You don't have permission to edit the server's AI settings.")
    return _ai_config_out(svc.update_ai_config(company, request.auth, payload.dict()))


@router.get("/ai-request-logs/", response=List[AIRequestLogOut])
def list_ai_request_logs(request):
    """Return the last 200 AI request logs, newest first (legacy shape).

    1.3.0: now gated. This lists raw prompts and responses across the WHOLE
    company, and before the audit work it was readable by anyone signed in.
    A project-scoped admin uses /audit/ below; this company-wide view needs
    the right held at company reach."""
    company = _company(request)
    if not PermissionChecker.can(request.auth, "project.audit", company=company):
        raise HttpError(403, "You don't have permission to read the AI audit log.")
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


# ── AI audit log (1.3.0) ──────────────────────────────────────────────────────
# "How was this reply's prompt built?" — per project, filterable to one topic
# or one message. Gated on project.audit (Admin-tier) because the rows carry
# the project brief, persona system prompts, retrieval snippets and raw model
# output.

def _audit_entry(log, persona_names: dict, detail: bool = False):
    base = dict(
        id=str(log.id),
        created_at=log.created_at.isoformat(),
        msg_id=log.msg_id,
        topic_id=log.topic_id or "",
        persona_id=str(log.persona_id) if log.persona_id else None,
        persona_name=persona_names.get(log.persona_id, ""),
        role=log.role or "",
        provider=log.provider,
        model_id=log.model_id,
        model_name=log.model_name or "",
        status=log.status,
        latency_ms=log.latency_ms,
        prompt_tokens=log.prompt_tokens,
        completion_tokens=log.completion_tokens,
        error=log.error,
    )
    if not detail:
        return AuditEntryOut(**base)
    return AuditEntryDetailOut(**base, breakdown=log.breakdown or {}, response=log.response or "")


def _audit_project(request, project_id: str):
    company = _company(request)
    project = Project.objects.filter(company=company, id=project_id, is_active=True).first()
    if not project:
        raise HttpError(404, "Project not found.")
    if not PermissionChecker.can(request.auth, "project.audit", obj=project):
        raise HttpError(403, "You don't have permission to read this project's AI audit log.")
    return company, project


def _persona_names(logs) -> dict:
    ids = {log.persona_id for log in logs if log.persona_id}
    if not ids:
        return {}
    return {p.id: p.name for p in Persona.objects.filter(id__in=ids)}


@router.get("/projects/{project_id}/audit/", response=List[AuditEntryOut])
def list_audit_entries(request, project_id: str,
                       topic_id: Optional[str] = None,
                       msg_id: Optional[str] = None,
                       limit: int = 50):
    """Newest first. Summary rows only — the anatomy rides on the detail route."""
    _company_, project = _audit_project(request, project_id)
    qs = AIRequestLog.objects.filter(project=project)
    if topic_id:
        qs = qs.filter(topic_id=topic_id)
    if msg_id:
        qs = qs.filter(msg_id=msg_id)
    logs = list(qs.order_by("-created_at")[: max(1, min(limit, 200))])
    names = _persona_names(logs)
    return [_audit_entry(log, names) for log in logs]


class AuditInvestigateIn(Schema):
    question: str
    model_config_id: str
    topic_id: Optional[str] = None
    msg_id: Optional[str] = None
    limit: int = 20


@router.post("/projects/{project_id}/audit/investigate/", response=dict)
def investigate_audit_route(request, project_id: str, payload: AuditInvestigateIn):
    """1.3.0 "investigate with a model" — must register BEFORE the {log_id}
    route below, whose regex also matches /audit/investigate/. The real body
    (investigate_audit) lives with its helpers further down."""
    return investigate_audit(request, project_id, payload)


@router.get("/projects/{project_id}/audit/export/")
def export_audit_topic(request, project_id: str, topic_id: str):
    """The whole topic's AI log as ONE markdown story (owner's ruling
    2026-10-31) — a download. Same gate as every audit route (project.audit,
    Admin-tier: the file carries everyone's prompts), the topic must belong
    to this project, credentials are masked (audit_export.redact), and the
    download itself is logged — who took a copy of which topic, when.
    Registered BEFORE the {log_id} route, whose regex also matches /export/."""
    from django.http import HttpResponse

    from nucleus.models import ChatTopic

    from .audit_export import build_topic_story

    _company_, project = _audit_project(request, project_id)
    try:
        topic = (ChatTopic.objects.filter(id=topic_id, project=project)
                 .select_related("channel").first())
    except Exception:  # noqa: BLE001 — not a UUID
        topic = None
    if not topic:
        raise HttpError(404, "Topic not found in this project.")
    filename, body = build_topic_story(project, topic, user=request.auth)
    logger.info("[audit] AI log exported: project=%s topic=%s by=%s (%d bytes)",
                project.id, topic.id, getattr(request.auth, "email", request.auth), len(body))
    response = HttpResponse(body, content_type="text/markdown; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@router.get("/projects/{project_id}/audit/{log_id}/", response=AuditEntryDetailOut)
def get_audit_entry(request, project_id: str, log_id: str):
    """One run in full: the prompt anatomy (breakdown) + the raw response."""
    _company_, project = _audit_project(request, project_id)
    log = AIRequestLog.objects.filter(project=project, id=log_id).first()
    if not log:
        raise HttpError(404, "Audit entry not found.")
    names = _persona_names([log])
    return _audit_entry(log, names, detail=True)


# ── "Investigate with a model" (1.3.0's deferred half) ────────────────────
# Ask a model questions ABOUT the log, from inside the audit dialog. Same
# right as reading the log (the model sees exactly what the admin may read);
# the model must be attached to the project (the chain-model-step rule); the
# answer is EPHEMERAL — never stored, never a chat message — and the call
# bills like a chain model step (kind=chat_reply, source=audit_investigate).

_INVESTIGATE_FIELD_CAP = 2_000     # chars per section/response text
_INVESTIGATE_TOTAL_CAP = 80_000    # chars of log the prompt may carry
_INVESTIGATE_RUNS_MAX = 50


def _clip(text: str, cap: int = _INVESTIGATE_FIELD_CAP) -> str:
    text = text or ""
    return text if len(text) <= cap else text[: cap - 1] + "…"


def _investigate_text(logs, names) -> tuple[str, int]:
    """The runs as prompt text, oldest first; stops at the total cap so one
    giant retrieval dump cannot blow the model's window. Returns (text, how
    many runs made it in — the NEWEST survive, older ones drop first)."""
    blocks: list[str] = []
    total = 0
    for n, log in enumerate(reversed(logs), 1):  # newest first while capping
        b = log.breakdown or {}
        lines = [
            f"--- run · {log.created_at.isoformat()} · @{names.get(log.persona_id, '') or 'unknown'}"
            f" · {log.provider}:{log.model_id} · seat {log.role or 'STANDARD'} · status {log.status}"
            f" · tokens {log.prompt_tokens or 0}/{log.completion_tokens or 0} · {log.latency_ms or 0} ms"
            f" · msg {log.msg_id} · topic {log.topic_id or '-'}",
        ]
        if b.get("message"):
            lines.append(f"the user's message: {_clip(str(b['message']))}")
        for section in b.get("sections") or []:
            kind = section.get("kind", "?")
            lines.append(f"[section {kind} · {section.get('chars', 0)} ch]\n{_clip(str(section.get('text') or ''))}")
        if b.get("extra_instructions"):
            lines.append(f"[extra instructions]\n{_clip(str(b['extra_instructions']))}")
        retrieved = b.get("retrieval") or []
        if retrieved:
            lines.append("retrieval: " + "; ".join(
                f"{r.get('label', '?')} ({r.get('score', '?')}, {r.get('kind', '?')})" for r in retrieved[:20]))
        if b.get("history_count") is not None:
            lines.append(f"history messages sent: {b.get('history_count')}"
                         + (" · resumed run" if b.get("resume") else "")
                         + (f" · fallback attempt {b.get('fallback_attempt')}" if b.get("fallback_attempt") else ""))
        if log.response:
            lines.append(f"the model's response:\n{_clip(log.response)}")
        if log.error:
            lines.append(f"error: {_clip(log.error, 500)}")
        block = "\n".join(lines)
        if total + len(block) > _INVESTIGATE_TOTAL_CAP and blocks:
            blocks.append(f"(… {len(logs) - n + 1} older run(s) omitted — over the size cap)")
            break
        blocks.append(block)
        total += len(block)
    blocks.reverse()  # back to oldest-first for the model
    omitted = blocks and blocks[-1].startswith("(…")
    runs_in = len(blocks) - (1 if omitted else 0)
    if omitted:
        blocks.insert(0, blocks.pop())  # the omission note reads first
    return "\n\n".join(blocks), runs_in


# Registered up at the audit listing (BEFORE the {log_id} route — Django
# resolves URLs in order, and "investigate" matches {log_id}'s regex, which
# answered 405 to the POST). The body lives here with its helpers.
def investigate_audit(request, project_id: str, payload: AuditInvestigateIn):
    """Ask a model about this project's audit log. Ephemeral: the answer goes
    back to the asker and nowhere else."""
    company, project = _audit_project(request, project_id)
    question = (payload.question or "").strip()
    if not question:
        raise HttpError(400, "Ask a question.")
    if len(question) > 4_000:
        raise HttpError(400, "The question is over 4,000 characters.")
    config = ModelConfig.objects.filter(id=payload.model_config_id, company=company, is_active=True).first()
    if not config:
        raise HttpError(404, "Model not found.")
    if not config.projects.filter(id=project.id, is_active=True).exists():
        raise HttpError(400, "That model is not attached to this project — attach it first.")

    qs = AIRequestLog.objects.filter(project=project)
    if payload.topic_id:
        qs = qs.filter(topic_id=payload.topic_id)
    if payload.msg_id:
        qs = qs.filter(msg_id=payload.msg_id)
    logs = list(qs.order_by("-created_at")[: max(1, min(payload.limit or 20, _INVESTIGATE_RUNS_MAX))])
    if not logs:
        raise HttpError(404, "No audit entries in this scope yet.")
    names = _persona_names(logs)
    log_text, runs_in = _investigate_text(logs, names)

    prompt = (
        f'You are examining the AI AUDIT LOG of the project "{project.name}" — the recorded '
        "anatomy of how each AI reply was built: the prompt sections sent, the retrieval hits, "
        "the models and seats, tokens, latency and how each run ended. Answer the question "
        "using ONLY this log. Be concrete (name runs by their time and persona); when the log "
        "cannot answer, say so plainly rather than guessing.\n\n"
        f"=== THE LOG ({runs_in} run(s), oldest first) ===\n{log_text}\n\n"
        f"=== THE QUESTION ===\n{question}"
    )
    from chat.nexus_ai import NexusAIClient
    try:
        out = NexusAIClient().transform({
            "provider": config.provider, "model_id": config.model_id,
            "api_key": config.get_api_key(), "api_base": config.api_base,
            "prompt": prompt,
            "max_tokens": config.max_output_tokens, "temperature": 0.2,
        })
    except Exception:  # noqa: BLE001 — an unreachable engine is a 502, not a stack trace
        raise HttpError(502, "The server could not reach the model.")
    if not out.get("ok"):
        raise HttpError(502, f"The model could not answer ({out.get('error_code') or 'error'}).")
    usage = out.get("usage") or {}
    _record_investigate_usage(company, project, config, request.auth, payload.topic_id or "", usage)
    return {
        "answer": out.get("text") or "",
        "runs_examined": runs_in,
        "model_name": config.name,
        "usage": {"prompt_tokens": usage.get("input_tokens"), "output_tokens": usage.get("output_tokens")},
    }


def _record_investigate_usage(company, project, config, user, topic_id: str, usage: dict) -> None:
    """Billed like a chain model step; billing must never fail the answer."""
    try:
        from django.utils import timezone

        from intelligence.pricing import price_record
        from nucleus.models import UsageRecord

        record = {
            "company_id": str(company.id), "project_id": str(project.id),
            "topic_id": topic_id, "persona_id": "",
            "user_id": str(user.id),
            "message_id": "", "job_id": f"audit-investigate:{project.id}",
            "kind": "chat_reply", "model_config_id": str(config.id),
            "provider": config.provider, "model_id": config.model_id, "role": "STANDARD",
            "provider_response_id": usage.get("provider_response_id"),
            "source": "audit_investigate",
            "input_tokens": int(usage.get("input_tokens") or 0),
            "uncached_input_tokens": int(usage.get("uncached_input_tokens") or 0),
            "cache_read_tokens": int(usage.get("cache_read_tokens") or 0),
            "cache_write_5m_tokens": int(usage.get("cache_write_5m_tokens") or 0),
            "cache_write_1h_tokens": int(usage.get("cache_write_1h_tokens") or 0),
            "output_tokens": int(usage.get("output_tokens") or 0),
            "reasoning_tokens": int(usage.get("reasoning_tokens") or 0),
            "finish_reason": usage.get("finish_reason"),
            "estimated": bool(usage.get("estimated")),
            "called_at": timezone.now(),
        }
        UsageRecord.objects.create(**{**record, **price_record(record)})
    except Exception:  # noqa: BLE001
        logger.exception("[audit] could not record the investigate call's usage")


# ── Output Types (M7) ─────────────────────────────────────────────────────────

# ── Catalogues (W11 tool catalog, W18 persona catalogue) ─────────────────────
# Static content, served so the app can pre-fill the dialogs a person already
# uses. Nothing is created here and nothing is fetched at runtime.

@router.get("/mcp-catalog/", response=List[MCPCatalogEntryOut])
def mcp_catalog(request):
    """Tool servers worth adding. Reading it needs the right that lists servers."""
    company = _company(request)
    if not PermissionChecker.can(request.auth, "mcp_server.list", obj=company):
        raise HttpError(403, "You don't have permission to see tool servers.")
    return mcp_catalog_content.catalog()


@router.get("/persona-catalog/", response=List[PersonaCatalogEntryOut])
def persona_catalog(request):
    """Roles a team usually wants. Reading it needs the right that lists personas."""
    company = _company(request)
    if not PermissionChecker.can(request.auth, "persona.list", obj=company):
        raise HttpError(403, "You don't have permission to see personas.")
    return persona_catalog_content.catalog()


@router.get("/model-presets/", response=List[ModelPresetOut])
def model_presets(request):
    """Free-LLM onboarding WP1: the "Free to start" tiles for /add-model.
    Content like the other catalogues; reading it needs the right that lists
    models. Nothing here is a credential — the person brings their own key."""
    company = _company(request)
    if not PermissionChecker.can(request.auth, "model_config.list", obj=company):
        raise HttpError(403, "You don't have permission to see models.")
    return model_presets_content.catalog()


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


# REMOVED (owner's ruling 2026-10-22): Recall endpoints (W5) — gone with 0042 ────────────────────────────────────────────────────
# (the _recall_out/_recall_project helpers and the three routes were here)
