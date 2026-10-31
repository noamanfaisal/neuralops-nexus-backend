"""
setup_tools — the gateway's ADMIN tools mounted INSIDE for personas
(docs/MISSING.md setup-copilot entry: "the same tools can then be mounted
INSIDE for personas via the InternalActor door — X-NeuralOps-User carries the
asking person; rights still theirs, writes still gated by approvals. One
door, one rights rule, both worlds").

Mechanism: a persona whose internal capability row carries the `setup` key
gets this FunctionToolset (ToolsetBuilder mounts it as a native-like
capability with id "setup"). Every call is FORWARDED to nucleus's own MCP
gateway (POST /api/v1/mcp/, tools/call) through the InternalActor door — the
engine's internal key plus X-NeuralOps-User = the person who triggered this
reply. The gateway runs the SAME permission-checked tool functions the
outside world gets, as that person: a right the person lacks comes back as a
worded refusal, never a bypass. On top the engine adds only the approval
gate: the six writes are ACTING_NATIVE_TOOLS["setup"], so an interactive run
pauses on an approval card first and an unattended one refuses in words.

THE KEY RULE (free-LLM hard rules — none bend): an API key must NEVER travel
through a chat message, because chat lands in the DB, the history and the
memory store. So the INSIDE copies of create_model/update_model have NO
api_key parameter at all — the model cannot send one, and a key pasted into
chat has nowhere to go. A keyless register works end to end for endpoints
that need none (a local Ollama).

WP3 — THE SECURE KEY CARD: the key road that does exist runs OUTSIDE the
conversation. create_model pauses on its approval card like every setup
write; the card offers a write-only key field; the typed key rides the
decision POST → nucleus memory → the resume's ApprovalDecisionIn.secret →
DeferredToolResults.metadata → ctx.tool_call_metadata HERE, where it is
added to the forwarded gateway arguments and forgotten. It is never a tool
argument, so it never enters the run state, the message history, the audit
anatomy or the memory store; the gateway stores it encrypted and answers
has_api_key only.

A gateway refusal (GatewayToolError → isError) comes back as the tool's
result TEXT, stating plainly that nothing changed — told only "error" a
model invents outcomes (the honesty rule markers.py and approvals follow).
"""
from __future__ import annotations

import logging

import httpx
from pydantic_ai import RunContext
from pydantic_ai.toolsets import FunctionToolset

log = logging.getLogger(__name__)

SETUP_TOOLSET_ID = "setup"

_NO_ACTOR = ("{tool} refused: this run carries no acting person, and every "
             "setup tool acts AS someone (their rights, their audit trail). "
             "Nothing changed.")
_UNREACHABLE = ("{tool} failed: the NeuralOps server could not be reached "
                "({error}). Nothing changed.")


def _drop_unset(args: dict) -> dict:
    """None = 'leave unchanged' on every update tool — never sent, so the
    gateway's own defaults rule (a None there means the same thing)."""
    return {k: v for k, v in args.items() if v is not None}


