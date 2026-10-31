"""
Step 6 (docs/NUCLEUS-REVAMP.md) — the gateway's five tools.

Every tool runs AS a real person: the MCP endpoint resolved a user (personal
token, or internal key + user id) before anything here runs, and each tool
enforces the SAME visibility and rights the app's own endpoints use — the
gateway is a thin front door over existing roads, never new business logic
(owner's rule, handoff change 13.1).

An invisible thing answers like a nonexistent one, same as the app.
"""
from __future__ import annotations

import asyncio
import logging

from asgiref.sync import sync_to_async
from django.conf import settings

logger = logging.getLogger(__name__)

SEARCH_LIMIT = 8


class GatewayToolError(Exception):
    """A refused tool call; the message goes back to the MCP client verbatim."""


def _company():
    from workspace.services import get_company

    company = get_company()
    if not company:
        raise GatewayToolError("This server is not set up yet.")
    return company


def _find_topic(user, topic_id: str):
    """(company, project, topic) — the same row visibility chat uses."""
    from nucleus.models import ChatTopic
    from workspace import services as ws_svc
    from workspace.api import ws_visible_topic

    company = _company()
    try:
        topic = ChatTopic.objects.filter(id=topic_id, is_active=True).select_related("project").first()
    except Exception:  # noqa: BLE001 — a malformed id is just "no such topic"
        topic = None
    if not topic:
        raise GatewayToolError("No such topic.")
    project = ws_svc.get_project(company, user, str(topic.project_id))
    if not project or not ws_visible_topic(user, project, topic_id):
        raise GatewayToolError("No such topic.")
    return company, project, topic


# ── the five tools ──────────────────────────────────────────────────────────

async def list_projects(user) -> list[dict]:
    def _run():
        from workspace import services as ws_svc

        company = _company()
        return [
            {"id": str(p.id), "name": p.name, "description": p.description or ""}
            for p in ws_svc.list_projects(company, user)
        ]
    return await sync_to_async(_run)()


async def list_topics(user, project_id: str) -> list[dict]:
    def _run():
        from workspace import services as ws_svc

        company = _company()
        project = ws_svc.get_project(company, user, project_id)
        if not project:
            raise GatewayToolError("No such project.")
        out = []
        for channel in ws_svc.list_channels(user, project):
            for topic in ws_svc.list_topics(user, channel):
                out.append({
                    "id": str(topic.id), "title": topic.title,
                    "channel": channel.name, "project_id": str(project.id),
                })
        return out
    return await sync_to_async(_run)()


async def post_message(user, topic_id: str, content: str) -> dict:
    """A plain human message — no AI reply (ask_persona is the trigger road)."""
    from chat import services as chat_svc

    content = (content or "").strip()
    if not content:
        raise GatewayToolError("content is empty.")
    company, project, topic = await sync_to_async(_find_topic)(user, topic_id)
    msg = await sync_to_async(chat_svc.save_user_message)(
        company=company, project=project, topic=topic, user=user, content=content,
    )
    asyncio.create_task(chat_svc.publish_async(chat_svc.topic_channel(topic_id), msg))
    return {"ok": True, "message_id": msg["id"], "topic_id": topic_id}


