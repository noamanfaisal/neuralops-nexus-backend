"""
Honesty check (B7, fix round 2026-10-28).

Found live 2026-10-27: after three real auth failures in one topic, a reply
twice wrote "Attempted now: aaf_analytics__get_schema → missing or invalid
bearer token" with NO tool call behind it (no tool row in the chat, nothing in
the server's log). The prompt rule (prompts/layout.py) forbids inventing
attempts; this check CATCHES the slip after the fact so a reader is never left
believing a run happened.

Deliberately narrow — a false flag on an honest reply would be worse than a
missed slip, so a line is flagged only when ALL of these hold:
  * it contains one of the persona's EXACT tool names (catalog model_names —
    distinctive machine tokens such as `aaf_analytics__get_schema`, never
    prose words), for a tool that was NOT called in this run;
  * it claims a completed attempt: a past-tense claim word (attempted, ran,
    called, executed, invoked, tried, failed) or a result arrow (→ / ->);
  * nothing on the line marks it as memory, intent or honest inability
    ("earlier we ran …", "I will call …", "I couldn't call …",
    "# not executed: …" — all spared).
"""
from __future__ import annotations

import re
from typing import Iterable, Sequence

# Completed-attempt wording only. Present/future forms ("I can call X",
# "I will run X", "let me try X") are honest intent, never flagged.
_CLAIM = re.compile(
    r"\b(attempted|ran|called|executed|invoked|tried|failed)\b", re.IGNORECASE
)
_ARROWS = ("→", "->")

# Words that mark the line as remembered, conditional or an honest refusal.
_SPARED = re.compile(
    r"\b(earlier|previous(?:ly)?|last time|before|remember(?:ed)?|"
    r"will|would|could|going to|about to|planning|"
    r"cannot|can['’]t|couldn['’]t|unable|unavailable|not available|"
    r"not allowed|no access|not (?:executed|run|called|attempted)|"
    r"if\b|when\b)",
    re.IGNORECASE,
)


def phantom_tool_claims(
    text: str,
    catalog_names: Sequence[str],
    used_names: Iterable[str],
) -> list[str]:
    """Tool names the reply claims were attempted in THIS reply although no
    such call happened in the run. Order of first appearance; empty when the
    reply is honest (the overwhelmingly common case)."""
    if not text:
        return []
    used = {n.strip().lower() for n in used_names if n}
    suspects = [n for n in catalog_names if n and n.strip().lower() not in used]
    if not suspects:
        return []
    flagged: list[str] = []
    for line in text.splitlines():
        low = line.lower()
        named = [n for n in suspects if n.lower() in low and n not in flagged]
        if not named:
            continue
        if not (_CLAIM.search(line) or any(a in line for a in _ARROWS)):
            continue
        if _SPARED.search(line):
            continue
        flagged.extend(named)
    return flagged


def honesty_note(flagged: Sequence[str]) -> str:
    """The visible correction appended to a text reply that slipped."""
    names = ", ".join(flagged)
    plural = "calls" if len(flagged) > 1 else "call"
    return (
        f"— Correction (added automatically): this reply describes {names} as "
        f"attempted, but no such tool {plural} happened in this reply."
    )