def setup_toolset(base_url: str, internal_key: str, user_id: str,
                  timeout_seconds: float = 30.0) -> FunctionToolset:
    """The admin tools bound to ONE reply's acting person (job.user_id)."""
    headers = {
        "X-Internal-Key": internal_key,
        "X-Internal-API-Key": internal_key,  # today's nucleus spelling, like NucleusClient
        "X-NeuralOps-User": user_id or "",
    }
    url = f"{base_url.rstrip('/')}/api/v1/mcp/"

    async def _call(tool: str, arguments: dict) -> str:
        if not (user_id or "").strip():
            return _NO_ACTOR.format(tool=tool)
        body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                "params": {"name": tool, "arguments": arguments}}
        try:
            async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                response = await client.post(url, json=body, headers=headers)
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:  # noqa: BLE001 — a dead door is the tool's result, never a crash
            log.warning("[setup] %s could not reach the gateway: %s", tool, type(exc).__name__)
            return _UNREACHABLE.format(tool=tool, error=type(exc).__name__)
        result = payload.get("result") or {}
        texts = [c.get("text", "") for c in (result.get("content") or [])
                 if isinstance(c, dict) and c.get("type") == "text"]
        text = "\n".join(t for t in texts if t).strip() or "(empty result)"
        if result.get("isError"):
            return f"{tool} refused: {text} Nothing changed."
        return text

    # ── models ──────────────────────────────────────────────────────────────

    async def list_models() -> str:
        """The models registered on this server — name, provider, model id,
        whether a key is stored (never the key itself) and which projects
        each one is attached to."""
        return await _call("list_models", {})

    async def create_model(ctx: RunContext, name: str, provider: str, model_id: str,
                           accept_provider_terms: bool = False,
                           api_base: str = "", description: str = "",
                           context_window: int | None = None,
                           max_output_tokens: int | None = None,
                           temperature: float | None = None,
                           routing_notes: str = "",
                           supports_tools: bool = True) -> str:
        """Register a model for the person you act for (they need model
        management rights, and must have said yes to the provider's terms —
        only then pass accept_provider_terms=true). The server CHECKS the
        model with the provider first and refuses to save one that cannot
        answer. There is NO way to pass an API key here, on purpose: keys
        never travel through chat — never ask for one and refuse a pasted
        one (tell the person to revoke it). When this call pauses for
        approval, THE CARD ITSELF offers a secure key field: tell the person
        to type the key there if the provider needs one. Keyless endpoints
        (a local Ollama, an open API base) work with no key at all."""
        args: dict = {"name": name, "provider": provider, "model_id": model_id,
                      "accept_provider_terms": accept_provider_terms,
                      "api_base": api_base, "description": description,
                      "routing_notes": routing_notes, "supports_tools": supports_tools}
        args.update(_drop_unset({"context_window": context_window,
                                 "max_output_tokens": max_output_tokens,
                                 "temperature": temperature}))
        # WP3: the key typed on the approval card arrives as call metadata —
        # added to the FORWARDED arguments only (never the model-visible
        # args), then forgotten. The gateway stores it encrypted.
        card = getattr(ctx, "tool_call_metadata", None) or {}
        secret = str(card.get("secret") or "").strip() if isinstance(card, dict) else ""
        if secret:
            args["api_key"] = secret
        return await _call("create_model", args)

    async def update_model(config_id: str, name: str | None = None,
                           provider: str | None = None, model_id: str | None = None,
                           api_base: str | None = None,
                           context_window: int | None = None,
                           max_output_tokens: int | None = None,
                           temperature: float | None = None,
                           routing_notes: str | None = None,
                           supports_tools: bool | None = None,
                           description: str | None = None) -> str:
        """Edit a registered model (None = leave unchanged). Changing how it
        is reached (provider, model id, API base) makes the server re-check
        it with the provider — using the key it already has stored — before
        saving. The stored key cannot be read or replaced from chat; a key
        change happens in the app's Edit dialog."""
        args = _drop_unset({"name": name, "provider": provider, "model_id": model_id,
                            "api_base": api_base, "context_window": context_window,
                            "max_output_tokens": max_output_tokens,
                            "temperature": temperature, "routing_notes": routing_notes,
                            "supports_tools": supports_tools, "description": description})
        args["config_id"] = config_id
        return await _call("update_model", args)

    # ── personas ────────────────────────────────────────────────────────────

    async def list_personas(project_id: str) -> str:
        """The personas of one project the acting person can see — name,
        description, model, answer format, max steps."""
        return await _call("list_personas", {"project_id": project_id})

    async def create_persona(project_id: str, name: str, system_prompt: str,
                             model_config_id: str, description: str = "",
                             output_type: str = "auto") -> str:
        """Create a persona in a project — the dialog's exact road: the acting
        person needs persona-create rights there, and the model must already
        be attached to the project."""
        return await _call("create_persona", {
            "project_id": project_id, "name": name, "system_prompt": system_prompt,
            "model_config_id": model_config_id, "description": description,
            "output_type": output_type,
        })

    async def update_persona(persona_id: str, name: str | None = None,
                             description: str | None = None,
                             system_prompt: str | None = None,
                             output_type: str | None = None,
                             model_config_id: str | None = None,
                             max_steps: int | None = None,
                             acts_after_approval: bool | None = None) -> str:
        """Edit a persona (None = leave unchanged): name, description, its
        system prompt, answer format, model, max steps, propose-first."""
        args = _drop_unset({"name": name, "description": description,
                            "system_prompt": system_prompt, "output_type": output_type,
                            "model_config_id": model_config_id, "max_steps": max_steps,
                            "acts_after_approval": acts_after_approval})
        args["persona_id"] = persona_id
        return await _call("update_persona", args)

    # ── users and topics ────────────────────────────────────────────────────

    async def list_users() -> str:
        """The members of this server's company — the Members page's rule:
        any member may look."""
        return await _call("list_users", {})

    async def get_topic_messages(topic_id: str, ai_only: bool = False,
                                 limit: int = 50) -> str:
        """One topic's transcript, oldest first (up to 200 rows), with the
        same row visibility chat itself applies. ai_only=true keeps only the
        personas' replies."""
        return await _call("get_topic_messages",
                           {"topic_id": topic_id, "ai_only": ai_only, "limit": limit})

    async def create_topic(channel_id: str, title: str) -> str:
        """Add a chat (topic) to a channel — topic.create on that channel, as
        the acting person. channel_id takes the channel's NAME (e.g.
        "general") or its id — never ask a person for a channel id; a wrong
        name is answered with the channels that exist."""
        return await _call("create_topic", {"channel_id": channel_id, "title": title})

    async def update_topic(topic_id: str, title: str = "",
                           archive: bool | None = None) -> str:
        """Rename a topic (title), archive it (archive=true) or restore it
        (archive=false) — the app's own gates: topic.update for the rename,
        topic.archive for both archive and restore."""
        args: dict = {"topic_id": topic_id, "title": title}
        if archive is not None:
            args["archive"] = archive
        return await _call("update_topic", args)

    return FunctionToolset(
        [list_models, create_model, update_model,
         list_personas, create_persona, update_persona,
         list_users, get_topic_messages, create_topic, update_topic],
        id=SETUP_TOOLSET_ID,
    )