async def ask_persona(user, topic_id: str, persona_name: str, message: str) -> dict:
    """
    Ask one of the project's personas and WAIT for the reply — the same trigger
    road chat uses (rights, reindex fence, queue-per-topic, relay). Past the
    timeout the reply keeps running and the answer says where to read it.
    """
    from authn.permissions.checker import PermissionChecker
    from chat import services as chat_svc
    from intelligence import services as intel_svc

    message = (message or "").strip()
    if not message:
        raise GatewayToolError("message is empty.")
    company, project, topic = await sync_to_async(_find_topic)(user, topic_id)

    if not await sync_to_async(PermissionChecker.can)(user, "persona.mention", obj=topic):
        raise GatewayToolError("You can't call personas in this topic.")
    if getattr(project, "reindex_status", "") == "building":
        raise GatewayToolError(
            "This project's memory is being rebuilt right now; try again once it finishes.")
    persona = await sync_to_async(intel_svc.get_persona_by_mention)(project, persona_name)
    if not persona or not persona.model_id:
        raise GatewayToolError(f"No persona named {persona_name!r} in this project.")

    msg = await sync_to_async(chat_svc.save_user_message)(
        company=company, project=project, topic=topic, user=user,
        content=f"@{persona.name} {message}",
    )
    asyncio.create_task(chat_svc.publish_async(chat_svc.topic_channel(topic_id), msg))

    run = asyncio.create_task(chat_svc.trigger_ai_response_async(
        company=company, project=project, topic=topic, persona=persona,
        user_message=message, user_message_id=msg["id"], topic_id=topic_id,
        output_type="auto", routine=None, triggered_by=user,
    ))
    timeout = int(getattr(settings, "GATEWAY_ASK_TIMEOUT_SECONDS", 180))
    done, _pending = await asyncio.wait({run}, timeout=timeout)
    if not done:
        # NOT cancelled — the relay finishes the reply into the topic.
        return {"status": "working", "topic_id": topic_id,
                "note": f"{persona.name} is still working — the reply will land in the topic."}

    reply = await sync_to_async(_newest_reply)(topic_id, str(persona.id), msg["sequence"])
    if not reply:
        return {"status": "unknown", "topic_id": topic_id,
                "note": "The run ended but no reply row was found — check the topic."}
    return reply


def _newest_reply(topic_id: str, persona_id: str, after_sequence: int) -> dict | None:
    from nucleus.models import ChatMessage

    row = (
        ChatMessage.objects
        .filter(topic_id=topic_id, sequence__gt=after_sequence, metadata__persona_id=persona_id)
        .order_by("-sequence")
        .first()
    )
    if not row:
        return None
    out = {
        "status": row.status,
        "message_id": str(row.id),
        "topic_id": topic_id,
        "persona": (row.metadata or {}).get("persona_name") or "",
        "content": row.content or "",
    }
    if row.status == ChatMessage.Status.PAUSED:
        out["note"] = ("The persona paused for an approval or a question — "
                       "answer it in the app; the reply then continues.")
    elif row.status == ChatMessage.Status.FAILED:
        out["note"] = "The reply failed — the content carries what the reader would see."
    return out


async def search_memory(user, query: str, project_id: str | None = None) -> list[dict]:
    """The same two-half search chat uses (W19): the engine ranks by meaning,
    nucleus filters by what THIS person may see; literal fallback when the
    engine can't answer."""
    from chat import search as search_svc
    from workspace import services as ws_svc

    query = (query or "").strip()
    if not query:
        raise GatewayToolError("query is empty.")

    def _scope():
        company = _company()
        if project_id:
            project = ws_svc.get_project(company, user, project_id)
            if not project:
                raise GatewayToolError("No such project.")
            projects = [str(project.id)]
        else:
            projects = [str(p.id) for p in ws_svc.list_projects(company, user)]
        return company, projects, search_svc.visible_topic_ids(user, company)

    company, project_ids, topic_ids = await sync_to_async(_scope)()
    if not topic_ids:
        return []
    try:
        ranked = await search_svc.semantic_ids(
            company, query[:search_svc.QUERY_MAX], project_ids, SEARCH_LIMIT)
    except Exception:  # noqa: BLE001 — search never fails the tool call
        ranked = []
    if ranked:
        rows = await sync_to_async(lambda: list(search_svc._rows(ranked, topic_ids)))()
        ordered = search_svc.order_by(ranked, rows)
    else:
        ordered = await sync_to_async(search_svc.literal)(query, topic_ids, SEARCH_LIMIT)
    return [search_svc._result(m, query) for m in ordered[:SEARCH_LIMIT]]


# ── chains (Step 7, ruling 6: the workflow MCP is these tools on the SAME door,
#    same tokens, same rights-as-the-person — never a separate server) ───────

