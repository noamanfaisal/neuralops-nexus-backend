"""
scheduling/runbooks.py -- Runbooks (W6): an ordered list of persona steps a
project runs as one unit, in one chat, one reply after another.

The definition is a JSON document validated as a whole (validate_runbook_data);
a run is a RunbookRun row the Celery task scheduling.tasks.run_runbook drives
through execute_run(): every step goes through the exact same
chat/services.py:trigger_ai_response_async a live @mention uses, with the
previous step's reply as its context, so a runbook step is indistinguishable
from a person typing "@Persona <prompt>" -- on a queue, unattended. The
starter is the actor of every step (their series of mentions), re-checked
before the first, like a schedule's creator.
"""
import logging
import re
import uuid

from asgiref.sync import async_to_sync
from django.utils import timezone

from chat.stop_signals import stop_signals

logger = logging.getLogger(__name__)

STEPS_MAX = 12
PROMPT_MAX = 4000
# Chains v2: the run-time QUERY (ruling 3) shares the prompt bound; a step's
# ROLE label (ruling 5) is a short word or two for the banner, not a prompt.
QUERY_MAX = PROMPT_MAX
ROLE_MAX = 60
TITLE_MAX = 120
DESCRIPTION_MAX = 500
ON_FAILURE = ("stop", "skip", "retry")
# A step's output type is the worker's short token (auto, chart, code, …).
OUTPUT_TYPE_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
# "retry" gives a failing step ONE more attempt before the stop rule applies.
RETRY_MAX = 1

# Step 7 (chains). Ruling 3: a REDO verdict may rerun a stage at most this
# many times, whatever redo_limit says. Ruling 4: a checkpoint waits this long.
REDO_CAP = 2
CHECKPOINT_EXPIRY_HOURS = 24
# How much of the stage's reply the reviewer sees, and how much of the
# reviewer's notes ride the redo prompt -- heads, so neither can crowd a prompt.
REVIEW_CLIP = 6000
NOTES_CLIP = 2000

# "waiting" (parked at a checkpoint) is active: stoppable, shown as in-flight.
ACTIVE_STATUSES = ("queued", "running", "waiting")


# ── Definition ────────────────────────────────────────────────────────────────

def validate_steps(project, steps) -> list[dict]:
    """The stored shape of a runbook's steps; raises ValueError with the reason a person can act on."""
    from nucleus.models import Persona, Routine

    if not isinstance(steps, list) or not 1 <= len(steps) <= STEPS_MAX:
        raise ValueError(f"A chain has 1 to {STEPS_MAX} steps.")
    personas = {str(p.id) for p in Persona.objects.filter(project=project, is_active=True).only("id")}
    routines = {str(r.id) for r in Routine.objects.filter(project=project, is_active=True).only("id")}
    out = []
    for i, step in enumerate(steps, 1):
        if not isinstance(step, dict):
            raise ValueError(f"Step {i} is not a step.")
        # Step 7: two step kinds. No `kind` key (every pre-chain row) = persona.
        kind = (step.get("kind") or "persona").strip().lower()
        if kind == "checkpoint":
            question = (step.get("question") or "").strip()
            if not question or len(question) > PROMPT_MAX:
                raise ValueError(f"Step {i} is a checkpoint and needs a question of at most {PROMPT_MAX:,} characters.")
            on_failure = step.get("on_failure") or "stop"
            if on_failure not in ("stop", "skip"):
                raise ValueError(f"Step {i}: a checkpoint's on_failure is stop or skip — it has nothing to retry.")
            out.append({"kind": "checkpoint", "question": question, "on_failure": on_failure})
            continue
        if kind not in ("persona", "model"):
            raise ValueError(f"Step {i} has a kind this server does not know.")
        # Chains v2 (ruling 5): an optional ROLE label for the banner ("Reviewer").
        role = (step.get("role") or "").strip()
        if len(role) > ROLE_MAX:
            raise ValueError(f"Step {i}: a role label is at most {ROLE_MAX} characters.")
        prompt = (step.get("prompt") or "").strip()
        if not prompt or len(prompt) > PROMPT_MAX:
            raise ValueError(f"Step {i} needs a prompt of at most {PROMPT_MAX:,} characters.")
        output_type = (step.get("output_type") or "auto").strip().lower()
        if not OUTPUT_TYPE_RE.match(output_type):
            raise ValueError(f"Step {i} has an output type the worker cannot resolve.")
        on_failure = step.get("on_failure") or "stop"
        if on_failure not in ON_FAILURE:
            raise ValueError(f"Step {i}: on_failure is stop, skip or retry.")
        if kind == "model":
            # Chains v2 (ruling 2): a bare model + prompt — a text-only transform,
            # no tools, no approvals. The model must be this project's to use.
            model_id = str(step.get("model_config_id") or "")
            if model_id not in _project_model_ids(project):
                raise ValueError(f"Step {i} names a model that is not attached to this project.")
            out.append({
                "kind": "model", "model_config_id": model_id, "prompt": prompt, "role": role,
                "output_type": output_type, "on_failure": on_failure,
            })
            continue
        persona_id = str(step.get("persona_id") or "")
        if persona_id not in personas:
            raise ValueError(f"Step {i} names a persona that is not in this project.")
        routine_id = step.get("routine_id") or None
        if routine_id is not None and str(routine_id) not in routines:
            raise ValueError(f"Step {i} names a routine that is not in this project.")
        out.append({
            "kind": "persona",
            "persona_id": persona_id, "prompt": prompt, "role": role,
            "routine_id": str(routine_id) if routine_id else None,
            "output_type": output_type, "on_failure": on_failure,
        })
    return out


