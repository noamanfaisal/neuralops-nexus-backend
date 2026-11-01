"""
Tool relevance — which catalog tools fit THIS message (owner, 2026-11-01).

Pure and cheap, no model call and no embedder: words of the message against
the words of each tool's model-facing name and one-line description, the same
kind of keyword matching ToolSearch's "keywords" strategy does when the model
searches. Two uses, both inside the narrow-once-and-hold decision
(NEXUS-AI-REVAMP §4 item 1 — the loaded set stays fixed per topic, because the
tool definitions sit at the front of the provider's cached prefix):

1. The FIRST reply of a topic with no router seat: the loaded set is the best
   matches (reads before writes) instead of the first N in catalog order.
   Found live 2026-11-01: a GitHub persona got add_comment…, create_branch,
   delete_file… loaded — and list_commits hidden — for "show the last 5
   commits".
2. Every LATER reply: when the best matches are hidden, a short prompt line
   names them so the model loads them with search_tools instead of answering
   "I have no tool for that" (the same live finding, turn two). The tool list
   itself never changes, so the cache is untouched.
"""
from __future__ import annotations

import re
from typing import Iterable, Sequence

from ai_engine.core.specs import ToolCatalogEntry

_WORD = re.compile(r"[a-z0-9]+")

# Words that carry no signal about WHICH tool fits.
_STOP = frozenset("""
a an the and or but if then else of to in on at by for from with without into onto
is are was were be been being am do does did done doing have has had having can could
will would shall should may might must i me my mine you your yours we our us they them
their it its this that these those there here what which who whom whose when where why
how all any some each every no not only just also too very more most less few many much
please show tell give get got make let lets list find look see want need know like about
last first next new old latest recent one two three four five ten few some
""".split())


def _stem(word: str) -> str:
    """A light stemmer that maps singular and plural to one form:
    commits/commit→commit, issues/issue→issue, repositories/repository→
    repositori, branches/branch→branch, listing→list. Enough for tool names;
    never empties a word."""
    if len(word) <= 3:
        return word
    if word.endswith("ies"):
        return word[:-3] + "i"
    if word.endswith("y") and len(word) > 4:
        return word[:-1] + "i"
    if word.endswith("ing") and len(word) > 5:
        return word[:-3]
    if word.endswith(("ches", "shes", "xes", "zes", "sses")):
        return word[:-2]
    if word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def words(text: str) -> set[str]:
    """Stemmed, stop-word-free words of a text (underscores split words, so
    github__list_commits gives github / list / commit)."""
    return {_stem(w) for w in _WORD.findall((text or "").lower().replace("_", " "))
            if len(w) > 2 and w not in _STOP}


def _name_words(entry: ToolCatalogEntry) -> set[str]:
    # The server slug (github__…) names the SOURCE, not the action — it matches
    # every tool of that server equally, so it never ranks one above another;
    # it still counts below as a tie-breaker for "use GitHub"-style messages.
    name = entry.model_name.split("__", 1)[-1]
    return words(name)


def score(entry: ToolCatalogEntry, message_words: set[str]) -> int:
    """Name hits count 3, description hits 1, a server-slug hit 1."""
    if not message_words:
        return 0
    name_hits = len(message_words & _name_words(entry))
    desc_hits = len(message_words & words(entry.one_line))
    slug = entry.model_name.split("__", 1)[0] if "__" in entry.model_name else ""
    slug_hit = 1 if slug and message_words & words(slug) else 0
    return 3 * name_hits + desc_hits + slug_hit


def ranked(catalog: Sequence[ToolCatalogEntry], message: str) -> list[tuple[int, ToolCatalogEntry]]:
    """(score, entry) for every catalog entry with a score above zero, best
    first; ties go to read-only tools, then catalog order."""
    message_words = words(message)
    scored = []
    for index, entry in enumerate(catalog):
        value = score(entry, message_words)
        if value > 0:
            scored.append((value, entry.read_only is not True, index, entry))
    scored.sort(key=lambda row: (-row[0], row[1], row[2]))
    return [(value, entry) for value, _, _, entry in scored]


def first_reply_set(catalog: Sequence[ToolCatalogEntry], message: str, cap: int) -> tuple[str, ...]:
    """The loaded set for a topic's first reply when no router chose one.

    Native capabilities first (a handful at most, and the persona's own
    configuration), then the MCP tools that best fit the message, then the
    rest in catalog order up to the cap. A message nothing matches keeps the
    plain catalog order — the Layer 1 behaviour, byte for byte."""
    best = [entry for _, entry in ranked(catalog, message) if entry.source_kind != "native"]
    if not best:
        return tuple(entry.tool_id for entry in catalog[:cap])
    ordered: list[str] = [e.tool_id for e in catalog if e.source_kind == "native"]
    for entry in list(best) + list(catalog):
        if entry.tool_id not in ordered:
            ordered.append(entry.tool_id)
    return tuple(ordered[:cap])


def hidden_matches(catalog: Sequence[ToolCatalogEntry], loaded_ids: Iterable[str],
                   message: str, limit: int = 4, min_score: int = 3) -> list[ToolCatalogEntry]:
    """The best-fitting tools for this message that are NOT loaded — at least
    one name word must match (min_score 3), so a stray description word never
    names a tool."""
    loaded = set(loaded_ids)
    out = []
    for value, entry in ranked(catalog, message):
        if value < min_score:
            break
        if entry.tool_id in loaded or entry.source_kind == "native":
            continue
        out.append(entry)
        if len(out) >= limit:
            break
    return out


def hint_text(entries: Sequence[ToolCatalogEntry]) -> str:
    names = ", ".join(entry.model_name for entry in entries)
    return ("Tools that fit this question but are not loaded yet: " + names + ". "
            "Load them with search_tools and use them — don't answer that you lack a "
            "tool for this, and don't suggest commands for the person to run instead.")
