"""
ReembedJob — embedder change ⇒ FULL re-embed (Layer 3 decisions 4 + 8).

Runs inside nexus-ai (vectors are nexus-ai's property): nucleus locks the
project, POSTs /embed/reindex/, and polls the status endpoint. The walk reads
the OLD schema's stored raw text — nothing is re-fetched — and the flip is
atomic in the registry: searches answer OLD vectors until the new set is
complete, so a crash mid-rebuild loses nothing.
"""
from __future__ import annotations

import logging

from ai_engine.vector_db.txtai_store import TxtaiVectorStore

log = logging.getLogger(__name__)


def _worded(exc: Exception) -> str:
    """A short, key-free reason the owner can act on. Raw provider text can
    carry a key fragment or a URL with one, so only the status code and the
    exception's class are trusted."""
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if status in (401, 403):
        return ("The embedding provider refused the API key — re-save the "
                "embedder with a valid key.")
    if status == 404:
        return "The embedding provider does not know this model id."
    if status == 429:
        return "The embedding provider rate-limited the rebuild — try again shortly."
    if status:
        return f"The embedding provider answered {status}."
    return f"The rebuild failed ({type(exc).__name__})."


class ReembedJob:
    def __init__(self, store: TxtaiVectorStore) -> None:
        self._store = store

    def start(self, company_id: str, project_id: str, embedder_spec: dict) -> dict:
        """Registers the BUILDING index or raises VectorStoreBusy (→ 409)."""
        return self._store.start_reindex(company_id, project_id, embedder_spec)

    def run(self, project_id: str) -> None:
        """The blocking walk — call from a background thread."""
        try:
            self._store.run_reindex(project_id)
        except Exception as exc:  # noqa: BLE001 — reported as 'failed', worded
            log.exception("reindex failed for project %s — old index stays active",
                          project_id)
            self._store.abandon_reindex(project_id, _worded(exc))

    def status(self, project_id: str) -> dict:
        return self._store.reindex_status(project_id)