async def list_chains(user, project_id: str) -> list[dict]:
    """The chains (runbooks) of one project — the same right the app's list uses."""
    def _run():
        from authn.permissions.checker import PermissionChecker
        from scheduling import runbooks
        from workspace import services as ws_svc

        company = _company()
        project = ws_svc.get_project(company, user, project_id)
        if not project or not PermissionChecker.can(user, "topic.list", obj=project):
            raise GatewayToolError("No such project.")
        return [
            {"id": r["id"], "title": r["title"], "description": r["description"],
             "steps": len(r["steps"]), "supervisor": r["supervisor_name"],
             "has_checkpoint": r["has_checkpoint"]}
            for r in runbooks.serialise_runbooks(runbooks.list_runbooks(project))
        ]
    return await sync_to_async(_run)()


async def run_chain(user, chain_id: str, topic_id: str, query: str = "") -> dict:
    """Start a chain in a topic — exactly the app's start road: runbook.run +
    persona.mention, the caller is the starter and the actor of every step.
    Chains v2 (ruling 3): `query` is the run's task — every step sees it."""
    def _run():
        from authn.permissions.checker import PermissionChecker
        from scheduling import runbooks
        from scheduling.tasks import run_runbook

        company, project, topic = _find_topic(user, topic_id)
        runbook = runbooks.get_runbook(project, chain_id)
        if not runbook:
            raise GatewayToolError("No such chain in that topic's project.")
        if not (runbook.steps or []):
            raise GatewayToolError("This chain has no steps yet — edit it in the app first.")
        if len((query or "").strip()) > runbooks.QUERY_MAX:
            raise GatewayToolError(f"A chain's query is at most {runbooks.QUERY_MAX:,} characters.")
        if not PermissionChecker.can(user, "runbook.run", obj=project):
            raise GatewayToolError("You can't run chains in this project.")
        if not PermissionChecker.can(user, "persona.mention", obj=topic):
            raise GatewayToolError("You can't call personas in this topic.")
        run = runbooks.start_run(company, project, runbook, user, topic, query=(query or "").strip())
        run_runbook.delay(str(run.id))
        return {"run_id": str(run.id), "status": "queued", "topic_id": topic_id,
                "note": "The chain runs in the topic; chain_status follows it."}
    return await sync_to_async(_run)()


# ── admin tools (1.4.0 setup copilot — the owner's list, ruled 2026-10-22
#    19:27). Same doctrine as everything above: a thin front door over the
#    EXACT roads the dialogs use — same services, same rights, checked as the
#    calling person; never a master user, never new business logic.
#    An api_key travels ONLY as a tool argument: it is never echoed back in a
#    result (results carry has_api_key, like the REST API) and tool arguments
#    are never logged. create_model/update_model run the dialogs' pre-save
#    provider check; a model that cannot answer is refused, not saved. ──────

def _model_summary(config, utility_id: str | None = None) -> dict:
    """A model row WITHOUT its key — has_api_key only, like ModelConfigOut."""
    return {
        "id": str(config.id), "name": config.name, "provider": config.provider,
        "model_id": config.model_id, "qualified_id": config.qualified_id,
        "api_base": config.api_base, "context_window": config.context_window,
        "max_output_tokens": config.max_output_tokens, "temperature": config.temperature,
        "routing_notes": config.routing_notes or "",
        "supports_tools": config.supports_tools,
        "has_api_key": bool(config.api_key_encrypted),
        "is_utility": str(config.id) == (utility_id or ""),
        "project_ids": [str(pid) for pid in config.projects.filter(is_active=True).values_list("id", flat=True)],
    }


def _run_model_check(company, provider: str, model_id: str,
                     api_key: str | None, api_base: str | None,
                     config_id: str | None = None) -> dict:
    """The dialogs' pre-save provider check, verbatim: ok → latency; a model
    that cannot answer, a bad id, or a missing worker all REFUSE the save."""
    from intelligence import services as intel_svc

    try:
        res = intel_svc.check_model_config(company, {
            "provider": provider, "model_id": model_id,
            "api_key": api_key or None, "api_base": api_base or None,
            "config_id": config_id,
        })
    except ValueError as exc:
        raise GatewayToolError(str(exc))
    except intel_svc.WorkerUnavailable as exc:
        raise GatewayToolError(f"The model could not be checked — {exc} Nothing was saved.")
    data = res if isinstance(res, dict) else res.dict()
    if not data.get("ok"):
        raise GatewayToolError(data.get("reason") or "The model could not be used — nothing was saved.")
    return data


