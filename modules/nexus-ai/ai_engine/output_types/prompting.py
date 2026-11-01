"""
The output instruction as the model sees it (0.8.0's with_output_instruction,
ported from NA/managers/prompt_builder.py:55-80): the resolved type's
system_instruction plus the one standing exception — a choice prompt when the
persona must ask — for every type but a plan or a choice itself.

In the rebuild this becomes its own PromptSection (kind="output_format",
priority 85, unstable — the type can change per message), appended to the
plan the same way the retrieval section is; the generator joins sections with
blank lines, reproducing 0.8.0's composed prompt.
"""
from __future__ import annotations

from ai_engine.output_types.registry import TYPES_WITHOUT_CHOICE

CHOICE_EXCEPTION = (
    "One exception to the format above: when you genuinely cannot continue without the person choosing "
    "between a few concrete options (not a rhetorical question, not something you could decide or look up "
    "yourself), answer with ONLY a choice prompt, in exactly this form and nothing else:\n"
    "<<<OUTPUT:choice>>>\n"
    '{ "question": "one clear question", "options": [ { "id": "short-id", "label": "the option", "hint": "one line of consequence, optional" } ], "multiple": false }\n'
    "<<<END_OUTPUT>>>\n"
    "Two to six options; multiple is true only when more than one may be picked together. "
    "The person's pick comes back as their next message, and you carry on from there."
)


# A run nobody is watching (a schedule, a chain step, a review). Found live
# 2026-10-31: a scheduled "fetch today's gold and dollar rates" answered with
# a choice card ("which market?") and sat waiting for a person — the run is
# unattended, so a question can only stall it. The choice exception is
# withheld and this rule rides instead.
UNATTENDED_RULE = (
    "Nobody is watching this reply: it was started by a schedule or an automation, and no one can answer "
    "a question or approve a step until it is over. Never ask the person anything and never offer them a "
    "choice. Where a detail is missing, take the most reasonable reading (the project, this conversation "
    "and earlier work usually show it), say in one line which reading you took, and finish the work."
)


# A format the CLASSIFIER guessed from the wording — nobody asked for it.
# Found live 2026-11-01: "use the code graph to index /code/nexus-ai" scored
# chart 0.646 vs text 0.550 (the word "graph"), a wider margin than a real
# "plot 3,1,4,1,5" — so no threshold separates them, and the hard "exactly
# this structure, nothing else" contract turned an indexing report into a
# bar chart of outcome counts. A guessed format is therefore an offer: the
# model keeps it when the answer really is that shape, and answers in plain
# text otherwise (no markers → finalise_reply lands it as text).
GUESSED_FORMAT_ESCAPE = (
    "This format was inferred from the wording of the request — the person did not ask for it. Use it "
    "only if the answer naturally is that shape. If the answer is a status, a report of what you did, "
    "an explanation or anything else, ignore the format above and answer in plain text with no "
    "<<<OUTPUT:...>>> markers at all."
)


def format_was_guessed(explicit: str | None, persona_default: str | None) -> bool:
    """True when the resolver will fall through to the classifier: no
    directive from the person and no default format on the persona."""
    def unset(value: str | None) -> bool:
        return (value or "").strip().lower() in ("", "auto")
    return unset(explicit) and unset(persona_default)


def output_instruction_block(system_instruction: str | None,
                             allow_choice: bool = True,
                             guessed: bool = False) -> str | None:
    """The section text for the resolved type, 0.8.0's shape kept. An
    unattended run (allow_choice=False) never gets the choice exception; a
    guessed format (guessed=True) gets the plain-text way out."""
    if not system_instruction:
        return None
    block = system_instruction
    if guessed:
        block = f"{block}\n\n{GUESSED_FORMAT_ESCAPE}"
    if allow_choice and not any(f"<<<OUTPUT:{name}>>>" in system_instruction for name in TYPES_WITHOUT_CHOICE):
        block = f"{block}\n\n{CHOICE_EXCEPTION}"
    return f"--- OUTPUT FORMAT INSTRUCTION ---\n{block}"