def has_checkpoint(runbook) -> bool:
    """Ruling 5: a chain that waits for a person cannot run on a schedule."""
    return any((s.get("kind") or "persona") == "checkpoint" for s in (runbook.steps or []))


def _project_model_ids(project) -> set[str]:
    """The ids of the active models a chain's model step may use — the ones
    attached to this project, the same reach a persona's seats have."""
    from nucleus.models import ModelConfig
    return {
        str(m)
        for m in ModelConfig.objects.filter(
            company=project.company, is_active=True, projects=project,
        ).values_list("id", flat=True)
    }


def validate_runbook_data(project, data: dict, *, partial: bool = False) -> dict:
    out = {}
    if "title" in data or not partial:
        title = (data.get("title") or "").strip()
        if not title or len(title) > TITLE_MAX:
            raise ValueError(f"A chain needs a title of at most {TITLE_MAX} characters.")
        out["title"] = title
    if "description" in data:
        description = (data.get("description") or "").strip()
        if len(description) > DESCRIPTION_MAX:
            raise ValueError(f"The description is at most {DESCRIPTION_MAX} characters.")
        out["description"] = description
    if "steps" in data or not partial:
        out["steps"] = validate_steps(project, data.get("steps"))
    # Step 7 (rulings 2+3): the one optional supervisor, and the redo bound.
    if data.get("supervisor_id"):
        from django.core.exceptions import ValidationError
        from nucleus.models import Persona
        try:
            supervisor = Persona.objects.filter(
                id=data["supervisor_id"], project=project, is_active=True,
            ).first()
        except (ValueError, ValidationError):
            supervisor = None
        if not supervisor:
            raise ValueError("The supervisor must be a persona in this project.")
        out["supervisor"] = supervisor
    if data.get("clear_supervisor"):
        out["supervisor"] = None
    if data.get("redo_limit") is not None:
        redo = data["redo_limit"]
        if not isinstance(redo, int) or isinstance(redo, bool) or not 0 <= redo <= REDO_CAP:
            raise ValueError(f"redo_limit is 0 to {REDO_CAP}.")
        out["redo_limit"] = redo
    return out


def list_runbooks(project):
    from nucleus.models import Runbook
    return list(Runbook.objects.filter(project=project, is_active=True).order_by("title"))


def chain_for_mention(project, name: str):
    """Chains v2 (ruling 4): the chain whose title answers to an @mention token.
    Mentions are one \\w+ word, titles have spaces — so both sides compare with
    case and separators ignored: "@WeeklyOpsUpdate" and "@weekly_ops_update"
    both name "Weekly ops update". Personas resolve FIRST (the caller only
    tries names no persona answered to), so a persona never loses its name to
    a chain. None when nothing matches — the token was just a word."""
    wanted = re.sub(r"[^a-z0-9]+", "", (name or "").lower())
    if not wanted:
        return None
    for runbook in list_runbooks(project):
        if re.sub(r"[^a-z0-9]+", "", runbook.title.lower()) == wanted:
            return runbook
    return None


def get_runbook(project, runbook_id: str):
    from nucleus.models import Runbook
    return Runbook.objects.filter(project=project, id=runbook_id, is_active=True).first()


def create_runbook(company, project, user, data: dict):
    from nucleus.models import Runbook
    data = validate_runbook_data(project, data)
    return Runbook.objects.create(company=company, project=project, created_by=user, **data)


def patch_runbook(project, runbook_id: str, data: dict):
    runbook = get_runbook(project, runbook_id)
    if not runbook:
        return None
    data = validate_runbook_data(project, {k: v for k, v in data.items() if v is not None}, partial=True)
    for field, value in data.items():
        setattr(runbook, field, value)
    runbook.save()
    return runbook


def delete_runbook(project, runbook_id: str) -> bool:
    """Soft-delete; its runs stay as history."""
    runbook = get_runbook(project, runbook_id)
    if not runbook:
        return False
    runbook.soft_delete()
    return True


