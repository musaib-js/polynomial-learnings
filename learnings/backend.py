"""Storage-agnostic vector-store contract.

The core depends only on this shape, never on a specific database. A backend
implements four operations; isolation filtering is the backend's job and must
be applied *before* ranking.
"""

from __future__ import annotations

from typing import Protocol, Sequence, runtime_checkable

from .models import Learning


class SearchFilter(dict):
    """A plain dict of filter fields, e.g.::

        {"agent_id": "...", "entity_id": "...", "status": "active"}

    Backends translate it into the isolation pre-filter:
    ``agent_id`` matches AND (``scope = 'global'`` OR ``entity_id`` matches)
    AND ``status = 'active'``.
    """


@runtime_checkable
class VectorStoreBackend(Protocol):
    def upsert(self, learning: Learning, embedding: Sequence[float]) -> None:
        """Insert or replace a learning together with its vector."""
        ...

    def vector_search(
        self, query_embedding: Sequence[float], flt: SearchFilter, top_k: int
    ) -> list[tuple[Learning, float]]:
        """Nearest learnings by cosine similarity, most similar first.

        Returns ``(learning, score)`` pairs where score is in [0, 1].
        """
        ...

    def keyword_search(
        self, query_text: str, flt: SearchFilter, top_k: int
    ) -> list[tuple[Learning, float]]:
        """Best learnings by full-text keyword match, best first."""
        ...

    def list(
        self, flt: SearchFilter, limit: int, offset: int
    ) -> list[Learning]:
        """List learnings matching ``flt``, most recently used first (no ranking)."""
        ...

    def update(self, learning_id: str, **fields) -> None:
        """Patch stored fields on an existing learning (e.g. hits, status)."""
        ...