async def list_models(user) -> list[dict]:
    """Every model config this person's road shows — never a key."""
    def _run():
        from intelligence import services as intel_svc

        company = _company()
        utility = intel_svc.utility_model_of(company)
        utility_id = str(utility.id) if utility else None
        return [_model_summary(m, utility_id) for m in intel_svc.list_model_configs(company, user)]
    return await sync_to_async(_run)()


async def create_model(user, name: str, provider: str, model_id: str,
                       accept_provider_terms: bool = False,
                       api_key: str = "", api_base: str = "",
                       context_window: int | None = None,
                       max_output_tokens: int | None = None,
                       temperature: float | None = None,
                       routing_notes: str = "", supports_tools: bool = True,
                       description: str = "") -> dict:
    """Register a model — the Register dialog's road: right, terms, the
    provider check, then the save. The key is encrypted at rest and never
    returned; the result says has_api_key only."""
    def _run():
        from authn.permissions.checker import PermissionChecker
        from intelligence import services as intel_svc
        from intelligence.schema import ModelConfigIn

        company = _company()
        if not PermissionChecker.can(user, "model_config.create", company=company):
            raise GatewayToolError("You don't have permission to create model configs.")
        if not accept_provider_terms:
            raise GatewayToolError(
                "You must accept the model provider's terms of service — ask the person, "
                "then pass accept_provider_terms=true. Nothing was saved.")
        check = _run_model_check(company, provider, model_id, api_key, api_base)
        fields = {
            "name": name, "provider": provider, "model_id": model_id,
            "api_key": api_key or None, "api_base": api_base or None,
            "description": description or None, "licence_accepted": True,
            "routing_notes": routing_notes or "", "supports_tools": supports_tools,
        }
        # Unsent sizes keep ModelConfigIn's own defaults — same as the dialog.
        if context_window is not None:
            fields["context_window"] = context_window
        if max_output_tokens is not None:
            fields["max_output_tokens"] = max_output_tokens
        if temperature is not None:
            fields["temperature"] = temperature
        try:
            config = intel_svc.create_model_config(company, user, ModelConfigIn(**fields).dict())
        except ValueError as exc:
            raise GatewayToolError(str(exc))
        return {**_model_summary(config), "checked": True,
                "latency_ms": check.get("latency_ms")}
    return await sync_to_async(_run)()


async def update_model(user, config_id: str, name: str | None = None,
                       provider: str | None = None, model_id: str | None = None,
                       api_key: str | None = None, api_base: str | None = None,
                       context_window: int | None = None,
                       max_output_tokens: int | None = None,
                       temperature: float | None = None,
                       routing_notes: str | None = None,
                       supports_tools: bool | None = None,
                       description: str | None = None) -> dict:
    """Edit a model — the Edit dialog's road. Changing how it is reached
    (provider, model id, API base, key) re-runs the provider check first;
    every persona on the config follows the saved change. Key write-only."""
    def _run():
        from authn.permissions.checker import PermissionChecker
        from intelligence import services as intel_svc

        company = _company()
        if not PermissionChecker.can(user, "model_config.update", company=company):
            raise GatewayToolError("You don't have permission to edit model configs.")
        config = intel_svc.get_model_config(company, config_id)
        if not config:
            raise GatewayToolError("No such model config.")
        data = {k: v for k, v in {
            "name": name, "provider": provider, "model_id": model_id,
            "api_key": api_key, "api_base": api_base,
            "context_window": context_window, "max_output_tokens": max_output_tokens,
            "temperature": temperature, "routing_notes": routing_notes,
            "supports_tools": supports_tools, "description": description,
        }.items() if v is not None}
        if not data:
            raise GatewayToolError("Nothing to change — pass at least one field.")
        reach_changed = any(k in data for k in ("provider", "model_id", "api_base", "api_key"))
        if reach_changed:
            # Merged values, the dialog's way: a blank key means the stored one.
            _run_model_check(
                company,
                data.get("provider") or config.provider,
                data.get("model_id") or config.model_id,
                data.get("api_key"),
                data.get("api_base") if "api_base" in data else config.api_base,
                config_id=None if data.get("api_key") else str(config.id),
            )
        try:
            config = intel_svc.update_model_config(company, config_id, data)
        except ValueError as exc:
            raise GatewayToolError(str(exc))
        if not config:
            raise GatewayToolError("No such model config.")
        return {**_model_summary(config), "checked": reach_changed}
    return await sync_to_async(_run)()


