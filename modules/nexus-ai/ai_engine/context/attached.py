"""
Files attached to the topic — always shown to the persona (owner, 2026-11-02:
"build 1.1.3").

Retrieval ranks memory by how much it RESEMBLES the message, so a request
about a file rather than its contents ("summarise the document I attached")
matched nothing in it, and the persona never saw the file it was asked about
(found live 2026-11-02, Contabo: the PDF was attached and indexed — 9 chunks —
yet only chat messages came back). Attached files are now a section of their
own, read in document order:

  - short files are shown WHOLE, so summarising, listing and comparing work;
  - when the files together exceed the budget, each is shown up to what is
    left, with a note saying how much of it is shown — similarity retrieval
    still searches the rest;
  - the persona is always told WHICH files are attached, by name.

Framework-free and pure: the store hands in chunks, this returns what to show.
"""
from __future__ import annotations

from dataclasses import dataclass

from ai_engine.core.specs import SearchHit
from ai_engine.vector_db.chunking import rejoin_chunks


@dataclass(frozen=True)
class AttachedDoc:
    label: str               # the file's name as attached
    text: str                # what is shown (whole, or the start)
    total_chars: int
    chunk_ids: tuple[str, ...]

    @property
    def whole(self) -> bool:
        return len(self.text) >= self.total_chars


def fit_attached(chunks: list[SearchHit], budget_chars: int) -> list[AttachedDoc]:
    """Group a topic's chunks into documents (ids are "<source>:<n>", already
    in document order), rebuild each document's text, and fit them into the
    budget in attach order. A document that no longer fits is cut, never
    dropped: its name is always listed."""
    groups: dict[str, list[SearchHit]] = {}
    for chunk in chunks:
        groups.setdefault(chunk.id.rpartition(":")[0] or chunk.id, []).append(chunk)
    left = max(budget_chars, 0)
    docs: list[AttachedDoc] = []
    for parts in groups.values():
        full = rejoin_chunks([p.text for p in parts])
        shown = full[:left]
        left -= len(shown)
        docs.append(AttachedDoc(label=parts[0].label or "attached file", text=shown,
                                total_chars=len(full),
                                chunk_ids=tuple(p.id for p in parts)))
    return docs


def attached_section(docs: list[AttachedDoc]) -> str:
    lines = [
        "Files attached to this topic. Their text is below, read by the server "
        "from the files themselves: answer questions about these files from it, "
        "and do not try to open them with other tools.",
    ]
    for doc in docs:
        if doc.whole:
            lines.append(f"=== {doc.label} (whole file) ===")
        elif doc.text:
            lines.append(f"=== {doc.label} (the first {len(doc.text):,} of "
                         f"{doc.total_chars:,} characters; ask about a specific "
                         f"part and it is searched) ===")
        else:
            lines.append(f"=== {doc.label} ({doc.total_chars:,} characters, not "
                         f"shown here for length; ask about a specific part and "
                         f"it is searched) ===")
        if doc.text:
            lines.append(doc.text)
        lines.append(f"=== end of {doc.label} ===")
    return "\n".join(lines)


def shown_whole_ids(docs: list[AttachedDoc]) -> set[str]:
    """Chunk ids already on screen in full — retrieval must not repeat them."""
    return {cid for doc in docs if doc.whole for cid in doc.chunk_ids}
