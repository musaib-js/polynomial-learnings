"""Hybrid relevance retrieval (see §7 of the design doc).

Runs semantic (vector) and keyword (full-text) search over the same isolation
pre-filter, then fuses the two ranked lists with Reciprocal Rank Fusion (RRF).
Ties are broken by recency and hit count.

An optional reranking + thresholding stage (see ``reranker.py``) runs after
fusion and before results are returned: each fused candidate is scored
against the query by a pluggable ``Reranker``, and anything that doesn't
clear ``rerank_threshold`` is dropped — including, if even the best-scoring
candidate misses the bar, everything (an empty list). Disabled by default
(``reranker=None``); existing behavior is unchanged unless one is configured.

Returned learnings are "touched" (hits++, last_used_at) so frequency/recency
signals stay current — only for whatever is actually returned, so reranked-
out candidates are never touched.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from .backend import SearchFilter, VectorStoreBackend
from .embedder import Embedder
from .models import Learning
from .reranker import Reranker

logger = logging.getLogger(__name__)


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
        reranker: Reranker | None = None,
        rerank_threshold: float = 0.52,
    ):
        self._backend = backend
        self._embedder = embedder
        self._semantic_weight = semantic_weight
        self._keyword_weight = keyword_weight
        self._rrf_k = rrf_k
        # Opt-in: reranker=None (the default) preserves the exact prior
        # behavior — RRF-fused order, truncated to `limit`, nothing dropped.
        # rerank_threshold is only consulted when a reranker is configured.
        # 0.52 is calibrated to CrossEncoderReranker's current default model
        # (mxbai-rerank-base-v1) on its sigmoid [0, 1] scale: measured
        # irrelevant queries consistently land at ~0.50-0.503, while relevant
        # queries (including paraphrases, and realistic-but-terse natural
        # language like "how do I get revenue by region?") land at ~0.545 and
        # above. 0.55 was tried first and was too tight — it clipped a
        # genuinely relevant, realistically-phrased query at 0.5467 — so 0.52
        # trades a little precision for not rejecting real content near the
        # boundary. See CrossEncoderReranker's docstring for the full measured
        # comparison. Pass your own value if you plug in a reranker with a
        # different scale.
        self._reranker = reranker
        self._rerank_threshold = rerank_threshold

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

        # Both searches return (learning, score) pairs; RRF re-ranks from
        # position alone, so the scores are dropped here.
        fused = reciprocal_rank_fusion(
            [
                [learning for learning, _ in semantic],
                [learning for learning, _ in keyword],
            ],
            weights=[self._semantic_weight, self._keyword_weight],
            k=self._rrf_k,
        )
        candidates = [learning for learning, _ in fused]

        if self._reranker is not None:
            results = self._rerank(query, candidates, limit)
        else:
            results = candidates[:limit]

        self._touch(results)
        return results

    def _rerank(
        self, query: str, candidates: list[Learning], limit: int
    ) -> list[Learning]:
        """Score every RRF-fused candidate against ``query``, gate on the
        best score, then keep only individual survivors of the threshold.

        Two-stage on purpose: if the single best-scoring candidate doesn't
        clear ``rerank_threshold``, nothing is relevant enough and the whole
        call returns ``[]`` (requirement: best score gates everything). If it
        does, only candidates that *individually* clear the threshold are
        kept — a strong top match doesn't drag mediocre ones along with it —
        capped at ``limit``.
        """
        if not candidates:
            return []
        scores = self._reranker.score(query, candidates)

        raw_scores = getattr(self._reranker, "_last_raw", None)
        if raw_scores is None:
            raw_scores = scores

        best_score = max(scores)
        gates_passed = best_score >= self._rerank_threshold

        for candidate, score, raw_score in zip(candidates, scores, raw_scores):
            sigmoid_enabled = getattr(self._reranker, "_apply_sigmoid", False)
            sigmoid_score = score if sigmoid_enabled else None
            accepted = gates_passed and (score >= self._rerank_threshold)
            decision = "Accepted" if accepted else "Rejected"

            logger.info(
                f"Reranker Candidate Evaluation:\n"
                f"  Query: {query!r}\n"
                f"  Rerank Text: {candidate.rerank_text()!r}\n"
                f"  Raw Score (logit): {raw_score:.6f}\n"
                f"  Sigmoid Score: {f'{sigmoid_score:.6f}' if sigmoid_score is not None else 'N/A'}\n"
                f"  Threshold: {self._rerank_threshold:.6f}\n"
                f"  Decision: {decision}"
            )

        scored = sorted(zip(candidates, scores), key=lambda pair: pair[1], reverse=True)
        if scored[0][1] < self._rerank_threshold:
            return []
        survivors = [
            learning for learning, score in scored if score >= self._rerank_threshold
        ]
        return survivors[:limit]

    def _touch(self, learnings: list[Learning]) -> None:
        now = datetime.now(timezone.utc)
        for learning in learnings:
            learning.hits += 1
            learning.last_used_at = now
            self._backend.update(learning.id, hits=learning.hits, last_used_at=now)
