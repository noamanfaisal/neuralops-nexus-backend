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


def output_instruction_block(system_instruction: str | None,
                             allow_choice: bool = True) -> str | None:
    """The section text for the resolved type, 0.8.0's shape kept. An
    unattended run (allow_choice=False) never gets the choice exception."""
    if not system_instruction:
        return None
    block = system_instruction
    if allow_choice and not any(f"<<<OUTPUT:{name}>>>" in system_instruction for name in TYPES_WITHOUT_CHOICE):
        block = f"{system_instruction}\n\n{CHOICE_EXCEPTION}"
    return f"--- OUTPUT FORMAT INSTRUCTION ---\n{block}"
