"""
The AI log as ONE downloadable story per topic (owner's ruling 2026-10-31:
"this md, should be a complete story, a complete diagnostic, like what search
from vector db, what from system prompt, what from file … how its compact,
and how its becomes final prompt and what returned by model, then any
response by tool"; "after this app stabalize, i want to focus on how our
context is being built").

build_topic_story(project, topic) → (filename, markdown). The topic's
messages in order; under every AI reply, each model RUN's chapters:

  1. the question            5. the tool loop, turn by turn
  2. ingredients gathered    6. response, tokens, cache, latency
  3. the trimming story      7. after the reply — the memory pass
  4. the final prompt (exact)

Older rows (written before the complete-story capture) render whatever they
carry — sections with text, the message, the response.

SECRETS: keys never enter the log by construction (the WP3 key rides run
metadata, never args; results carry has_api_key only) — and the whole file
still passes redact() before it leaves, so a key pasted into chat or a
tool's output is masked too. Pinned by tests.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from django.utils.text import slugify

MESSAGE_CAP = 6_000

_SECRET_PATTERNS = [
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{10,}"),
    re.compile(r"sk-(?:proj-)?[A-Za-z0-9_\-]{16,}"),
    re.compile(r"gsk_[A-Za-z0-9]{16,}"),
    re.compile(r"AIza[0-9A-Za-z_\-]{30,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"xox[abprs]-[A-Za-z0-9\-]{10,}"),
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{16,}"),
    re.compile(r"(?i)(\"?(?:api[_-]?key|secret|password|token)\"?\s*[:=]\s*\"?)([^\s\",}]{8,})"),
]


def redact(text: str) -> str:
    """Mask anything shaped like a credential. Applied to the WHOLE file."""
    for pattern in _SECRET_PATTERNS:
        if pattern.groups:
            text = pattern.sub(lambda m: m.group(1) + "[redacted]", text)
        else:
            text = pattern.sub("[redacted]", text)
    return text


def _fence(body: str, lang: str = "") -> str:
    """A code fence longer than any backtick run inside the body."""
    body = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False, indent=2, default=str)
    longest = max((len(m) for m in re.findall(r"`+", body)), default=0)
    ticks = "`" * max(3, longest + 1)
    return f"{ticks}{lang}\n{body.rstrip()}\n{ticks}"


def _clip(text: str, cap: int) -> str:
    text = text or ""
    return text if len(text) <= cap else text[:cap] + f"… [+{len(text) - cap} chars]"


def _n(value) -> str:
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return "?"


def _cell(text) -> str:
    return str(text if text is not None else "").replace("|", "\\|").replace("\n", " ")


def _run_chapters(log, index: int) -> list[str]:
    b = log.breakdown or {}
    out: list[str] = []

    # ── the memory pass is its own entry (role "memory") ──
    if log.role == "memory":
        mp = b.get("memory_pass") or {}
        out.append("#### 7. After the reply — the memory pass")
        if mp.get("skipped"):
            out.append(f"Skipped: {mp['skipped']}.")
        if mp.get("error"):
            out.append(f"**Failed:** {mp['error']}")
        if mp.get("model"):
            out.append(f"Decided by **{mp['model']}**.")
        rulings = mp.get("rulings") or []
        if rulings:
            out.append("\n| # | tool | decision | summary |\n|---|---|---|---|")
            out += [f"| {r.get('index')} | {_cell(r.get('tool'))} | {_cell(r.get('action'))} "
                    f"| {_cell(_clip(r.get('summary') or '', 300))} |" for r in rulings]
        saved = mp.get("saved") or []
        out.append(f"\n**Saved to project memory: {len(saved)} row(s).**")
        for row in saved:
            out.append(f"- `{row.get('label', '')}`\n\n{_fence(row.get('text', ''), 'text')}")
        return out

    head = (f"### Run {index} — {log.role or 'run'} · {log.model_name or log.model_id or '?'}"
            f" ({log.provider or '?'}/{log.model_id or '?'}) · **{log.status}**")
    out.append(head)
    facts = [f"{log.latency_ms / 1000:.1f} s" if log.latency_ms else None,
             f"in {_n(log.prompt_tokens)} / out {_n(log.completion_tokens)} tokens",
             f"cache read {_n(b.get('cache_read_tokens'))}" if b.get("cache_read_tokens") else None,
             f"{b.get('model_calls')} model calls" if b.get("model_calls") else None,
             "fallback attempt " + str(b.get("fallback_attempt")) if b.get("fallback_attempt") else None,
             "resumed after a pause" if b.get("resume") else None]
    out.append(" · ".join(f for f in facts if f))

    # 1. the question
    if b.get("message"):
        out.append("#### 1. The question")
        out.append(_fence(b["message"], "text"))

    # 2. ingredients gathered
    out.append("#### 2. Ingredients gathered")
    rd = b.get("retrieval_detail")
    if rd:
        out.append(f"**Memory search** — query: _{_cell(_clip(rd.get('query', ''), 300))}_ · "
                   f"top {rd.get('top_k')} · cut-off score {rd.get('min_score')} · "
                   f"{rd.get('scopes', '')}")
        if rd.get("error"):
            out.append(f"Search failed: {rd['error']} — the reply ran without memory.")
        hits = rd.get("hits") or []
        if hits:
            out.append("\n| score | kind | label | excerpt |\n|---|---|---|---|")
            out += [f"| {h.get('score')} | {_cell(h.get('kind'))} | {_cell(h.get('label'))} "
                    f"| {_cell(_clip(h.get('excerpt') or '', 400))} |" for h in hits]
        else:
            out.append("No hit cleared the cut-off — nothing from memory went into the prompt.")
    elif b.get("retrieval"):
        out.append("**Memory hits:** " + ", ".join(
            f"{_cell(r.get('label'))} ({r.get('score')})" for r in b["retrieval"]))
    else:
        out.append("**Memory search:** not run (no index yet, a resumed run, or memory off).")
    sections = b.get("sections") or []
    if sections:
        out.append("\n**Prompt sections** (after trimming):\n")
        out += [f"- `{s.get('kind')}` — {_n(s.get('chars'))} chars" for s in sections]
    history = b.get("history")
    if history:
        out.append(f"\n**History sent ({len(history)} message(s)):**\n")
        for h in history:
            who = h.get("author") or h.get("role")
            out.append(f"- **{h.get('role')}{(' · ' + who) if who and who != h.get('role') else ''}:** "
                       f"{_cell(_clip(h.get('text') or '', 1500))}")
    elif "history_count" in b:
        out.append(f"\n**History sent:** {b.get('history_count')} message(s) (text not recorded for this run).")

    # 3. trimming
    trim = b.get("trim")
    out.append("#### 3. Trimming — how the prompt was fitted")
    if trim:
        out.append(f"Model **{trim.get('model')}** · window {_n(trim.get('context_window'))} · "
                   f"reply cap {_n(trim.get('reply_cap'))} · loop headroom {_n(trim.get('loop_headroom'))} "
                   f"→ input budget {_n(trim.get('input_budget'))} · target {_n(trim.get('target'))} "
                   f"({trim.get('target_pct')}%)")
        out.append(f"Estimated prompt: **{_n(trim.get('tokens_before'))} → {_n(trim.get('tokens_after'))} tokens**"
                   + (" — trimmed." if trim.get("trimmed") else " — fitted without cuts."))
        if trim.get("protected_over_target"):
            out.append("⚠ Protected content alone exceeded the target — sent anyway.")
        items = trim.get("items") or []
        if items:
            out.append("\n| ingredient | tokens | kept | why |\n|---|---|---|---|")
            out += [f"| {_cell(i.get('what'))} | {_n(i.get('tokens'))} | "
                    f"{'yes' if i.get('kept') else '**DROPPED**'} | {_cell(i.get('reason', ''))} |"
                    for i in items]
    else:
        out.append("Not recorded for this run (a resumed run continues its stored state, "
                   "or the row predates the trimming capture).")

    # 4. the final prompt
    out.append("#### 4. The final prompt, exactly as sent")
    if b.get("final_instructions"):
        out.append("**Instructions (system):**")
        out.append(_fence(b["final_instructions"], "text"))
    else:
        for s in sections:
            if s.get("text"):
                out.append(f"**Section `{s.get('kind')}`:**")
                out.append(_fence(s["text"], "text"))
    if b.get("extra_instructions"):
        out.append("**Added for routing / hand-over:**")
        out.append(_fence(b["extra_instructions"], "text"))
    out.append("Then: the history above, then the question.")

    # 5. the tool loop
    transcript = b.get("transcript") or []
    out.append("#### 5. The run, turn by turn")
    if transcript:
        for n, turn in enumerate(transcript, 1):
            step = turn.get("step")
            if step == "tool_call":
                out.append(f"{n}. **Model called `{turn.get('tool')}`**")
                out.append(_fence(turn.get("args") or "", "json"))
            elif step == "tool_result":
                out.append(f"{n}. **Result from `{turn.get('tool')}`**")
                out.append(_fence(turn.get("content") or "", "text"))
            elif step == "model_text":
                out.append(f"{n}. **Model said**")
                out.append(_fence(turn.get("content") or "", "text"))
            elif step == "model_thinking":
                out.append(f"{n}. **Model reasoning**")
                out.append(_fence(turn.get("content") or "", "text"))
            elif step == "retry":
                out.append(f"{n}. **Retry asked of the model** (`{turn.get('tool') or ''}`)")
                out.append(_fence(turn.get("content") or "", "text"))
            elif step == "user":
                out.append(f"{n}. **Prompt to the model**")
                out.append(_fence(turn.get("content") or "", "text"))
            else:
                out.append(f"{n}. {turn.get('content', '')}")
    else:
        out.append("No turn record (the row predates the tool-loop capture, or the run ended before a turn).")

    # 6. outcome
    out.append("#### 6. Outcome")
    if log.error:
        out.append(f"**Error:** {log.error}")
    if log.response:
        out.append("**Response:**")
        out.append(_fence(log.response, "text"))
    elif not log.error:
        out.append(f"No text response (status **{log.status}**).")
    return out


def build_topic_story(project, topic, user=None) -> tuple[str, str]:
    from nucleus.models import AIRequestLog, ChatMessage, Persona

    messages = list(ChatMessage.objects.filter(topic=topic, is_active=True)
                    .select_related("sender").order_by("sequence", "created_at"))
    logs = list(AIRequestLog.objects.filter(project=project, topic_id=str(topic.id))
                .order_by("created_at"))
    by_msg: dict[str, list] = {}
    for log in logs:
        by_msg.setdefault(log.msg_id, []).append(log)
    persona_ids = {log.persona_id for log in logs if log.persona_id}
    names = {p.id: p.name for p in Persona.objects.filter(id__in=persona_ids)} if persona_ids else {}

    now = datetime.now(timezone.utc)
    channel = getattr(topic, "channel", None)
    lines = [
        f"# AI log — {project.name} / {getattr(channel, 'name', '?')} / {topic.title}",
        "",
        f"Exported {now.strftime('%Y-%m-%d %H:%M UTC')}"
        + (f" by {getattr(user, 'email', '')}" if user else "")
        + f" · {len(messages)} message(s) · {sum(1 for l in logs if l.role != 'memory')} model run(s)",
        "",
        "Every AI reply below tells its whole story: the question, what was gathered (memory "
        "search with scores, history, prompt sections), how the prompt was trimmed to fit, the "
        "exact final prompt, every tool call and result, the outcome, and what memory kept "
        "afterwards. Credentials are masked.",
        "",
    ]
    seen: set[str] = set()
    for message in messages:
        meta = message.metadata or {}
        is_ai = "persona_id" in meta
        author = meta.get("persona_name") if is_ai else (
            message.sender.get_display_name() if message.sender_id else "system")
        stamp = message.created_at.strftime("%Y-%m-%d %H:%M:%S") if message.created_at else ""
        lines.append(f"---\n\n## {'🤖 ' if is_ai else ''}{author} · {stamp}")
        if message.is_deleted_from_context:
            lines.append("_(removed from AI context by a person)_")
        if message.content:
            lines.append(_clip(message.content, MESSAGE_CAP))
        runs = by_msg.get(str(message.id), [])
        seen.add(str(message.id))
        model_runs = [r for r in runs if r.role != "memory"]
        for n, run in enumerate(model_runs, 1):
            lines += [""] + _run_chapters(run, n)
        for run in runs:
            if run.role == "memory":
                lines += [""] + _run_chapters(run, 0)
        lines.append("")

    # runs whose message is gone (deleted/expired) still belong to the story
    orphans = [log for log in logs if log.msg_id not in seen]
    if orphans:
        lines.append("---\n\n## Runs whose message is no longer in the topic\n")
        for n, run in enumerate(orphans, 1):
            who = names.get(run.persona_id, "")
            lines.append(f"_message {run.msg_id}{' · ' + who if who else ''}_")
            lines += _run_chapters(run, n) + [""]

    filename = (f"{slugify(project.name) or 'project'}-{slugify(topic.title) or 'topic'}"
                f"-ai-log-{now.strftime('%Y%m%d-%H%M')}.md")
    return filename, redact("\n".join(lines) + "\n")