def _persona_summary(persona) -> dict:
    return {
        "id": str(persona.id), "name": persona.name, "mention": f"@{persona.name}",
        "description": persona.description or "",
        "project_id": str(persona.project_id),
        "model": persona.model.name if persona.model_id else None,
        "output_type": persona.prompt.output_type if getattr(persona, "prompt", None) else None,
        "tool_servers": [s.name for s in persona.mcp_servers.all() if s.is_active],
        "max_steps": persona.max_steps,
        "acts_after_approval": persona.acts_after_approval,
    }


async def list_personas(user, project_id: str) -> list[dict]:
    """One project's personas — the same visibility the app's list uses."""
    def _run():
        from intelligence import services as intel_svc
        from workspace import services as ws_svc

        company = _company()
        project = ws_svc.get_project(company, user, project_id)
        if not project:
            raise GatewayToolError("No such project.")
        return [_persona_summary(p) for p in intel_svc.list_personas(project, user)]
    return await sync_to_async(_run)()


async def create_persona(user, project_id: str, name: str, system_prompt: str,
                         model_config_id: str, description: str = "",
                         output_type: str = "auto",
                         mcp_server_ids: list | None = None) -> dict:
    """Create a persona — the dialog's road: persona.create on the project,
    the same wiring rules (model attached to the project, …)."""
    def _run():
        from authn.permissions.checker import PermissionChecker
        from intelligence import services as intel_svc
        from intelligence.schema import PersonaIn, PromptIn
        from workspace import services as ws_svc

        company = _company()
        project = ws_svc.get_project(company, user, project_id)
        if not project:
            raise GatewayToolError("No such project.")
        if not PermissionChecker.can(user, "persona.create", obj=project):
            raise GatewayToolError("You don't have permission to create personas in this project.")
        if not (system_prompt or "").strip():
            raise GatewayToolError("system_prompt is empty.")
        payload = PersonaIn(
            name=name, description=description or None, project_id=str(project.id),
            model_config_id=model_config_id,
            mcp_server_ids=[str(s) for s in (mcp_server_ids or [])],
            prompt=PromptIn(system_prompt=system_prompt, output_type=(output_type or "auto")),
        ).dict()
        try:
            persona = intel_svc.create_persona(company, user, payload)
        except ValueError as exc:
            raise GatewayToolError(str(exc))
        return {**_persona_summary(persona),
                "note": f"Mention {persona.name} in a topic as @{persona.name} to use it."}
    return await sync_to_async(_run)()