def serialise_runbook(runbook, personas: dict | None = None, routines: dict | None = None, models: dict | None = None) -> dict:
    """The definition with each step's persona, routine and model named as they are NOW (a rename shows)."""
    from nucleus.models import ModelConfig, Persona, Routine

    steps = runbook.steps or []
    if personas is None:
        ids = {s.get("persona_id") for s in steps if s.get("persona_id")}
        personas = {str(p.id): p.name for p in Persona.objects.filter(id__in=ids)} if ids else {}
    if routines is None:
        ids = {s.get("routine_id") for s in steps if s.get("routine_id")}
        routines = {str(r.id): r.title for r in Routine.objects.filter(id__in=ids)} if ids else {}
    if models is None:
        ids = {s.get("model_config_id") for s in steps if s.get("model_config_id")}
        models = {str(m.id): m.name for m in ModelConfig.objects.filter(id__in=ids)} if ids else {}
    return {
        "id": str(runbook.id),
        "project_id": str(runbook.project_id),
        "title": runbook.title,
        "description": runbook.description or "",
        "supervisor_id": str(runbook.supervisor_id) if runbook.supervisor_id else None,
        "supervisor_name": runbook.supervisor.name if runbook.supervisor_id and runbook.supervisor else None,
        "redo_limit": runbook.redo_limit,
        "has_checkpoint": has_checkpoint(runbook),
        "steps": [
            {
                **s,
                "persona_name": personas.get(s.get("persona_id")),
                "routine_title": routines.get(s.get("routine_id")) if s.get("routine_id") else None,
                "model_name": models.get(s.get("model_config_id")) if s.get("model_config_id") else None,
            }
            for s in steps
        ],
        "created_by_id": str(runbook.created_by_id) if runbook.created_by_id else None,
        "created_at": runbook.created_at.isoformat(),
    }


def serialise_runbooks(runbooks: list) -> list[dict]:
    from nucleus.models import ModelConfig, Persona, Routine

    persona_ids = {s.get("persona_id") for rb in runbooks for s in (rb.steps or []) if s.get("persona_id")}
    routine_ids = {s.get("routine_id") for rb in runbooks for s in (rb.steps or []) if s.get("routine_id")}
    model_ids = {s.get("model_config_id") for rb in runbooks for s in (rb.steps or []) if s.get("model_config_id")}
    personas = {str(p.id): p.name for p in Persona.objects.filter(id__in=persona_ids)} if persona_ids else {}
    routines = {str(r.id): r.title for r in Routine.objects.filter(id__in=routine_ids)} if routine_ids else {}
    models = {str(m.id): m.name for m in ModelConfig.objects.filter(id__in=model_ids)} if model_ids else {}
    return [serialise_runbook(rb, personas, routines, models) for rb in runbooks]


# ── Runs ──────────────────────────────────────────────────────────────────────

def _current_role(run) -> str:
    """Chains v2 (ruling 5): the ROLE label of the step in progress, for the
    banner — "step 2 of 4 — Reviewer". Empty when the step has none."""
    steps = run.runbook.steps or []
    if 0 <= run.current_step < len(steps):
        return (steps[run.current_step].get("role") or "")
    return ""


def serialise_run(run) -> dict:
    return {
        "id": str(run.id),
        "runbook_id": str(run.runbook_id),
        "runbook_title": run.runbook.title,
        "project_id": str(run.project_id),
        "topic_id": str(run.topic_id),
        "channel_id": str(run.topic.channel_id),
        "topic_title": run.topic.title,
        "started_by_id": str(run.started_by_id) if run.started_by_id else None,
        "started_by_name": run.started_by.get_display_name() if run.started_by else None,
        "status": run.status,
        "query": run.query or "",
        "current_step": run.current_step,
        "current_role": _current_role(run),
        "step_count": len(run.runbook.steps or []),
        "step_results": run.step_results or [],
        "checkpoint": run.checkpoint,
        "skipped_count": skipped_count(run),
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "ended_at": run.ended_at.isoformat() if run.ended_at else None,
        "error": run.error or "",
        "created_at": run.created_at.isoformat(),
    }


def _runs(project):
    from nucleus.models import RunbookRun
    return RunbookRun.objects.filter(project=project, is_active=True).select_related("runbook", "topic", "started_by")


def list_runs(project, *, runbook_id: str | None = None, topic_id: str | None = None, active: bool = False, limit: int = 50):
    qs = _runs(project)
    if runbook_id:
        qs = qs.filter(runbook_id=runbook_id)
    if topic_id:
        qs = qs.filter(topic_id=topic_id)
    if active:
        qs = qs.filter(status__in=ACTIVE_STATUSES)
    return list(qs.order_by("-created_at")[:limit])


def get_run(project, run_id: str):
    return _runs(project).filter(id=run_id).first()


def start_run(company, project, runbook, actor, topic, query: str = ""):
    """A queued run in `topic`; the caller enqueues the task (or executes it, from a schedule).
    Chains v2 (ruling 3): `query` is the task this run is about — every step sees it."""
    from nucleus.models import RunbookRun
    return RunbookRun.objects.create(
        company=company, project=project, runbook=runbook, topic=topic, started_by=actor,
        query=(query or "").strip()[:QUERY_MAX],
    )


def _with_query(prompt: str, query: str) -> str:
    """Ruling 3: the run's query rides into EVERY step's prompt as the chain's
    task — step prompts describe the method, the query says what it is about."""
    q = (query or "").strip()
    if not q:
        return prompt
    return f"The chain's task for this run:\n{q}\n\n{prompt}"


