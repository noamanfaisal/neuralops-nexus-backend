"""
Recover a reply whose model followed the output contract but dropped the
<<<OUTPUT:...>>> markers around it (0.8.0, kept) — and, new in the rebuild,
VALIDATE the claimed type (Layer 4 decision 2: a claimed type that doesn't
hold falls back to text — a broken "html" must never reach the renderer).

Strict on purpose: the entire reply must be the object — prose around it means
the model was talking, not charting — and only the resolved type is recovered,
never a type the classifier did not pick. The one type every ordinary turn may
answer with is a choice prompt (CHOICE_EXCEPTION), so a reply shaped like one
is a choice whatever the turn resolved to — except a preflight turn, whose
instruction never offered it.
"""
from __future__ import annotations

import json
import re

from ai_engine.output_types.registry import OutputTypeRegistry, TYPES_WITHOUT_CHOICE

# A lone marker — the model opened without closing, or closed without opening.
_STRAY_MARKERS = re.compile(r"<{2,3}(?:OUTPUT:\w+|END_OUTPUT|EMBED|END_EMBED)>{0,3}")

# preflight joined 2026-10-31 (seen live, DeepSeek): a plan-first turn whose
# model answered with the bare plan JSON and no markers was saved as TEXT —
# no plan card, nothing to approve, so the work never ran. Only a preflight
# turn recovers it (the resolved type must be preflight), so an ordinary
# reply that happens to be JSON with "steps" is never misread as a plan.
RECOVERABLE = {"chart": ("type", "datasets"), "choice": ("question", "options"),
               "preflight": ("steps",)}

_FENCE = re.compile(r"^```[A-Za-z0-9_-]*\s*\n(.*)\n```$", re.DOTALL)

# Types whose content must be ONE JSON object to render at all.
_JSON_TYPES = {"chart", "choice", "preflight"}


def _unfence(text: str) -> str:
    """The body of a reply that is ONE fenced block (```json … ```), else the
    text unchanged — gpt-oss fences its JSON (seen live 2026-10-30)."""
    match = _FENCE.match(text.strip())
    return match.group(1).strip() if match else text


def _whole_object(content: str) -> dict | None:
    text = _unfence(_STRAY_MARKERS.sub("", content).strip())
    if not (text.startswith("{") and text.endswith("}")):
        return None
    try:
        value = json.loads(text)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def _shaped_as(kind: str, value: dict) -> bool:
    required = RECOVERABLE[kind]
    if kind == "choice":
        return all(key in value for key in required) and isinstance(value["options"], list) and bool(value["options"])
    if kind == "preflight":
        return isinstance(value.get("steps"), list) and bool(value["steps"])
    # one description, or a reply of several: {"charts": [description, ...]}
    candidates = value.get("charts") if "charts" in value else [value]
    if not isinstance(candidates, list) or not candidates:
        return False
    return all(isinstance(c, dict) and all(key in c for key in required) for c in candidates)


def recover_unmarked(resolved_type: str, content: str, allow_choice: bool = True) -> str | None:
    value = _whole_object(content)
    if value is None:
        return None
    if resolved_type in RECOVERABLE and _shaped_as(resolved_type, value):
        return resolved_type
    if allow_choice and resolved_type not in TYPES_WITHOUT_CHOICE and _shaped_as("choice", value):
        return "choice"
    return None


def strip_stray_markers(content: str) -> str:
    return _STRAY_MARKERS.sub("", content).strip()


def _holds(final_type: str, render_as: str, content: str) -> bool:
    """Decision 2's validation: does the content actually carry the type?"""
    if final_type in _JSON_TYPES:
        return _whole_object(content) is not None
    if render_as == "html":
        lowered = content.lstrip().lower()
        return lowered.startswith("<!doctype") or lowered.startswith("<html")
    return True


def finalise_reply(raw: str, resolved_type: str,
                   allow_choice: bool = True) -> tuple[str, str, str, str | None]:
    """
    What a finished reply is: (clean content, output type, render_as, embed
    description). Markers name the type; without them the reply is text —
    the model answered conversationally — unless it is the unmarked chart
    the run asked for. A claimed type whose content doesn't hold falls back
    to text (decision 2) rather than breaking the renderer.
    """
    from ai_engine.output_types.markers import parse_output_markers

    clean, marker_type, embed_description = parse_output_markers(raw)
    spec = OutputTypeRegistry.get(marker_type)
    # parse_output_markers reports "text" when it found no markers at all.
    if spec is None or spec.name == "text":
        recovered = recover_unmarked(resolved_type, clean, allow_choice)
        if recovered:
            spec = OutputTypeRegistry.get(recovered)
            clean = _unfence(strip_stray_markers(clean))
    final_type = spec.name if spec else "text"
    render_as = getattr(spec, "render_as", None) or "text"
    if final_type in _JSON_TYPES:
        clean = _unfence(clean)  # a fenced object inside the markers renders as the object
    if final_type != "text" and not _holds(final_type, render_as, clean):
        final_type, render_as = "text", "text"
    if final_type == "choice" and not allow_choice:
        # unattended run that asked anyway: no card to wait on — the question
        # reads as words, so whoever opens the topic sees what was unclear
        clean, final_type, render_as = _choice_as_text(clean), "text", "text"
    return clean, final_type, render_as, (None if render_as == "text" else embed_description)


def _choice_as_text(content: str) -> str:
    value = _whole_object(content) or {}
    question = str(value.get("question") or "").strip() or "a choice"
    labels = [str(o.get("label") or o.get("id") or "").strip()
              for o in value.get("options") or [] if isinstance(o, dict)]
    options = "; ".join(label for label in labels if label)
    return (f"This run had nobody to ask, so it stopped at a question: {question}"
            + (f" (options: {options})" if options else "")
            + ". Add that detail to the schedule's message so the next run has it.")
