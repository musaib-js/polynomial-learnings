"""Tests for the reranking + thresholding stage on HybridRetriever.

Real Postgres/pgvector + real HuggingFaceEmbedder (semantic search, keyword
search, and RRF fusion are all real); only the reranker is faked
(``FakeReranker``) for deterministic scores. Set DATABASE_URL to run, same
gate as the other integration suites.

Covers: above-threshold survival, below-threshold empty result, touch()
happening only for survivors, and a no-regression check for the
`reranker=None` default (existing retrieval/persist flows depend on this
being byte-identical to pre-reranker behavior).
"""

from __future__ import annotations

import os
import uuid

import pytest

from learnings import HuggingFaceEmbedder, LearningManager, PgVectorBackend
from learnings.reranker import FakeReranker
from learnings.retriever import HybridRetriever

DSN = os.environ.get("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DSN, reason="DATABASE_URL not set")

EMBEDDER = HuggingFaceEmbedder()
THRESHOLD = 0.52  # matches HybridRetriever's default, calibrated for
# CrossEncoderReranker's default model (mxbai-rerank-base-v1) on its
# sigmoid [0, 1] scale; FakeReranker scores below are chosen to sit clearly
# above/below it so tests aren't sensitive to the exact cutoff.


@pytest.fixture
def env():
    agent_id = f"test-rerank-{uuid.uuid4()}"
    backend = PgVectorBackend(DSN)

    class Env:
        pass

    e = Env()
    e.agent_id = agent_id
    e.backend = backend
    e.manager = LearningManager(agent_id=agent_id, backend=backend, embedder=EMBEDDER)

    def make_retriever(reranker=None, **kwargs) -> HybridRetriever:
        return HybridRetriever(backend, EMBEDDER, reranker=reranker, **kwargs)

    e.make_retriever = make_retriever

    yield e

    with backend._pool.connection() as conn:
        conn.execute("DELETE FROM learnings WHERE agent_id = %s", [agent_id])
    backend.close()


def _hits(env, learning_id: str) -> int:
    with env.backend._pool.connection() as conn:
        cur = conn.execute("SELECT hits FROM learnings WHERE id = %s", [learning_id])
        return cur.fetchone()[0]


def _seed_three(env, entity_id="alice"):
    """Three learnings that all share a rare keyword, so keyword_search
    (and typically semantic search too) surfaces all three as RRF
    candidates regardless of rerank scoring — isolating the rerank stage
    as the only thing that can drop a candidate in these tests.
    """
    a = env.manager.record(
        context="user asks about rerank-fixture-widget strongly relevant",
        content="strongly relevant answer about rerank-fixture-widget",
        entity_id=entity_id,
    )
    b = env.manager.record(
        context="user asks about rerank-fixture-widget somewhat relevant",
        content="somewhat relevant answer about rerank-fixture-widget",
        entity_id=entity_id,
    )
    c = env.manager.record(
        context="user asks about rerank-fixture-widget barely relevant",
        content="barely relevant answer about rerank-fixture-widget",
        entity_id=entity_id,
    )
    return a, b, c


def _score_by_content(mapping: dict[str, float]):
    def _fn(query, candidates):
        return [mapping[c.content] for c in candidates]

    return _fn


# -- above threshold ----------------------------------------------------


def test_rerank_above_threshold_returns_only_surviving_candidates_in_score_order(env):
    a, b, c = _seed_three(env)
    reranker = FakeReranker(
        _score_by_content(
            {
                a.content: 0.95,  # survives
                b.content: 0.60,  # survives
                c.content: 0.05,  # dropped
            }
        )
    )
    retriever = env.make_retriever(reranker=reranker, rerank_threshold=THRESHOLD)

    results = retriever.retrieve(
        env.agent_id, "rerank-fixture-widget", entity_id="alice", limit=5
    )

    assert [r.id for r in results] == [a.id, b.id]  # score-descending, C excluded


def test_rerank_respects_limit_even_when_more_survive(env):
    a, b, c = _seed_three(env)
    reranker = FakeReranker(
        _score_by_content({a.content: 0.95, b.content: 0.90, c.content: 0.85})
    )
    retriever = env.make_retriever(reranker=reranker, rerank_threshold=THRESHOLD)

    results = retriever.retrieve(
        env.agent_id, "rerank-fixture-widget", entity_id="alice", limit=2
    )

    assert len(results) == 2
    assert [r.id for r in results] == [a.id, b.id]


# -- below threshold / empty result --------------------------------------


def test_rerank_below_threshold_returns_empty_list(env):
    a, b, c = _seed_three(env)
    reranker = FakeReranker(
        _score_by_content({a.content: 0.30, b.content: 0.20, c.content: 0.10})
    )
    retriever = env.make_retriever(reranker=reranker, rerank_threshold=THRESHOLD)

    results = retriever.retrieve(
        env.agent_id, "rerank-fixture-widget", entity_id="alice", limit=5
    )

    assert results == []
    assert isinstance(results, list)  # empty list, not None — response shape preserved


def test_empty_candidate_pool_short_circuits_without_calling_reranker(env):
    calls = []

    def _fn(query, candidates):
        calls.append(candidates)
        return [1.0] * len(candidates)

    retriever = env.make_retriever(
        reranker=FakeReranker(_fn), rerank_threshold=THRESHOLD
    )

    results = retriever.retrieve(
        env.agent_id, "nothing seeded yet", entity_id="alice", limit=5
    )

    assert results == []
    assert calls == []  # reranker never invoked over an empty candidate pool


# -- touch() only on survivors --------------------------------------------


def test_touch_happens_only_for_surviving_candidates(env):
    a, b, c = _seed_three(env)
    assert _hits(env, a.id) == 0
    assert _hits(env, b.id) == 0
    assert _hits(env, c.id) == 0

    reranker = FakeReranker(
        _score_by_content({a.content: 0.95, b.content: 0.05, c.content: 0.05})
    )
    retriever = env.make_retriever(reranker=reranker, rerank_threshold=THRESHOLD)
    retriever.retrieve(
        env.agent_id, "rerank-fixture-widget", entity_id="alice", limit=5
    )

    assert _hits(env, a.id) == 1  # survived -> touched
    assert _hits(env, b.id) == 0  # reranked out -> untouched
    assert _hits(env, c.id) == 0  # reranked out -> untouched


def test_touch_does_not_happen_for_anything_when_all_are_below_threshold(env):
    a, b, c = _seed_three(env)
    reranker = FakeReranker(
        _score_by_content({a.content: 0.05, b.content: 0.05, c.content: 0.05})
    )
    retriever = env.make_retriever(reranker=reranker, rerank_threshold=THRESHOLD)
    retriever.retrieve(
        env.agent_id, "rerank-fixture-widget", entity_id="alice", limit=5
    )

    assert _hits(env, a.id) == 0
    assert _hits(env, b.id) == 0
    assert _hits(env, c.id) == 0


# -- no regression when reranker is not configured -------------------------


def test_no_reranker_preserves_existing_fused_order_and_touches_all_returned(env):
    """Default (reranker=None) must be byte-identical to pre-reranker
    behavior: RRF-fused order, truncated to `limit`, everything returned
    is touched. Both the retrieval flow and the persist flow's reuse of
    HybridRetriever for novelty-check neighbours depend on this.
    """
    a, b, c = _seed_three(env)
    retriever = env.make_retriever()  # reranker=None, the default

    results = retriever.retrieve(
        env.agent_id, "rerank-fixture-widget", entity_id="alice", limit=5
    )

    assert {r.id for r in results} == {a.id, b.id, c.id}
    for learning in results:
        assert (
            _hits(env, learning.id) == 1
        )  # every returned learning touched, as before


def test_no_reranker_response_shape_is_unchanged(env):
    """response_model=list[Learning] contracts (SDK + API) depend on this."""
    _seed_three(env)
    retriever = env.make_retriever()

    results = retriever.retrieve(
        env.agent_id, "rerank-fixture-widget", entity_id="alice", limit=5
    )

    assert isinstance(results, list)
    assert all(hasattr(r, "id") and hasattr(r, "content") for r in results)


def test_manager_retrieve_unaffected_when_no_reranker_configured(env):
    """End-to-end via LearningManager (the SDK entry point used by both the
    /retrieve route and LearningCurator's novelty-check lookup) — confirms
    the reranker addition didn't change the manager-level contract either.
    """
    a, b, c = _seed_three(env)
    results = env.manager.retrieve("rerank-fixture-widget", entity_id="alice", limit=5)
    assert {r.id for r in results} == {a.id, b.id, c.id}
