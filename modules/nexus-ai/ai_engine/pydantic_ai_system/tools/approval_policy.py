"""
ApprovalPolicy — item 2's policy, pure and I/O-free (testable like HistoryPolicy).

Ported from 0.8.0's `level_for` (nexus-ai-legacy/apps/managers/approvals.py),
re-keyed on the item 3 catalog ids, plus the 2026-10-12 decisions (§1.3
item 2, 5–7):
  - read tools run automatically, never ask;
  - write tools ask EVERY time — no "always allow" escape;
  - an MCP tool with unknown read/write nature (no stored read_only, no
    readOnlyHint) asks, unless the topic's clearance list says it is a read
    (the one "always allow" left; stored by nucleus next to topic_tools).
Explicit persona `tool_levels` win over all defaults, as at 0.8.0 — an admin's
deliberate per-tool setting, not the approval card's button.

Level keys honoured (the same keying 0.8.0's levels already support):
  "<capability>/<tool>"  one native tool     e.g. "filesystem/write_file"
  "<capability>"         a whole native      e.g. "filesystem"
  "mcp:<sid>/<tool>"     one MCP tool        (= the catalog tool_id)
  "mcp:<sid>"            a whole MCP server
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Mapping

from ai_engine.core.specs import ToolCatalogEntry

LEVELS = ("auto", "ask", "off")

# Native tools that change something outside the conversation. Everything else
# a native capability offers only reads. Names are the pinned harness 0.55
# toolsets (verified 2026-10-12): FileSystem and Shell.
ACTING_NATIVE_TOOLS: dict[str, set[str]] = {
    "shell": {"run_command", "start_command", "stop_command"},
    "filesystem": {"write_file", "edit_file", "create_directory"},
    # setup-copilot (setup_tools.py): the gateway admin tools mounted inside.
    # Every write asks — a model/persona/topic change is an act on the server;
    # the list_* tools and the transcript read run silently.
    "setup": {"create_model", "update_model", "create_persona",
              "update_persona", "create_topic", "update_topic"},
}

PREVIEW_CHARS = 300

# The texts the model sees when a call did NOT run — each states that plainly,
# because told only "declined" a model has answered with invented output
# (0.8.0's wording, kept).
REFUSED_UNATTENDED = (
    "{tool} needs a person's approval, and nobody can give one in this run "
    "(a schedule or an unattended job). Say what you would have done instead."
)
DENIED = (
    "The person declined this call. It did not run and nothing changed. Say so "
    "plainly and do not show any output for it; explain, or find another way."
)
# 9b part 2 (owner, 2026-11-03): a server with a repository allow-list refuses
# calls — reads included, an outside read leaks data — that name any other
# repo. Worded like the other refusals: the model must know it did NOT run.
REPO_OUTSIDE = (
    "This server may only act on these repositories: {allowed}. The call named "
    "{named}, which is not on that list, so it did not run and nothing "
    "changed. Say so plainly; use a server that is allowed to reach {named}, "
    "or ask an admin to widen this server's repository list."
)


def named_repo(args: object) -> str | None:
    """The owner/repo a GitHub-shaped tool call names, or None when it names
    none (search tools and the like — those always run). Reads the common
    spellings: owner+repo as separate params (the GitHub MCP server's shape),
    or a single repo/repository/repo_full_name holding "owner/name"."""
    if isinstance(args, str):
        try:
            args = json.loads(args or "{}")
        except ValueError:
            return None
    if not isinstance(args, Mapping):
        return None
    owner, repo = args.get("owner"), args.get("repo")
    if (isinstance(owner, str) and owner and isinstance(repo, str) and repo
            and "/" not in repo):
        return f"{owner}/{repo}"
    for value in (repo, args.get("repository"), args.get("repo_full_name")):
        if isinstance(value, str) and value.count("/") == 1:
            return value
    return None


def args_preview(args: object) -> str:
    """One short line of what the call would do — for the approval card,
    never the raw object. pydantic-ai hands tool args as a JSON string."""
    if isinstance(args, str):
        text = args
    else:
        try:
            text = json.dumps(args, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            text = str(args)
    return text if len(text) <= PREVIEW_CHARS else text[: PREVIEW_CHARS - 1] + "…"


@dataclass(frozen=True)
class ToolSource:
    """What ToolsetBuilder knows about one capability it built — the gate maps
    a run-time ToolDefinition back to the catalog through this."""

    kind: str        # "native" | "mcp"
    cap_key: str     # "filesystem" | "shell" | ... | "mcp:<server_id>"
    source_id: str   # native key, or the MCP server id
    slug: str = ""   # MCP only: the model-name prefix ("github")
    # 9b part 2: the row's "repositories this server may use" — lowercase
    # owner/repo entries; empty = no fence. The gate refuses any call (reads
    # included) whose args name a repo outside it.
    allowed_repos: tuple[str, ...] = ()


class ApprovalPolicy:
    def __init__(self, tool_levels: Mapping[str, str] | None = None,
                 clearances: frozenset[str] | set[str] = frozenset()) -> None:
        self._levels = dict(tool_levels or {})
        # topic clearances: catalog tool_ids the topic marked "treat as read"
        # (decision 6 — only meaningful for MCP tools with read_only=None)
        self._clearances = frozenset(clearances)

    # ── catalog time (ToolRegistry) ────────────────────────────────────────
    def catalog_level(self, entry: ToolCatalogEntry) -> str:
        """Only an EXPLICIT level can be 'off' — defaults never hide a tool.
        Used by ToolRegistry to drop off tools from the catalog entirely
        (never searchable, never loadable)."""
        for key in self._level_keys(entry.tool_id, entry.source_kind, entry.source_id):
            level = self._levels.get(key)
            if level in LEVELS:
                return level
        return "auto" if entry.source_kind == "native" else "default"

    # ── run time (ApprovalGate) ────────────────────────────────────────────
    def runtime_level(self, *, tool_name: str, source: ToolSource | None,
                      entry: ToolCatalogEntry | None, metadata: Mapping | None) -> str:
        """auto | ask | off for one tool the model may call right now."""
        if source is None:
            # not a tool we built (future: ToolSearch's own tool, output tools)
            return "auto"
        if source.kind == "native":
            for key in (f"{source.cap_key}/{tool_name}", source.cap_key):
                level = self._levels.get(key)
                if level in LEVELS:
                    return level
            acting = tool_name in ACTING_NATIVE_TOOLS.get(source.cap_key, ())
            return "ask" if acting else "auto"
        # MCP: strip the model-name prefix back to the server's own tool name
        base = tool_name.removeprefix(f"{source.slug}__") if source.slug else tool_name
        tool_id = f"mcp:{source.source_id}/{base}"
        for key in (tool_id, source.cap_key):
            level = self._levels.get(key)
            if level in LEVELS:
                return level
        read_only = entry.read_only if entry is not None else None
        if read_only is True:
            return "auto"
        if read_only is None:
            annotations = (metadata or {}).get("annotations") or {}
            if not isinstance(annotations, Mapping):
                annotations = getattr(annotations, "model_dump", lambda: {})()
            # both spellings: mcp 1.x readOnlyHint, 2.x read_only_hint
            # (found live 2026-10-31)
            if (annotations.get("readOnlyHint") is True
                    or annotations.get("read_only_hint") is True):
                return "auto"
            if tool_id in self._clearances:
                return "auto"  # the topic cleared this unlabeled tool as a read
        return "ask"  # a known write, or unknown and uncleared

    @staticmethod
    def _level_keys(tool_id: str, source_kind: str, source_id: str) -> tuple[str, ...]:
        if source_kind == "mcp":
            return (tool_id, f"mcp:{source_id}")
        return (tool_id,)
