"""
Budget and BudgetFitter — item 16 (§4.1), the SELECTION half.

    input_budget = context_window − max_output_tokens − loop_headroom

Two numbers, structurally apart (§4.1): target (~70% of budget — what the
prompt is trimmed to before the run, and what compaction compacts down to)
and trigger (~90% — where mid-run compaction fires). The gap is what lets the
tool loop grow between compactions.

Selection and compaction are different mechanisms: this class is selection —
"do not put it in if it will not fit" — applied BEFORE the run. Mid-run growth
(tool results) is compaction's job (the TieredCompaction capability, wired in
ToolsetBuilder with target_tokens=budget.target).

Framework-free (dependency rule 1): the token estimator is injected — the
factory passes pydantic_ai_system's wrapper around the harness estimator.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from typing import Callable

from ai_engine.core.specs import ModelSpec, PromptPlan

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Budget:
    input_budget: int
    target: int    # trim/compact down to this
    trigger: int   # compaction fires above this


def budget_for(spec: ModelSpec, loop_headroom: int, target_pct: int, trigger_pct: int,
               max_output_tokens: int) -> Budget:
    """The run's budget from the MODEL's window and the PERSONA's output cap —
    two separate numbers, never one field (§4.1: reading max_output_tokens as
    the window is the live 0.8.0 defect this exists to bury)."""
    input_budget = spec.context_window - max_output_tokens - loop_headroom
    floor = max(1, spec.context_window // 2)
    if input_budget < floor:
        # A misconfigured card — a reply cap at or over the model's whole
        # window — must not starve the prompt: at target 1 EVERYTHING (history,
        # retrieval, tool catalog) gets dropped and the persona forgets the
        # conversation every run (found live 2026-10-30: a Groq card saved
        # with window 8192 and reply cap 16000 — the setup copilot re-asked
        # its questions forever). The reply cap yields: the prompt keeps at
        # least half the window.
        log.warning(
            "budget: reply cap %d + headroom %d leave %d of a %d-token window — "
            "flooring the input budget at %d (fix the model card's numbers)",
            max_output_tokens, loop_headroom, input_budget, spec.context_window, floor,
        )
        input_budget = floor
    return Budget(
        input_budget=input_budget,
        target=max(1, input_budget * target_pct // 100),
        trigger=max(1, input_budget * trigger_pct // 100),
    )


class BudgetFitter:
    """Trim a prompt plan to the model's budget (§1.5 catalog, L2).

    Order (§4.1's protection list): OLD HISTORY is dropped first, oldest
    message first; then sections below the persona prompt's priority (today:
    the tool catalog). NEVER dropped: the current user message, the persona
    prompt / project brief, attached files (none yet — Layer 3)."""

    def __init__(self, estimate: Callable[[str], int]) -> None:
        self._estimate = estimate

    def fit(self, plan: PromptPlan, budget: Budget) -> PromptPlan:
        return self.fit_report(plan, budget)[0]

    def fit_report(self, plan: PromptPlan, budget: Budget) -> tuple[PromptPlan, dict]:
        """fit() plus THE TRIMMING STORY for the AI log (owner's ruling
        2026-10-31: the log must show "how its compact"): every ingredient
        with its token estimate and whether it was kept, the reason for each
        drop, and the totals before/after against the target. Until now the
        drops went only to the server log — which is how the 8192-window
        starvation (2026-10-30) stayed invisible."""
        est = self._estimate
        section_costs = [est(s.text) for s in plan.instructions]
        message_cost = est(plan.message)
        history_costs = [est(m.text) for m in plan.history]
        before = sum(section_costs) + message_cost + sum(history_costs)
        total = before
        dropped_history = 0
        dropped_sections: set[int] = set()   # indexes into plan.instructions
        protected_over = False

        if total > budget.target:
            # 1) drop old history, oldest first
            while dropped_history < len(plan.history) and total > budget.target:
                total -= history_costs[dropped_history]
                log.info("budget: dropped history message (%d chars) — over target",
                         len(plan.history[dropped_history].text))
                dropped_history += 1
            # 2) drop droppable sections (below the persona prompt's priority)
            if total > budget.target:
                order = sorted((i for i, s in enumerate(plan.instructions) if s.priority < 90),
                               key=lambda i: plan.instructions[i].priority)
                for i in order:
                    dropped_sections.add(i)
                    total -= section_costs[i]
                    log.info("budget: dropped section %r — over target", plan.instructions[i].kind)
                    if total <= budget.target:
                        break
            if total > budget.target:
                # protected content alone exceeds the target: §4.1's escape valve
                # (indexing, items 33/34) is the real answer — never truncate it here.
                protected_over = True
                log.warning("budget: protected content (%d tokens) exceeds target %d — sent anyway",
                            total, budget.target)

        # a plan that fits passes through as the SAME object (the cache
        # prefix is not disturbed for nothing — test_budget pins it)
        fitted = plan if not (dropped_history or dropped_sections) else replace(
            plan,
            history=plan.history[dropped_history:],
            instructions=tuple(s for i, s in enumerate(plan.instructions) if i not in dropped_sections),
        )
        items = [
            {"what": f"section: {s.kind}", "priority": s.priority, "tokens": section_costs[i],
             "kept": i not in dropped_sections,
             **({"reason": "over target — lowest-priority sections go after all old history"}
                if i in dropped_sections else {})}
            for i, s in enumerate(plan.instructions)
        ] + [
            {"what": f"history #{n + 1} ({m.role}{', ' + m.author if m.author else ''})",
             "tokens": history_costs[n], "kept": n >= dropped_history,
             **({"reason": "over target — oldest history goes first"} if n < dropped_history else {})}
            for n, m in enumerate(plan.history)
        ] + [{"what": "the current message", "tokens": message_cost, "kept": True,
              "reason": "never dropped"}]
        report = {
            "input_budget": budget.input_budget,
            "target": budget.target,
            "trigger": budget.trigger,
            "tokens_before": before,
            "tokens_after": total,
            "trimmed": before > budget.target,
            "protected_over_target": protected_over,
            "items": items,
        }
        return fitted, report