def _run_block(run, index: int, count: int, *, step: dict | None = None, review: bool = False) -> dict:
    """The `runbook_run` metadata a step's reply carries — the app's banner
    reads it. Chains v2 adds the step's role label (ruling 5)."""
    block = {"id": str(run.id), "title": run.runbook.title, "step": index + 1, "of": count}
    role = (step or {}).get("role") or ""
    if role:
        block["role"] = role
    if review:
        block["review"] = True
    return block


def run_event(run) -> dict:
    """What the topic hears at every transition -- the app's banner and history read it."""
    # Every topic event carries a top-level id (the app's parser insists): the run's.
    return {"type": "runbook_run", "id": str(run.id), "run": serialise_run(run)}


def _announce(run, content: str) -> None:
    from chat import services as chat_svc
    msg = chat_svc.save_system_message(company=run.company, project=run.project, topic=run.topic, content=content)
    chat_svc.publish(chat_svc.topic_channel(str(run.topic_id)), {**msg, "type": "message"})


def _publish_run(run) -> None:
    from chat import services as chat_svc
    chat_svc.publish(chat_svc.topic_channel(str(run.topic_id)), run_event(run))


def stop_run(run, user) -> str:
    """
    "stopped" once the run will go no further, "finished" when it already had.
    A queued run ends here and now; a running one is marked and its current
    reply gets the stop signal -- the loop closes the run when that reply ends
    (or before the next step starts).
    """
    from nucleus.models import ChatMessage, RunbookRun

    if run.status not in ACTIVE_STATUSES:
        return "finished"
    name = user.get_display_name()
    run.error = f"Stopped by {name}"
    if run.status in (RunbookRun.Status.QUEUED, RunbookRun.Status.WAITING):
        # Queued (nothing started) or parked at a checkpoint (nothing in
        # flight): the run ends here and now, no pending reply to signal.
        waited = run.status == RunbookRun.Status.WAITING
        run.status = RunbookRun.Status.STOPPED
        run.checkpoint = None
        run.ended_at = timezone.now()
        run.save(update_fields=["status", "error", "checkpoint", "ended_at", "updated_at"])
        _announce(run, f"Chain: {run.runbook.title} stopped by {name}" + (" while waiting at its checkpoint." if waited else " before it started."))
        _publish_run(run)
        return "stopped"
    run.status = RunbookRun.Status.STOPPED
    # Stamped here as well as in _end: if the worker driving this run is already
    # gone, nothing else will ever close the row and the banner reads "stopped"
    # with no end time for good (audit, 2026-09-21).
    run.ended_at = timezone.now()
    run.save(update_fields=["status", "error", "ended_at", "updated_at"])
    pending = ChatMessage.objects.filter(
        topic=run.topic, status=ChatMessage.Status.PENDING, metadata__runbook_run__id=str(run.id),
    ).order_by("-sequence").first()
    if pending:
        async_to_sync(stop_signals().request_stop)(str(pending.id))
    _publish_run(run)
    return "stopped"


# ── Execution (the Celery task's body) ────────────────────────────────────────

def skipped_count(run) -> int:
    """
    How many steps were SKIPPED (their `skip` rule carried the run past a
    failure) -- a run that finished with one did not finish cleanly. Only
    skipped: a failed or stopped step ends the run, and its own status says so.
    """
    return sum(1 for s in (run.step_results or []) if s.get("status") == "skipped")


def _end(run, status: str, *, error: str = "", line: str) -> None:
    run.status = status
    run.error = error or run.error
    run.ended_at = timezone.now()
    run.save(update_fields=["status", "error", "ended_at", "updated_at"])
    _announce(run, line)
    _publish_run(run)


def _after_step(run) -> None:
    """Record the steps so far AND the context the next one builds on (Step 7:
    persisted so a checkpoint pause can resume in a fresh task), tell the topic."""
    from nucleus.models import RunbookRun
    RunbookRun.objects.filter(id=run.id).update(
        step_results=run.step_results, context=run.context or "", updated_at=timezone.now(),
    )
    _publish_run(run)


def _run_step(run, step: dict, index: int, count: int, context: str | None, actor, prompt: str | None = None) -> tuple[str, str | None, str, str]:
    """One attempt: (status done|failed|stopped, message id, error, content).
    `prompt` overrides the step's own (Step 7: a redo carries the reviewer's notes)."""
    from chat import services as chat_svc
    from nucleus.models import ChatMessage, Persona, Routine

    # Chains v2 (ruling 2): a model step is a bare text transform — same
    # (status, message id, error, content) contract, so retry/redo/review and
    # every on_failure rule apply to it unchanged.
    if (step.get("kind") or "persona") == "model":
        return _run_model_step(run, step, index, count, context, prompt)

    persona = Persona.objects.filter(id=step["persona_id"], project=run.project, is_active=True).select_related("identity_user").first()
    if persona is None:
        return "failed", None, "its persona is no longer in the project", ""
    routine = None
    if step.get("routine_id"):
        routine = Routine.objects.filter(id=step["routine_id"], project=run.project, is_active=True).select_related("model_config").first()
        if routine is None:
            return "failed", None, "its routine is gone", ""
    msg_id = async_to_sync(chat_svc.trigger_ai_response_async)(
        company=run.company, project=run.project, topic=run.topic, persona=persona,
        user_message=prompt if prompt is not None else _with_query(step["prompt"], run.query),
        user_message_id=str(uuid.uuid4()), topic_id=str(run.topic_id),
        output_type=step.get("output_type") or "auto",
        interactive=False,  # a runbook has nobody waiting to approve a plan
        routine=routine, triggered_by=actor,
        step_context=context,
        runbook_run=_run_block(run, index, count, step=step),
    )
    row = ChatMessage.objects.filter(id=msg_id).first() if msg_id else None
    if row is None:
        return "failed", msg_id, "no reply was produced", ""
    if (row.metadata or {}).get("stopped"):
        return "stopped", msg_id, "", row.content or ""
    if row.status == ChatMessage.Status.COMPLETED:
        return "done", msg_id, "", row.content or ""
    return "failed", msg_id, row.content or "the reply failed", ""


