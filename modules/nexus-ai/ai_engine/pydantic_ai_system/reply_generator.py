"""
ReplyGenerator — produce one reply with pydantic-ai: build the agent, convert
messages, stream, collect usage. One instance serves one run (the factory
builds a fresh graph per request).

usage_records() is available after ANY ending — done, pause, cancel, or error:
  - normal end: one record per ModelResponse in the run,
    read by UsageReader (which flags the cut-stream shapes estimated);
  - paused (item 2): same — the paused call's usage is real (trial D5/E2);
  - cancelled: one estimated record from whatever was received;
  - error: one estimated record, so a model 500 still bills its input (T9).

Item 2: a run that ends in DeferredToolRequests sets pause_info() — the caller
(PydanticAISystem) saves it to nucleus and closes with message_paused. A
resume (TriggerJob.resume) re-enters with the stored messages as history and
the decisions as DeferredToolResults — no new user prompt.

Items 13/46: one PydanticAISystem may call generate() more than once per reply
(router run, then deep run) — usage records ACCUMULATE across calls; a run
ending in Escalate sets escalation(); handover= appends the router's note to
the deep run's instructions.

Item 12 (fallbacks, opt-in per persona): each run tries the seat's model, then
the persona's FALLBACK models in order — a whole fresh stream per candidate,
and NEVER a switch once the first token reached the reader (mapper.text() is
the witness). The failed attempt still bills (estimated). fallback_used()
names the candidate that answered, for the "answered by X (fallback)" label.

Item 16 (selection + limits): the plan is trimmed to the primary model's
budget BEFORE the run (BudgetFitter — selection, §4.1); persona.max_steps
becomes UsageLimits(request_limit=...), finally capping agent rounds.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import replace as dc_replace
from datetime import datetime, timezone

from pydantic_ai.messages import (
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    UserPromptPart,
)
from pydantic_ai.run import AgentRunResultEvent
from pydantic_ai.tools import DeferredToolRequests, DeferredToolResults, ToolApproved, ToolDenied
from pydantic_ai.usage import UsageLimits

from ai_engine.context.budget import BudgetFitter, budget_for
from ai_engine.core.config import EngineSettings
from ai_engine.core.specs import (
    ModelRole,
    ModelSpec,
    PauseInfo,
    PendingApproval,
    ReplyRequest,
    UsageRecord,
)
from ai_engine.pydantic_ai_system.agent_builder import AgentBuilder
from ai_engine.pydantic_ai_system.escalation import Escalate, handover_suffix, router_instructions
from ai_engine.pydantic_ai_system.event_mapper import EventMapper
from ai_engine.pydantic_ai_system.message_converter import MessageConverter
from ai_engine.pydantic_ai_system.tools.approval_gate import ApprovalGate
from ai_engine.pydantic_ai_system.tools.approval_policy import DENIED, args_preview
from ai_engine.pydantic_ai_system.tools.ask_user import ASK_USER_CAPABILITY_ID, ask_user_toolset
from ai_engine.pydantic_ai_system.usage_reader import UsageReader
from fastapi_app.contracts.trigger import AgentEvent, ResumeBlock

log = logging.getLogger(__name__)

# 1.3.0 AI audit log: the anatomy keeps FULL section/response text up to this
# cap per field — enough to read a whole system prompt, bounded so one giant
# retrieval dump can't bloat the nucleus row.
AUDIT_TEXT_CAP = 20_000
AUDIT_ERROR_CAP = 500
# The complete-story additions (owner's ruling 2026-10-31): the exact final
# instructions string, each history message as sent, and every turn of the
# tool loop — capped per item so one giant tool result can't bloat the row.
AUDIT_INSTRUCTIONS_CAP = 60_000
AUDIT_HISTORY_CAP = 4_000
AUDIT_TURN_CAP = 8_000
AUDIT_MAX_TURNS = 200


def _clip(text: str, cap: int) -> str:
    text = text or ""
    return text if len(text) <= cap else text[:cap] + f"… [+{len(text) - cap} chars]"


def _as_text(value) -> str:
    if isinstance(value, str):
        return value
    try:
        import json
        return json.dumps(value, ensure_ascii=False, default=str)
    except Exception:  # noqa: BLE001
        return str(value)


def _transcript(messages) -> list[dict]:
    """The run's tool loop turn by turn, for the AI log: what the model said
    or asked for, each tool call with its args, each tool's result, retries.
    Read off pydantic-ai's own message list by part_kind — no framework
    imports needed, and an unknown part kind is skipped, never fatal."""
    turns: list[dict] = []
    for message in messages or []:
        kind = getattr(message, "kind", "")
        for part in getattr(message, "parts", []) or []:
            pk = getattr(part, "part_kind", "")
            if kind == "response" and pk == "text":
                turns.append({"step": "model_text", "content": _clip(part.content, AUDIT_TURN_CAP)})
            elif kind == "response" and pk == "thinking":
                turns.append({"step": "model_thinking", "content": _clip(part.content, AUDIT_TURN_CAP)})
            elif kind == "response" and pk == "tool-call":
                turns.append({"step": "tool_call", "tool": part.tool_name,
                              "call_id": part.tool_call_id,
                              "args": _clip(_as_text(part.args), AUDIT_TURN_CAP)})
            elif kind == "request" and pk == "tool-return":
                turns.append({"step": "tool_result", "tool": part.tool_name,
                              "call_id": part.tool_call_id,
                              "content": _clip(_as_text(part.content), AUDIT_TURN_CAP)})
            elif kind == "request" and pk == "retry-prompt":
                turns.append({"step": "retry", "tool": getattr(part, "tool_name", None),
                              "content": _clip(_as_text(part.content), AUDIT_TURN_CAP)})
            elif kind == "request" and pk == "user-prompt":
                turns.append({"step": "user", "content": _clip(_as_text(part.content), AUDIT_TURN_CAP)})
            if len(turns) >= AUDIT_MAX_TURNS:
                turns.append({"step": "truncated", "content": f"more than {AUDIT_MAX_TURNS} turns"})
                return turns
    return turns


def _transcript_from_outputs(outputs: list[dict]) -> list[dict]:
    """A failed run has no result to read — the mapper's tool outputs are the
    best record of what ran before it died."""
    turns: list[dict] = []
    for out in outputs[:AUDIT_MAX_TURNS]:
        turns.append({"step": "tool_call", "tool": out.get("tool"),
                      "args": _clip(_as_text(out.get("args") or {}), AUDIT_TURN_CAP)})
        turns.append({"step": "tool_result", "tool": out.get("tool"),
                      "content": _clip(_as_text(out.get("content") or ""), AUDIT_TURN_CAP)})
    return turns


class ReplyGenerator:
    def __init__(self, agents: AgentBuilder, converter: MessageConverter, usage: UsageReader,
                 fitter: BudgetFitter | None = None,
                 settings: EngineSettings | None = None) -> None:
        self._agents = agents
        self._converter = converter
        self._usage = usage
        self._fitter = fitter          # item 16: selection before the run
        self._settings = settings
        self._records: list[UsageRecord] = []   # accumulated across ALL runs of this reply
        self._mapper: EventMapper | None = None
        self._pause: PauseInfo | None = None
        self._escalation: Escalate | None = None
        self._used_tools: list[str] = []
        self._tool_outputs: list[dict] = []  # item 27: fed to the memory pass
        self._fallback: ModelSpec | None = None  # item 12: who answered, when not the seat's own
        # 1.3.0 audit: one dict per model RUN (a fallback or hand-over adds
        # another), accumulated across this reply's runs like _records.
        self._audits: list[dict] = []

    async def generate(self, request: ReplyRequest, capabilities: list | None = None,
                       resume: ResumeBlock | None = None, catalog_hash: str = "",
                       allow_escalation: bool = False, handover: Escalate | None = None,
                       allow_ask: bool = True, nudges=None, delegate=None,
                       primary: ModelSpec | None = None):
        """capabilities: harness/pydantic-ai capability objects from
        ToolsetBuilder (Layer 1); None/empty keeps the Layer 0 toolless path.
        resume: the pause state + decisions (item 2) — the run continues
        instead of starting from the new message.
        allow_escalation: this run may end with an Escalate (items 13/46).
        handover: a previous routing run's note — appended to the instructions.
        allow_ask: item 5 — this run may ask the person a question (ask_user);
        the router's screening run passes False, and an unattended job never
        gets the tool regardless (nobody can answer).
        delegate: item 46 — the call_persona toolset, when this persona may
        run others (built by the caller; None = no delegation this run).
        primary: the exact model this run uses — the smart router's BENCH
        pick on a DEEP run; None = the seat's first model (every other run)."""
        persona = request.persona
        ask = allow_ask and request.job.interactive  # item 5
        toolsets: list = ([ask_user_toolset()] if ask else [])  # item 5
        if delegate is not None:
            toolsets.append(delegate)  # item 46
        primary = primary or persona.model_for(request.role)
        # item 12: the seat's model first, then the persona's fallbacks in order
        candidates = [primary] + [m for m in persona.models if m.role is ModelRole.FALLBACK]

        # item 16: SELECTION — trim the plan to the primary model's budget
        # before anything is sent (a resume continues a stored state untouched)
        plan = request.plan
        trim: dict | None = None   # the AI log's trimming story
        if self._fitter is not None and self._settings is not None and resume is None:
            # 7b (2026-10-20): the PRIMARY CANDIDATE's own output cap — per
            # model, no longer one persona-wide number.
            budget = budget_for(primary, self._settings.budget_loop_headroom,
                                self._settings.budget_target_pct, self._settings.budget_trigger_pct,
                                primary.max_output_tokens)
            plan, trim = self._fitter.fit_report(plan, budget)
            trim = {"model": primary.name, "context_window": primary.context_window,
                    "reply_cap": primary.max_output_tokens,
                    "loop_headroom": self._settings.budget_loop_headroom,
                    "target_pct": self._settings.budget_target_pct, **trim}

        instructions = self._converter.instructions(plan)
        # 1.3.0 audit: anything appended BEYOND the plan's sections is recorded
        # separately, so the log shows the router bench / hand-over note as its
        # own ingredient instead of vanishing into "instructions".
        extra_instructions = ""
        if allow_escalation:
            # Smart router: with a bench of 2+ deep models the instructions
            # list them with their strengths, so the run can NAME its pick.
            extra_instructions += router_instructions(persona.models_for(ModelRole.DEEP))
        if handover is not None:
            extra_instructions += handover_suffix(handover)
        instructions += extra_instructions

        if resume is not None:
            history = list(ModelMessagesTypeAdapter.validate_json(resume.state))
            prompt = None
            deferred = _deferred_results(resume)
        else:
            history = self._converter.to_messages(plan.history)
            prompt = plan.message
            deferred = None
        request_messages: list[ModelMessage] = list(history)
        if prompt is not None:
            request_messages.append(ModelRequest(parts=[UserPromptPart(content=prompt)]))

        # item 16: max_steps finally enforced — caps agent rounds in the loop
        usage_limits = (UsageLimits(request_limit=persona.max_steps)
                        if persona.max_steps and persona.max_steps > 0 else None)

        gate = next((c for c in capabilities or [] if isinstance(c, ApprovalGate)), None)
        mapper: EventMapper | None = None
        base: UsageRecord | None = None
        result = None
        for index, candidate in enumerate(candidates):
            started = time.monotonic()
            # 1.3.0 audit: the prompt anatomy AS THIS RUN SENT IT — the plan's
            # sections post-fit (what instructions= was built from), the extra
            # instructions, the converted history count and the user message.
            audit = {
                "role": request.role.value,
                "provider": candidate.provider,
                "model_id": candidate.model_id,
                "model_name": candidate.name,
                "resume": resume is not None,
                "fallback_attempt": index,
                "sections": [
                    {"kind": s.kind, "chars": len(s.text), "text": s.text[:AUDIT_TEXT_CAP]}
                    for s in plan.instructions
                ],
                "extra_instructions": extra_instructions[:AUDIT_TEXT_CAP],
                "history_count": len(history),
                "message": (prompt or "")[:AUDIT_TEXT_CAP],
                "started_at": datetime.now(timezone.utc).isoformat(),
                # ── the complete story (owner's ruling 2026-10-31) ──
                "trim": trim,
                # the history AS SENT (post-trim); a resume continues a stored
                # run state instead — its turns appear in the transcript
                "history": ([] if resume is not None else [
                    {"role": m.role, "author": m.author, "text": _clip(m.text, AUDIT_HISTORY_CAP)}
                    for m in plan.history
                ]),
                # the exact instructions string the model received
                "final_instructions": _clip(instructions, AUDIT_INSTRUCTIONS_CAP),
            }
            agent = self._agents.build(persona, request.role, instructions,
                                       escalate=allow_escalation, spec=candidate)
            mapper = EventMapper(
                msg_id=request.job.msg_id, persona=persona,
                tool_capability_ids=gate.tool_capability_ids if gate else None,
            )
            self._mapper = mapper
            self._pause = None
            self._last_run_start = len(self._records)
            base = _base_record(request, candidate)
            result = None
            try:
                async with agent.run_stream_events(
                    prompt, message_history=history,
                    capabilities=capabilities or None,
                    toolsets=toolsets or None,  # items 5 + 46
                    deferred_tool_results=deferred,
                    usage_limits=usage_limits,
                ) as run:
                    async for event in run:
                        if isinstance(event, AgentRunResultEvent):
                            result = event.result
                        for out in mapper.map(event):
                            yield out
                        if nudges is not None:
                            # W8 design point 2: a taken nudge's event rides
                            # out with the next flush — no side-channel merge.
                            for pending in nudges.drain():
                                yield pending
                for out in mapper.flush():
                    yield out
                if nudges is not None:
                    for pending in nudges.drain():
                        yield pending
            except asyncio.CancelledError:
                self._records.append(self._usage.read(None, request_messages, mapper.text(), True, base))
                self._used_tools.extend(t for t in mapper.used_tools if t not in self._used_tools)
                self._tool_outputs.extend(mapper.tool_outputs)
                rec = self._records[-1]
                self._audits.append({**audit, "status": "cancelled", "error": None,
                                     "response": mapper.text()[:AUDIT_TEXT_CAP],
                                     "prompt_tokens": rec.input_tokens, "completion_tokens": rec.output_tokens,
                                     "latency_ms": int((time.monotonic() - started) * 1000)})
                raise
            except Exception as exc:
                self._records.append(self._usage.read(None, request_messages, mapper.text(), False, base))
                self._used_tools.extend(t for t in mapper.used_tools if t not in self._used_tools)
                self._tool_outputs.extend(mapper.tool_outputs)
                rec = self._records[-1]
                self._audits.append({**audit, "status": "failed", "error": str(exc)[:AUDIT_ERROR_CAP],
                                     "response": mapper.text()[:AUDIT_TEXT_CAP],
                                     "prompt_tokens": rec.input_tokens, "completion_tokens": rec.output_tokens,
                                     "latency_ms": int((time.monotonic() - started) * 1000),
                                     "transcript": _transcript_from_outputs(mapper.tool_outputs)})
                # item 12: retry on the next candidate ONLY while the reader has
                # seen nothing — never switch voices mid-reply.
                if mapper.text() == "" and index < len(candidates) - 1:
                    log.warning("model %s failed before first token — trying fallback %s",
                                candidate.model_id, candidates[index + 1].model_id)
                    continue
                raise
            self._audits.append({**audit, "status": "done", "error": None,
                                 "response": mapper.text()[:AUDIT_TEXT_CAP],
                                 "latency_ms": int((time.monotonic() - started) * 1000)})
            if index > 0:
                self._fallback = candidate
            break

        responses = (
            [m for m in result.new_messages() if isinstance(m, ModelResponse)] if result else []
        )
        if responses:
            self._records.extend(
                self._usage.read(r, request_messages, mapper.text(), False, base) for r in responses
            )
        else:  # the stream ended without a result — estimated, like a cut
            self._records.append(self._usage.read(None, request_messages, mapper.text(), False, base))
        self._used_tools.extend(t for t in mapper.used_tools if t not in self._used_tools)
        self._tool_outputs.extend(mapper.tool_outputs)
        if self._audits:
            # 1.3.0 audit: the finished run's token totals (the records for
            # THIS run start at _last_run_start — set per candidate above).
            run_records = self._records[self._last_run_start:]
            self._audits[-1]["prompt_tokens"] = sum(r.input_tokens for r in run_records)
            self._audits[-1]["completion_tokens"] = sum(r.output_tokens for r in run_records)
            self._audits[-1]["cache_read_tokens"] = sum(r.cache_read_tokens for r in run_records)
            self._audits[-1]["model_calls"] = len(run_records)
            # the tool loop, turn by turn (THIS run's messages only — the
            # history it started from is recorded separately above)
            self._audits[-1]["transcript"] = (
                _transcript(result.new_messages()) if result is not None
                else _transcript_from_outputs(mapper.tool_outputs if mapper else []))

        # Items 13/46: a run that produced an Escalate hands the reply over.
        output = result.output if result else None
        if isinstance(output, Escalate):
            self._escalation = output
            if self._audits:  # 1.3.0 audit: the run's real ending
                self._audits[-1]["status"] = "escalated"
            return

        # Item 2: a run that produced DeferredToolRequests is PAUSED, not done.
        # Item 5: ask_user calls land in output.calls — same pause, kind
        # "question"; the resume answers them instead of deciding them.
        if isinstance(output, DeferredToolRequests):
            names = gate.tool_capability_ids if gate else {}
            pending = [
                PendingApproval(
                    call_id=call.tool_call_id,
                    tool=call.tool_name,
                    capability_id=names.get(call.tool_name, ""),
                    args_preview=args_preview(call.args),
                )
                for call in output.approvals
            ] + [
                PendingApproval(
                    call_id=call.tool_call_id,
                    tool=call.tool_name,
                    capability_id=ASK_USER_CAPABILITY_ID,
                    args_preview=args_preview(call.args),
                    kind="question",
                )
                for call in output.calls
            ]
            self._pause = PauseInfo(
                state=ModelMessagesTypeAdapter.dump_json(result.all_messages()).decode(),
                pending=tuple(pending),
                catalog_hash=catalog_hash,
            )
            if self._audits:  # 1.3.0 audit: the run's real ending
                self._audits[-1]["status"] = "paused"

    def usage_records(self) -> list[UsageRecord]:
        """One per model call, ACCUMULATED across this reply's runs (items
        13/46: router + deep are separate records); available after any ending."""
        return list(self._records)

    def full_text(self) -> str:
        """The LAST run's text — on an escalation, the deep model's answer only
        (the router's stray words never enter the saved message)."""
        return self._mapper.text() if self._mapper else ""

    def pause_info(self) -> PauseInfo | None:
        """Set when the run paused on approvals (item 2); None otherwise."""
        return self._pause

    def escalation(self) -> Escalate | None:
        """Set when the last run handed the reply over (items 13/46)."""
        return self._escalation

    def used_tools(self) -> list[str]:
        """Tools that actually executed across this reply's runs (item 13 /
        Layer 3 bridge: stored on the message, later vector metadata)."""
        return list(self._used_tools)

    def tool_outputs(self) -> list[dict]:
        """The reply's full tool outputs (capped per output) — item 27's
        memory pass reviews these after message_done."""
        return list(self._tool_outputs)

    def audits(self) -> list[dict]:
        """1.3.0 AI audit log: one dict per model RUN of this reply — the
        prompt anatomy (sections post-fit, extra instructions, history count,
        message) plus the outcome (status/response/error/latency). Accumulates
        across runs like usage_records(); available after any ending."""
        return [dict(a) for a in self._audits]

    def fallback_used(self) -> ModelSpec | None:
        """The fallback model that answered, or None when the seat's own did
        (item 12 — feeds the "answered by X (fallback)" label)."""
        return self._fallback

    def set_source_on_last_run(self, source: str) -> None:
        """Mark the last run's records (e.g. source='router_failed' when the
        reply fell through to STANDARD after a broken router — item 13)."""
        start = getattr(self, "_last_run_start", 0)
        self._records[start:] = [dc_replace(r, source=source) for r in self._records[start:]]


