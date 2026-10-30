"""
PromptLayout — the prompt as ordered sections: stable first (cache-friendly),
system prompt once. Layer 0 rule (§1.5): instructions = project brief (if any)
then persona prompt, both stable; history; then the new message as the last
user turn.

Joined with "\n\n", the sections reproduce 0.8.0's composed system prompt
byte for byte (legacy prompt_builder.compose_system_prompt).
"""
from __future__ import annotations

from typing import Sequence

from ai_engine.core.specs import (
    ContextBundle,
    PersonaSpec,
    PromptPlan,
    PromptSection,
    ToolCatalogEntry,
)
from ai_engine.prompts.templates import PromptTemplates


class PromptLayout:
    def __init__(self, templates: PromptTemplates) -> None:
        self._templates = templates

    def build(self, persona: PersonaSpec, bundle: ContextBundle, message: str,
              catalog: Sequence[ToolCatalogEntry] = ()) -> PromptPlan:
        sections: list[PromptSection] = []
        brief = (persona.project_brief or "").strip()
        if brief:
            sections.append(PromptSection(
                kind="project_brief", priority=100, stable=True,
                text=self._templates.render("project_brief.j2", {"brief": brief}),
            ))
        sections.append(PromptSection(
            kind="persona_prompt", priority=90, stable=True,
            text=persona.system_prompt,
        ))
        if catalog:
            # Item 1: the catalog — one line per ELIGIBLE tool, stable per
            # topic so the cache prefix survives. Full schemas travel only for
            # the loaded set, via the tools parameter, never in this text.
            lines = "\n".join(f"- {e.model_name}: {e.one_line}" for e in catalog)
            # Honesty rule (live finding 2026-10-22: a persona invented date/ls
            # transcripts): tool RESULTS are the only ground truth — appended
            # after the lines so the section still starts with the same stable
            # prefix byte-for-byte. Extended 2026-10-28 (B7, live finding
            # 2026-10-27: after real auth failures, a reply twice claimed
            # "Attempted now: … → missing or invalid bearer token" with NO
            # call behind it): invented ATTEMPTS are banned like invented
            # results.
            sections.append(PromptSection(
                kind="tool_catalog", priority=80, stable=True,
                text="Tools available in this conversation:\n" + lines + (
                    "\nTool results are the only ground truth: never invent, "
                    "embellish or simulate a tool's output. If a call is "
                    "refused, denied or unavailable, say so plainly instead of "
                    "imagining what it would have returned. The same honesty "
                    "covers attempts: never say a tool was called, attempted "
                    "or failed in this reply unless that call really happened "
                    "in this reply. An earlier reply's calls may be described "
                    "as remembered (\"earlier we ran …\"), never as fresh."
                ),
            ))
        # getattr, not a plain read: build() is also called with lighter
        # persona-shaped objects (ot9's unit test, older callers) that predate
        # the field — absent means none, never an error.
        if getattr(persona, "other_servers", ()):
            # MCP suggest-attach (owner's "option 2", ruled 2026-10-22): the
            # persona may SEE that other servers exist in the project — names
            # and one-liners only, never their tools — so "what shopping tools
            # do you have?" gets "this project has Shopping; ask someone with
            # edit rights to attach it" instead of a flat "none" (found live).
            # The attach stays a HUMAN CLICK gated by the persona-edit right;
            # nothing in this text can arm the persona, and a crafted message
            # cannot either — the list comes from nucleus, not the chat.
            # Priority 70: under budget pressure this drops before the catalog.
            lines = "\n".join(
                f"- {name}: {one_line}" if one_line else f"- {name}"
                for name, one_line in persona.other_servers  # type: ignore[union-attr]
            )
            sections.append(PromptSection(
                kind="other_servers", priority=70, stable=True,
                text="Tool servers that exist in this project but are NOT attached to you:\n"
                     + lines
                     + "\nYou cannot see or call their tools, and must never pretend to. "
                       "When one would clearly help with what was asked, say so and name it — "
                       "someone with persona-edit rights can attach it to you under Intelligence.",
            ))
        return PromptPlan(instructions=tuple(sections), history=bundle.history, message=message)