def _run_model_step(run, step: dict, index: int, count: int, context: str | None, prompt: str | None) -> tuple[str, str | None, str, str]:
    """Chains v2 (ruling 2): one bare model call through the engine's transform
    road — no tools, no approvals, no persona. The reply posts AS THE CHAIN
    (the chain's title is the bubble's name; the model is named in metadata)
    and bills kind=chat_reply with the run's id riding job_id, persona_id
    empty — exactly the owner's proposal in the ruling."""
    from django.db.models import Max
    from chat import services as chat_svc
    from chat.services import NexusAIClient
    from nucleus.models import ChatMessage, ModelConfig

    cfg = ModelConfig.objects.filter(id=step["model_config_id"], company=run.company, is_active=True).first()
    if cfg is None:
        return "failed", None, "its model is no longer available", ""
    text_prompt = prompt if prompt is not None else _with_query(step["prompt"], run.query)
    if context:
        text_prompt = f"The previous step's output:\n{context}\n\n{text_prompt}"
    try:
        out = NexusAIClient().transform({
            "provider": cfg.provider, "model_id": cfg.model_id,
            "api_key": cfg.get_api_key(), "api_base": cfg.api_base,
            "prompt": text_prompt,
            "max_tokens": cfg.max_output_tokens, "temperature": cfg.temperature,
        })
    except Exception as exc:  # noqa: BLE001 — an unreachable engine is a failed step, not a dead run
        logger.warning("[chain] run %s step %s: the transform road failed: %s", run.id, index + 1, exc)
        return "failed", None, "the server could not reach the model", ""
    if not out.get("ok"):
        logger.info("[chain] run %s step %s: model transform refused: %s", run.id, index + 1, out.get("error"))
        return "failed", None, f"the model could not run this step ({out.get('error_code') or 'error'})", ""

    text = out.get("text") or ""
    usage = out.get("usage") or {}
    max_seq = ChatMessage.objects.filter(topic_id=run.topic_id).aggregate(Max("sequence"))["sequence__max"] or 0
    msg = ChatMessage.objects.create(
        company=run.company, project=run.project, topic=run.topic,
        sender=None,  # the chain itself speaks — no persona, no shadow user
        content=text,
        message_type=ChatMessage.MessageType.TEXT,
        status=ChatMessage.Status.COMPLETED,
        sequence=max_seq + 1,
        metadata={
            "role": "assistant",
            "persona_name": run.runbook.title,          # the bubble's display name
            "chain_step": True,
            "model_name": cfg.name,
            "render_as": "text", "output_type": "text",
            "usage": {"prompt_tokens": usage.get("input_tokens"), "output_tokens": usage.get("output_tokens"),
                      "context_window": cfg.context_window},
            "runbook_run": _run_block(run, index, count, step=step),
        },
    )
    chat_svc.publish(chat_svc.topic_channel(str(run.topic_id)), chat_svc.serialise(msg))
    _record_model_step_usage(run, cfg, str(msg.id), usage)
    return "done", str(msg.id), "", text


