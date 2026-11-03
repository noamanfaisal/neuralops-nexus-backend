"""
1.1.3 — files attached to the topic are always shown to the persona
(ai_engine/context/attached.py + vector_db/chunking.rejoin_chunks). Pure: no
store, no network. The end-to-end case is test_retrieval.py::tr4.
"""
from __future__ import annotations

from ai_engine.context.attached import attached_section, fit_attached, shown_whole_ids
from ai_engine.core.specs import SearchHit
from ai_engine.vector_db.chunking import chunk_text, rejoin_chunks


def _doc(paragraphs: int, word: str) -> str:
    return "\n\n".join(f"{word} paragraph {n} " + "x" * 300 for n in range(paragraphs))


def _hits(source: str, label: str, text: str) -> list[SearchHit]:
    return [SearchHit(id=f"{source}:{n}", kind="context_source", label=label, score=1.0,
                      text=chunk, topic_id="t1")
            for n, chunk in enumerate(chunk_text(text))]


def test_at1_chunks_rejoin_to_the_document_without_the_overlaps():
    """chunk_text packs paragraphs with a one-paragraph overlap; the reader
    must get the document back exactly once, in order."""
    text = _doc(12, "alpha")
    chunks = chunk_text(text)
    assert len(chunks) > 2  # the overlap path really runs
    assert rejoin_chunks(chunks) == text


def test_at2_a_short_file_is_shown_whole():
    """The live case: an 8,000-character PDF — summarising needs ALL of it."""
    text = _doc(6, "revenue")
    [doc] = fit_attached(_hits("pdf1", "Dashboard answers.pdf", text), budget_chars=24000)
    assert doc.whole and doc.text == text and doc.label == "Dashboard answers.pdf"
    section = attached_section([doc])
    assert "Dashboard answers.pdf (whole file)" in section
    assert "revenue paragraph 5" in section
    assert "do not try to open them with other tools" in section
    assert shown_whole_ids([doc]) == set(doc.chunk_ids)


def test_at3_over_budget_files_are_cut_never_dropped():
    """Two files over the budget: the first is shown whole, the second is cut
    with a note saying how much is shown; a third that gets nothing is still
    NAMED. Cut files keep their chunks searchable (not in shown_whole_ids)."""
    first, second, third = _doc(4, "one"), _doc(10, "two"), _doc(3, "three")
    chunks = (_hits("a", "a.pdf", first) + _hits("b", "b.docx", second)
              + _hits("c", "c.txt", third))
    budget = len(first) + 1000
    a, b, c = fit_attached(chunks, budget_chars=budget)
    assert a.whole and not b.whole and len(b.text) == 1000 and c.text == ""
    section = attached_section([a, b, c])
    assert "b.docx (the first 1,000 of" in section
    assert "c.txt (" in section and "not shown here for length" in section
    assert shown_whole_ids([a, b, c]) == set(a.chunk_ids)


def test_at4_no_attached_files_means_no_section():
    assert fit_attached([], budget_chars=24000) == []
