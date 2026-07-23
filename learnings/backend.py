"""Storage-agnostic vector-store contract.

The core depends only on this shape, never on a specific database. A backend
implements four operations; isolation filtering is the backend's job and must
be applied *before* ranking.
"""

from __future__ import annotations

from typing import Protocol, Sequence, runtime_checkable

from .models import Learning, TokenUsageRecord


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

    def get(self, learning_id: str) -> Learning | None:
        """Fetch a single learning by id, or ``None`` if it does not exist."""
        ...

    def update(self, learning_id: str, **fields) -> None:
        """Patch stored fields on an existing learning (e.g. hits, status)."""
        ...

    def stats(self, agent_id: str, top_n: int = 5) -> dict:
        """Aggregate statistics for one agent's learnings.

        Returns raw counts/sums plus the ``top_n`` most-used learnings; the
        manager assembles these into an ``AgentStats`` model.
        """
        ...

    def list_agents(self) -> list[dict]:
        """Roster of every agent the store has seen, one compact row each.

        There is no agent registry table; the roster is derived from every
        ``agent_id`` present in the learnings/token tables. Each row carries
        enough signal (totals, last activity) to render a list entry; the
        manager wraps these into ``AgentSummary`` models.
        """
        ...

    # -- token accounting -------------------------------------------------
    def record_token_usage(self, record: TokenUsageRecord) -> None:
        """Persist one token-consumption event."""
        ...

    def token_usage_stats(self, agent_id: str) -> dict:
        """Aggregate token consumption for one agent.

        Returns raw totals plus per-operation and per-model breakdowns; the
        manager assembles these into a ``TokenUsageStats`` model.
        """
        ...

    # -- agent learnings flag --------------------------------------------
    def get_agent_has_learnings(self, agent_id: str) -> bool:
        """Whether this agent has any learnings (fast path for the store flow).

        Returns ``False`` when no flag row exists yet — a brand-new agent whose
        neighbour search can be skipped entirely.
        """
        ...

    def set_agent_has_learnings(self, agent_id: str, has_learnings: bool = True) -> None:
        """Mark that this agent now has learnings. Idempotent upsert."""
        ...