def _record_model_step_usage(run, cfg, message_id: str, usage: dict) -> None:
    """One UsageRecord for the transform — kind=chat_reply (the ruling), the
    run's id in job_id, persona_id empty. Billing must never fail a step."""
    try:
        from intelligence.pricing import price_record
        from nucleus.models import UsageRecord

        record = {
            "company_id": str(run.company_id), "project_id": str(run.project_id),
            "topic_id": str(run.topic_id), "persona_id": "",
            "user_id": str(run.started_by_id) if run.started_by_id else "",
            "message_id": message_id, "job_id": f"chain-run:{run.id}",
            "kind": "chat_reply", "model_config_id": str(cfg.id),
            "provider": cfg.provider, "model_id": cfg.model_id, "role": "STANDARD",
            "provider_response_id": usage.get("provider_response_id"),
            "source": "chain_model_step",
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
        logger.exception("[chain] run %s: could not record the model step's usage", run.id)


def execute_run(run_id: str) -> None:
    """Drive a queued run to its end. Sync -- it runs inside a Celery task."""
    from nucleus.models import RunbookRun

    # Claimed, not checked: two deliveries of the same task both read "queued"
    # and both drove every step into the chat (audit, 2026-09-21). Exactly one
    # update can move the row out of QUEUED, and only that one goes on.
    claimed = RunbookRun.objects.filter(id=run_id, status=RunbookRun.Status.QUEUED).update(
        status=RunbookRun.Status.RUNNING, updated_at=timezone.now(),
    )
    if not claimed:
        logger.info("[runbook] run %s was not queued, nothing to do", run_id)
        return
    # started_at only on the FIRST claim -- a resume after a checkpoint (Step 7)
    # re-enters here QUEUED and must keep the original start time.
    RunbookRun.objects.filter(id=run_id, started_at__isnull=True).update(started_at=timezone.now())
    run = RunbookRun.objects.select_related("runbook", "topic", "project", "company", "started_by").filter(id=run_id).first()
    if not run:
        return
    # Every way out of _drive that is not an ending is an ending here. Without
    # this the row stayed RUNNING for ever on a time limit, a DB error or a bug,
    # and the chat showed a runbook mid-flight that nothing would ever close --
    # nothing reaps active runs, and a lost task is not redelivered (audit,
    # 2026-09-21).
    try:
        _drive(run)
    except Exception as exc:  # noqa: BLE001
        logger.exception("[runbook] run %s stopped driving", run_id)
        _end(
            run, RunbookRun.Status.FAILED,
            error=f"The server stopped driving this run: {type(exc).__name__}",
            line=f"Chain: {run.runbook.title} stopped unexpectedly — the server could not carry it to the end.",
        )
        raise


def _drive(run) -> None:
    """The steps themselves — from the first (or, resuming after a checkpoint,
    the one after it) to whichever one ends the run."""
    from authn.permissions.checker import PermissionChecker
    from nucleus.models import Persona, RunbookRun

    title = run.runbook.title
    steps = run.runbook.steps or []
    count = len(steps)
    actor = run.started_by
    # current_step is -1 on a fresh run; a checkpoint answer re-enqueues the run
    # with current_step already advanced past the answered step (Step 7).
    resuming = run.current_step >= 0
    start = max(run.current_step, 0)

    # The starter is the actor of every step -- their right to call personas here
    # is re-checked, as a schedule's is. On a resume too: rights move.
    if actor is None:
        reason = "its starter no longer has an account here"
    elif not PermissionChecker.can(actor, "persona.mention", obj=run.topic):
        reason = f"{actor.email or actor.username} can no longer call personas in this chat"
    else:
        reason = None
    if reason:
        _end(run, RunbookRun.Status.FAILED, error=f"Did not start: {reason}.", line=f"Chain: {title} did not start — {reason}.")
        return

    if resuming:
        _announce(run, f"Chain: {title} continuing at step {start + 1} of {count}.")
    else:
        # Ruling 3: the run's task is part of the start line, so the chat says
        # what this run is ABOUT, not only which chain ran.
        task = (run.query or "").strip()
        task_line = f" Task: {task[:200]}" if task else ""
        _announce(run, f"Chain: {title} started by {actor.get_display_name()} — {count} steps.{task_line}")
    _publish_run(run)

    # Ruling 2: the one optional supervisor. A retired/removed supervisor stops
    # the reviewing, never the chain.
    supervisor = None
    if run.runbook.supervisor_id:
        supervisor = Persona.objects.filter(
            id=run.runbook.supervisor_id, project=run.project, is_active=True,
        ).select_related("identity_user").first()
    # Ruling 3: redo_limit, hard-capped. No supervisor, no redos.
    redo_allowed = min(run.runbook.redo_limit or 0, REDO_CAP) if supervisor else 0

    names = {str(p.id): p.name for p in Persona.objects.filter(
        project=run.project, id__in={s["persona_id"] for s in steps if s.get("persona_id")},
    )}
    # Chains v2 (ruling 2): model steps name their model in the step results.
    from nucleus.models import ModelConfig
    model_names = {str(m.id): m.name for m in ModelConfig.objects.filter(
        company=run.company, id__in={s["model_config_id"] for s in steps if s.get("model_config_id")},
    )}
    context: str | None = (run.context or "").strip() or None
    for index in range(start, count):
        step = steps[index]
        # Stopped from outside between steps: the next one never starts.
        fresh = RunbookRun.objects.filter(id=run.id).values_list("status", flat=True).first()
        if fresh == RunbookRun.Status.STOPPED:
            run.refresh_from_db(fields=["error"])
            how = (run.error[0].lower() + run.error[1:]) if run.error else "stopped"
            _end(run, RunbookRun.Status.STOPPED, line=f"Chain: {title} {how} after step {index} of {count}.")
            return
        run.current_step = index
        run.save(update_fields=["current_step", "updated_at"])
        _publish_run(run)

        # Ruling 4: a checkpoint parks the run WAITING; the answer endpoint (or
        # the 24h expiry task) picks it up from here in a fresh Celery task.
        if (step.get("kind") or "persona") == "checkpoint":
            run.checkpoint = {"index": index, "question": step["question"], "asked_at": timezone.now().isoformat()}
            run.status = RunbookRun.Status.WAITING
            run.save(update_fields=["checkpoint", "status", "updated_at"])
            _announce(run, f"Chain: {title} is waiting for a person at step {index + 1} of {count} — {step['question']}")
            _publish_run(run)
            return

        attempts = 0
        redos = 0
        verdict = None
        prompt = _with_query(step["prompt"], run.query)
        started = timezone.now()
        while True:
            attempts += 1
            status, msg_id, error, content = _run_step(run, step, index, count, context, actor, prompt=prompt)
            if status == "failed" and step.get("on_failure") == "retry" and attempts <= RETRY_MAX:
                continue
            if status != "done" or supervisor is None:
                break
            # Rulings 2+3: the supervisor judges the stage; its verdict is a
            # visible reply in the topic like everything else.
            verdict, notes = _review(run, supervisor, step, content, actor, index, count)
            if verdict == "redo" and redos < redo_allowed:
                redos += 1
                prompt = (
                    f"{_with_query(step['prompt'], run.query)}\n\nThe reviewer asked for changes — redo this step and address these notes:\n"
                    f"{(notes or '')[:NOTES_CLIP]}"
                )
                continue
            if verdict in ("fail", "redo"):  # redo with none left fails too (ruling 3)
                status = "failed"
                first_line = (notes or "").strip().splitlines()[0][:200] if (notes or "").strip() else ""
                error = "the reviewer did not pass this step" + (f": {first_line}" if first_line else "")
            break
        result = {
            "index": index, "kind": step.get("kind") or "persona",
            "persona_id": step.get("persona_id"), "persona_name": names.get(step.get("persona_id")),
            "model_config_id": step.get("model_config_id"),
            "model_name": model_names.get(step.get("model_config_id")),
            "role": step.get("role") or "",
            "message_id": msg_id, "status": status, "attempts": attempts,
            "started_at": started.isoformat(), "ended_at": timezone.now().isoformat(), "error": error,
        }
        if supervisor is not None:
            result["redos"] = redos
            result["verdict"] = verdict
        if status == "failed" and step.get("on_failure") == "skip":
            result["status"] = "skipped"
        run.step_results = [*(run.step_results or []), result]
        if status == "done":
            run.context = content or ""
        _after_step(run)

        if status == "done":
            context = content
            continue
        if status == "stopped":
            run.refresh_from_db(fields=["error"])
            _end(run, RunbookRun.Status.STOPPED, line=f"Chain: {title} stopped at step {index + 1} of {count}.")
            return
        if step.get("on_failure") == "skip":
            continue  # the next step sees the last GOOD output
        _end(run, RunbookRun.Status.FAILED, error=f"Failed at step {index + 1} of {count}: {error}", line=f"Chain: {title} failed at step {index + 1} of {count} — {error}")
        return

    # "finished" on its own would hide a skipped step from everyone reading the chat.
    skipped = skipped_count(run)
    _end(run, RunbookRun.Status.DONE, line=f"Chain: {title} finished — {count} steps" + (f", {skipped} skipped." if skipped else "."))


# ── The supervisor (Step 7, rulings 2+3) ───────────────────────────────

def _parse_verdict(content: str) -> tuple[str, str]:
    """(verdict, full text). The review prompt demands one first word — APPROVE,
    REDO or FAIL; a reply that follows no format reads as "unclear" and the
    stage STANDS (a reviewer that cannot follow format must not kill a chain),
    with the verdict recorded so the step result says so."""
    text = (content or "").strip()
    first = text.splitlines()[0].strip().upper() if text else ""
    for word, verdict in (("APPROVE", "approve"), ("REDO", "redo"), ("FAIL", "fail")):
        if word in first:
            return verdict, text
    return "unclear", text


def _review(run, supervisor, step: dict, content: str, actor, index: int, count: int) -> tuple[str, str]:
    """Ask the chain's supervisor to judge the stage, through the same mention
    road as everything else (interactive=False — reviews never ask questions).
    Returns (approve|redo|fail|unclear|unreviewed, notes). Never raises."""
    from chat import services as chat_svc
    from nucleus.models import ChatMessage

    # Pass-unless-broken bias (live finding 2026-10-21: a supervisor REDO'd
    # perfectly fine work twice — against its own taste, not against the goal —
    # and the capped run failed): the reviewer judges whether the stage DID ITS
    # JOB, never whether it matches how the reviewer would have done it.
    task = (run.query or "").strip()
    task_line = f"The chain's task for this run:\n{task[:1000]}\n\n" if task else ""
    question = (
        f"You are the reviewer of a chain stage that just finished (step {index + 1} of {count}).\n"
        f"{task_line}"
        f"The stage's goal:\n{step['prompt'][:1000]}\n\n"
        f"The stage's reply:\n{(content or '')[:REVIEW_CLIP]}\n\n"
        "Start your reply with exactly one word on its own line — APPROVE, REDO or FAIL — "
        "then your notes.\n"
        "APPROVE is the usual verdict: approve any reply that does the stage's job, "
        "even one you would have worded, structured or approached differently — "
        "style and taste are never defects. REDO only for a concrete, fixable defect "
        "your notes name (a wrong fact, a missed requirement from the goal, a broken "
        "format); the stage then runs again with your notes. FAIL only when it did "
        "not do its job at all and redoing cannot fix it."
    )
    try:
        msg_id = async_to_sync(chat_svc.trigger_ai_response_async)(
            company=run.company, project=run.project, topic=run.topic, persona=supervisor,
            user_message=question, user_message_id=str(uuid.uuid4()), topic_id=str(run.topic_id),
            output_type="text",
            interactive=False,  # a review never raises a question card
            triggered_by=actor,
            runbook_run=_run_block(run, index, count, review=True),
        )
        row = ChatMessage.objects.filter(id=msg_id).first() if msg_id else None
    except Exception:  # noqa: BLE001 -- a broken reviewer must not kill the chain
        logger.exception("[runbook] run %s: the supervisor review itself failed", run.id)
        row = None
    if row is None or row.status != ChatMessage.Status.COMPLETED:
        _announce(run, f"Chain: {run.runbook.title} — the reviewer could not review step {index + 1}; the step stands.")
        return "unreviewed", ""
    return _parse_verdict(row.content or "")


# ── Checkpoints (Step 7, ruling 4) ──────────────────────────────────────

def may_answer_checkpoint(user, run) -> bool:
    """Ruling 4: the starter, or any of the four roles (the project.update
    holders — same four as the configure fence). Fails CLOSED on an
    unregistered right, like the Step 6 fence."""
    from authn.permissions.checker import PermissionChecker

    if user is None:
        return False
    if run.started_by_id and str(run.started_by_id) == str(user.id):
        return True
    try:
        return PermissionChecker.can(user, "project.update", obj=run.project)
    except ValueError:
        return False


def answer_checkpoint(run, user, answer: str):
    """Record the person's answer, step past the checkpoint and re-enqueue the
    run. Returns the refreshed run, or None when someone else got there first
    (the WAITING→QUEUED claim is the lock, like execute_run's)."""
    from nucleus.models import RunbookRun
    from scheduling.tasks import run_runbook

    claimed = RunbookRun.objects.filter(id=run.id, status=RunbookRun.Status.WAITING).update(
        status=RunbookRun.Status.QUEUED, updated_at=timezone.now(),
    )
    if not claimed:
        return None
    checkpoint = run.checkpoint or {}
    index = int(checkpoint.get("index", max(run.current_step, 0)))
    answer = (answer or "").strip()
    name = user.get_display_name()
    run.step_results = [*(run.step_results or []), {
        "index": index, "kind": "checkpoint", "status": "answered",
        "question": checkpoint.get("question", ""), "answer": answer[:PROMPT_MAX], "answered_by": name,
        "persona_id": None, "persona_name": None, "message_id": None, "error": "",
        "started_at": checkpoint.get("asked_at"), "ended_at": timezone.now().isoformat(),
    }]
    block = f"A person ({name}) answered the checkpoint question \"{checkpoint.get('question', '')}\":\n{answer}"
    run.context = f"{run.context}\n\n{block}".strip() if (run.context or "").strip() else block
    run.checkpoint = None
    run.current_step = index + 1
    run.status = RunbookRun.Status.QUEUED
    run.save(update_fields=["step_results", "context", "checkpoint", "current_step", "status", "updated_at"])
    _announce(run, f"Chain: {run.runbook.title} — {name} answered the checkpoint; continuing.")
    _publish_run(run)
    run_runbook.delay(str(run.id))
    return run


def expire_waiting_run(run) -> None:
    """24 hours passed with nobody answering (ruling 4, same window as question
    cards): the checkpoint's own on_failure decides — skip carries on past it,
    stop ends the run. Claim-guarded against a racing answer."""
    from nucleus.models import RunbookRun
    from scheduling.tasks import run_runbook

    claimed = RunbookRun.objects.filter(id=run.id, status=RunbookRun.Status.WAITING).update(
        status=RunbookRun.Status.QUEUED, updated_at=timezone.now(),
    )
    if not claimed:
        return
    checkpoint = run.checkpoint or {}
    index = int(checkpoint.get("index", max(run.current_step, 0)))
    steps = run.runbook.steps or []
    step = steps[index] if 0 <= index < len(steps) else {}
    run.step_results = [*(run.step_results or []), {
        "index": index, "kind": "checkpoint", "status": "expired",
        "question": checkpoint.get("question", ""),
        "persona_id": None, "persona_name": None, "message_id": None,
        "error": "nobody answered within 24 hours",
        "started_at": checkpoint.get("asked_at"), "ended_at": timezone.now().isoformat(),
    }]
    run.checkpoint = None
    if step.get("on_failure") == "skip":
        run.current_step = index + 1
        run.save(update_fields=["step_results", "checkpoint", "current_step", "updated_at"])
        _announce(run, f"Chain: {run.runbook.title} — the checkpoint expired with no answer; skipping it.")
        _publish_run(run)
        run_runbook.delay(str(run.id))
        return
    run.save(update_fields=["step_results", "checkpoint", "updated_at"])
    _end(run, RunbookRun.Status.FAILED,
         error="The checkpoint expired — nobody answered within 24 hours.",
         line=f"Chain: {run.runbook.title} failed — its checkpoint expired with nobody answering.")