def _deferred_results(resume: ResumeBlock) -> DeferredToolResults:
    # item 5: a question's answer IS the tool result
    calls: dict = dict(resume.answers or {})
    approvals: dict = {}
    # WP3 secure key card: a secret typed on the approval card rides to the
    # ONE approved call as RunContext metadata (ctx.tool_call_metadata) —
    # never as tool args, so it never enters the run state or the history.
    metadata: dict[str, dict] = {}
    for call_id, decision in resume.approvals.items():
        if decision.decision == "allow":
            approvals[call_id] = ToolApproved()
            if (decision.secret or "").strip():
                metadata[call_id] = {"secret": decision.secret.strip()}
        else:
            approvals[call_id] = ToolDenied(decision.reason or DENIED)
    return DeferredToolResults(approvals=approvals, calls=calls, metadata=metadata)


def _base_record(request: ReplyRequest, spec: ModelSpec) -> UsageRecord:
    job = request.job
    return UsageRecord(
        company_id=job.company_id,
        project_id=job.project_id,
        topic_id=job.topic_id,
        persona_id=job.persona_id,
        user_id=job.user_id,
        message_id=job.msg_id,
        job_id=job.job_id,
        kind="router" if request.role is ModelRole.ROUTER else "chat_reply",
        model_config_id=spec.config_id,
        provider=spec.provider,
        model_id=spec.model_id,
        role=request.role.value,
        provider_response_id=None,
        input_tokens=0,
        uncached_input_tokens=0,
        cache_read_tokens=0,
        cache_write_5m_tokens=0,
        cache_write_1h_tokens=0,
        output_tokens=0,
        reasoning_tokens=0,
        finish_reason=None,
        estimated=False,
        called_at=datetime.now(timezone.utc),
    )