async def update_persona(user, persona_id: str, name: str | None = None,
                         description: str | None = None,
                         system_prompt: str | None = None,
                         output_type: str | None = None,
                         model_config_id: str | None = None,
                         max_steps: int | None = None,
                         acts_after_approval: bool | None = None) -> dict:
    """Edit a persona — persona.update on its project, the dialog's rules."""
    def _run():
        from authn.permissions.checker import PermissionChecker
        from intelligence import services as intel_svc
        from nucleus.models import Persona
        from workspace import services as ws_svc

        company = _company()
        try:
            persona = (Persona.objects.filter(company=company, id=persona_id, is_active=True)
                       .select_related("project", "prompt").first())
        except Exception:  # noqa: BLE001 — a malformed id is just "no such persona"
            persona = None
        # Invisible answers like nonexistent — the project must be theirs to see.
        if not persona or not ws_svc.get_project(company, user, str(persona.project_id)):
            raise GatewayToolError("No such persona.")
        if not PermissionChecker.can(user, "persona.update", obj=persona.project):
            raise GatewayToolError("You don't have permission to edit this persona.")
        data = {k: v for k, v in {
            "name": name, "description": description,
            "model_config_id": model_config_id, "max_steps": max_steps,
            "acts_after_approval": acts_after_approval,
        }.items() if v is not None}
        if system_prompt is not None or output_type is not None:
            current = getattr(persona, "prompt", None)
            text = system_prompt if system_prompt is not None else (current.system_prompt if current else "")
            if not (text or "").strip():
                raise GatewayToolError("system_prompt is empty.")
            data["prompt"] = {
                "system_prompt": text,
                "output_type": output_type or (current.output_type if current else "auto"),
            }
        if not data:
            raise GatewayToolError("Nothing to change — pass at least one field.")
        try:
            persona = intel_svc.patch_persona(company, persona_id, data)
        except ValueError as exc:
            raise GatewayToolError(str(exc))
        if not persona:
            raise GatewayToolError("No such persona.")
        return _persona_summary(persona)
    return await sync_to_async(_run)()


async def list_users(user) -> list[dict]:
    """The server's members — any member may look, like the Members page."""
    def _run():
        from workspace import members_services as members_svc

        company = _company()
        if not members_svc.get_member_access(company, user):
            raise GatewayToolError("You are not a member of this server.")
        rows = members_svc.list_members(company)
        return [row if isinstance(row, dict) else dict(row) for row in rows]
    return await sync_to_async(_run)()


async def get_topic_messages(user, topic_id: str, ai_only: bool = False,
                             limit: int = 50) -> list[dict]:
    """One topic's transcript, newest last — the same row visibility chat
    uses. ai_only=true keeps only the personas' replies."""
    def _run():
        from nucleus.models import ChatMessage

        _company_, _project, topic = _find_topic(user, topic_id)
        take = max(1, min(int(limit or 50), 200))
        qs = ChatMessage.objects.filter(topic=topic, is_active=True).select_related("sender")
        if ai_only:
            qs = qs.filter(metadata__has_key="persona_id")
        rows = list(qs.order_by("-sequence")[:take])[::-1]
        out = []
        for row in rows:
            meta = row.metadata or {}
            author = meta.get("persona_name") or (
                getattr(row.sender, "display_name", "") or getattr(row.sender, "username", "") or ""
                if row.sender_id else "")
            out.append({
                "id": str(row.id), "sequence": row.sequence, "author": author,
                "ai": "persona_id" in meta, "status": row.status,
                "content": row.content or "",
                "created_at": row.created_at.isoformat(),
            })
        return out
    return await sync_to_async(_run)()


async def create_topic(user, channel_id: str, title: str) -> dict:
    """Add a chat — topic.create on the channel, exactly the app's road.

    channel_id takes the channel's id OR ITS NAME (case-insensitive): a person
    or a persona says "Marketing", not a UUID — found live 2026-10-30, when
    the setup copilot had to ask the owner for "the exact channel ID" (his
    verdict: "how the hell do i know"). A miss or an ambiguous name answers
    with the channels the person can actually see, so the next call lands."""
    def _run():
        from authn.permissions.checker import PermissionChecker
        from nucleus.models import Channel
        from workspace import services as ws_svc

        company = _company()
        if not (title or "").strip():
            raise GatewayToolError("title is empty.")
        wanted = (channel_id or "").strip()
        if not wanted:
            raise GatewayToolError("Say which channel — its name or its id.")

        def readable(c):
            return ws_svc.get_project(company, user, str(c.project_id))

        qs = Channel.objects.filter(company=company, is_active=True).select_related("project")
        try:
            channel = qs.filter(id=wanted).first()
        except Exception:  # noqa: BLE001 — not a UUID: try it as a name
            channel = None
        project = readable(channel) if channel else None
        if not channel:
            named = [c for c in qs if c.name.lower() == wanted.lower() and readable(c)]
            if len(named) == 1:
                channel = named[0]
                project = readable(channel)
            elif len(named) > 1:
                listing = ", ".join(f"{c.name} in {c.project.name} (id {c.id})" for c in named)
                raise GatewayToolError(
                    f"Several channels are named '{wanted}' — say which by id: {listing}.")
        if not channel or not project:
            visible = [c for c in qs if readable(c)][:30]
            listing = "; ".join(f"{c.name} (project {c.project.name})" for c in visible)
            raise GatewayToolError(
                f"No such channel: '{wanted}'. The channels you can see: {listing or 'none'}.")
        if not PermissionChecker.can(user, "topic.create", obj=channel):
            raise GatewayToolError("You don't have permission to create topics in this channel.")
        topic = ws_svc.create_topic(company=company, project=project, channel=channel,
                                    title=title.strip(), creator=user)
        return {"id": str(topic.id), "title": topic.title,
                "channel_id": str(topic.channel_id), "project_id": str(topic.project_id)}
    return await sync_to_async(_run)()


