"""Hybrid relevance retrieval (see §7 of the design doc).

Runs semantic (vector) and keyword (full-text) search over the same isolation
pre-filter, then fuses the two ranked lists with Reciprocal Rank Fusion (RRF).
Ties are broken by recency and hit count. Returned learnings are "touched"
(hits++, last_used_at) so frequency/recency signals stay current.
"""

from __future__ import annotations

from datetime import datetime, timezone

from .backend import SearchFilter, VectorStoreBackend
from .embedder import Embedder
from .models import Learning


def reciprocal_rank_fusion(
    ranked_lists: list[list[Learning]],
    weights: list[float] | None = None,
    k: int = 60,
) -> list[tuple[Learning, float]]:
    """Fuse several ranked lists into one, best first.

    RRF scores each item by ``weight * 1 / (k + rank)`` summed across the lists
    it appears in (rank is 0-based). ``k`` damps the influence of top ranks;
    60 is the value from the original RRF paper.
    """
    if weights is None:
        weights = [1.0] * len(ranked_lists)

    scores: dict[str, float] = {}
    seen: dict[str, Learning] = {}
    for lst, weight in zip(ranked_lists, weights):
        for rank, learning in enumerate(lst):
            scores[learning.id] = scores.get(learning.id, 0.0) + weight / (k + rank)
            seen.setdefault(learning.id, learning)

    fused = [(seen[lid], score) for lid, score in scores.items()]

    def sort_key(item: tuple[Learning, float]):
        learning, score = item
        last_used = learning.last_used_at or datetime.min.replace(tzinfo=timezone.utc)
        return (score, last_used, learning.hits)

    fused.sort(key=sort_key, reverse=True)
    return fused


class HybridRetriever:
    def __init__(
        self,
        backend: VectorStoreBackend,
        embedder: Embedder,
        semantic_weight: float = 1.0,
        keyword_weight: float = 1.0,
        rrf_k: int = 60,
    ):
        self._backend = backend
        self._embedder = embedder
        self._semantic_weight = semantic_weight
        self._keyword_weight = keyword_weight
        self._rrf_k = rrf_k

    def retrieve(
        self,
        agent_id: str,
        query: str,
        entity_id: str | None = None,
        limit: int = 5,
        candidate_k: int | None = None,
    ) -> list[Learning]:
        """Return the most relevant active learnings for ``query``.

        ``candidate_k`` is how many to pull from each search before fusion
        (defaults to ``4 * limit`` so fusion has room to work).
        """
        candidate_k = candidate_k or max(limit * 4, limit)
        flt = SearchFilter(agent_id=agent_id, entity_id=entity_id, status="active")

        query_vector = self._embedder.embed([query])[0]
        semantic = self._backend.vector_search(query_vector, flt, candidate_k)
        keyword = self._backend.keyword_search(query, flt, candidate_k)

        fused = reciprocal_rank_fusion(
            [[l for l, _ in semantic], [l for l, _ in keyword]],
            weights=[self._semantic_weight, self._keyword_weight],
            k=self._rrf_k,
        )
        results = [learning for learning, _ in fused[:limit]]
        self._touch(results)
        return results

    def _touch(self, learnings: list[Learning]) -> None:
        now = datetime.now(timezone.utc)
        for learning in learnings:
            learning.hits += 1
            learning.last_used_at = now
            self._backend.update(
                learning.id, hits=learning.hits, last_used_at=now
            )