async def update_topic(user, topic_id: str, title: str = "",
                       archive: bool | None = None) -> dict:
    """Rename and/or archive/restore a topic — topic.update for the rename,
    topic.archive for both archive and restore, the app's exact gates."""
    def _run():
        from authn.permissions.checker import PermissionChecker
        from nucleus.models import ChatTopic
        from workspace import services as ws_svc

        company = _company()
        if not (title or "").strip() and archive is None:
            raise GatewayToolError("Nothing to change — pass a title and/or archive.")
        # Fetched WITHOUT the active filter: restoring an archived topic is
        # the point of archive=false (the app's unarchive road).
        try:
            topic = (ChatTopic.objects.filter(id=topic_id)
                     .select_related("project", "channel").first())
        except Exception:  # noqa: BLE001
            topic = None
        project = ws_svc.get_project(company, user, str(topic.project_id)) if topic else None
        if not topic or not project:
            raise GatewayToolError("No such topic.")
        out = {"id": str(topic.id), "title": topic.title, "archived": not topic.is_active}
        if (title or "").strip():
            if not topic.is_active:
                raise GatewayToolError("This topic is archived — restore it first (archive=false).")
            if not PermissionChecker.can(user, "topic.update", obj=topic):
                raise GatewayToolError("You don't have permission to rename this topic.")
            topic = ws_svc.update_topic(project, topic.channel, topic, title.strip())
            out.update({"title": topic.title})
        if archive is not None:
            if not PermissionChecker.can(user, "topic.archive", obj=topic):
                raise GatewayToolError("You don't have permission to archive or restore this topic.")
            if archive:
                ws_svc.archive_topic(topic)
            else:
                ws_svc.unarchive_topic(topic)
            out["archived"] = bool(archive)
        return out
    return await sync_to_async(_run)()


async def chain_status(user, run_id: str) -> dict:
    """One run's progress — status, the step it is on, each step's outcome, and
    the checkpoint it may be waiting at. Invisible = nonexistent, as everywhere."""
    def _run():
        from authn.permissions.checker import PermissionChecker
        from nucleus.models import RunbookRun
        from scheduling import runbooks
        from workspace import services as ws_svc

        company = _company()
        try:
            run = (RunbookRun.objects.filter(id=run_id, is_active=True)
                   .select_related("runbook", "topic", "project", "started_by").first())
        except Exception:  # noqa: BLE001 — a malformed id is just "no such run"
            run = None
        if not run:
            raise GatewayToolError("No such run.")
        project = ws_svc.get_project(company, user, str(run.project_id))
        if not project or not PermissionChecker.can(user, "topic.list", obj=project):
            raise GatewayToolError("No such run.")
        full = runbooks.serialise_run(run)
        return {
            **{k: full[k] for k in (
                "id", "runbook_id", "runbook_title", "status", "current_step", "step_count",
                "checkpoint", "skipped_count", "error", "started_at", "ended_at",
            )},
            "steps": [
                {"index": s.get("index"), "status": s.get("status"), "persona": s.get("persona_name"),
                 "verdict": s.get("verdict"), "error": s.get("error")}
                for s in (full["step_results"] or [])
            ],
        }
    return await sync_to_async(_run)()
