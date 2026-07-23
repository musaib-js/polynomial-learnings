"""Integration tests for LearningCurator.persist — the Persist Learning API.

Real Postgres/pgvector backend, real HuggingFaceEmbedder, real HybridRetriever
(semantic + keyword + RRF, unmodified). Only the Judge is faked — this suite
never stubs or bypasses retrieval, per the plan.

Set DATABASE_URL to run these, same as tests/test_ingest_retrieve.py::

    docker compose up -d
    export DATABASE_URL=postgresql://polynomial:change-me@localhost:5433/learnings
    pytest tests/test_curator_persist.py
"""

from __future__ import annotations

import os
import uuid

import pytest

from learnings import HuggingFaceEmbedder, LearningManager, PgVectorBackend
from learnings.curator import LearningCurator
from learnings.judge import FakeJudge
from learnings.models import (
    GeneratedLearning,
    JudgeVerdict,
    Message,
    Scope,
    Verdict,
)
from learnings.retriever import HybridRetriever

DSN = os.environ.get("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DSN, reason="DATABASE_URL not set")

# Reuses the module-level embedder + session schema fixture already
# established by tests/test_ingest_retrieve.py (same 384-dim table).
EMBEDDER = HuggingFaceEmbedder()


def _messages(*texts: str) -> list[Message]:
    return [Message(role="user", content=t) for t in texts]


@pytest.fixture
def env():
    """A fresh agent_id + wired-up manager/curator, torn down after the test."""
    agent_id = f"test-curator-{uuid.uuid4()}"
    backend = PgVectorBackend(DSN)
    retriever = HybridRetriever(backend, EMBEDDER)
    manager = LearningManager(
        agent_id=agent_id, backend=backend, embedder=EMBEDDER, retriever=retriever
    )

    class Env:
        pass

    e = Env()
    e.agent_id = agent_id
    e.backend = backend
    e.retriever = retriever
    e.manager = manager

    def make_curator(judge: FakeJudge, **kwargs) -> LearningCurator:
        return LearningCurator(backend, EMBEDDER, judge, retriever, **kwargs)

    e.make_curator = make_curator

    yield e

    with backend._pool.connection() as conn:
        conn.execute("DELETE FROM learnings WHERE agent_id = %s", [agent_id])
    backend.close()


def _row_status(env, learning_id: str) -> str:
    with env.backend._pool.connection() as conn:
        cur = conn.execute("SELECT status FROM learnings WHERE id = %s", [learning_id])
        return cur.fetchone()[0]


# -- reject ------------------------------------------------------------------


def test_reject_persists_nothing(env):
    judge = FakeJudge(
        JudgeVerdict(verdict=Verdict.reject, reason="trivial restatement")
    )
    curator = env.make_curator(judge)

    result = curator.persist(
        env.agent_id, _messages("thanks, that helps"), entity_id="alice"
    )

    assert result.decision == "rejected"
    assert result.verdict is Verdict.reject
    assert env.manager.retrieve("thanks that helps", entity_id="alice") == []


def test_no_user_messages_rejects(env):
    judge = FakeJudge(JudgeVerdict(verdict=Verdict.reject))
    curator = env.make_curator(judge)

    result = curator.persist(
        env.agent_id,
        [Message(role="assistant", content="how can I help?")],
        entity_id="alice",
    )

    assert result.decision == "rejected"
    assert "no user messages" in result.reason


# -- new -----------------------------------------------------------------


def test_new_inserts_active_learning(env):
    generated = GeneratedLearning(
        context="user asks for revenue by region",
        content="join orders to regions on region_id",
        scope=Scope.personal,
    )
    judge = FakeJudge(JudgeVerdict(verdict=Verdict.new, learning=generated))
    curator = env.make_curator(judge)

    result = curator.persist(
        env.agent_id, _messages("revenue by region please"), entity_id="alice"
    )

    assert result.decision == "persisted"
    assert result.verdict is Verdict.new
    assert result.learning_id is not None
    assert _row_status(env, result.learning_id) == "active"

    retrieved = env.manager.retrieve("revenue by region", entity_id="alice")
    assert len(retrieved) == 1
    assert "region_id" in retrieved[0].content


def test_global_scope_forces_entity_id_none_even_if_request_has_one(env):
    generated = GeneratedLearning(
        context="any user asks about fiscal year",
        content="fiscal year starts in April",
        scope=Scope.global_,
    )
    judge = FakeJudge(JudgeVerdict(verdict=Verdict.new, learning=generated))
    curator = env.make_curator(judge)

    # Request supplies entity_id=alice, but the judge decided global scope.
    result = curator.persist(
        env.agent_id, _messages("when is fiscal year?"), entity_id="alice"
    )
    assert result.decision == "persisted"

    for entity in ("alice", "bob", None):
        found = env.manager.retrieve("fiscal year", entity_id=entity)
        assert len(found) == 1
        assert found[0].entity_id is None


def test_personal_scope_without_entity_id_is_rejected(env):
    generated = GeneratedLearning(
        context="alice prefers metric units",
        content="always report weight in kg",
        scope=Scope.personal,
    )
    judge = FakeJudge(JudgeVerdict(verdict=Verdict.new, learning=generated))
    curator = env.make_curator(judge)

    result = curator.persist(
        env.agent_id, _messages("report weight in kg"), entity_id=None
    )

    assert result.decision == "rejected"
    assert "entity_id" in result.reason


# -- same ------------------------------------------------------------------


def test_same_touches_existing_and_creates_nothing_new(env):
    existing = env.manager.record(
        context="user asks about churn rate widget-frobnicator-xyz",
        content="churn is measured monthly",
        entity_id="alice",
    )
    assert existing.hits == 0

    judge = FakeJudge(
        JudgeVerdict(verdict=Verdict.same, related_learning_id=existing.id)
    )
    curator = env.make_curator(judge)

    result = curator.persist(
        env.agent_id,
        _messages("what about churn widget-frobnicator-xyz?"),
        entity_id="alice",
    )

    assert result.decision == "persisted"
    assert result.verdict is Verdict.same
    assert result.learning_id == existing.id

    retrieved = env.manager.retrieve("churn widget-frobnicator-xyz", entity_id="alice")
    assert len(retrieved) == 1  # no duplicate row created
    assert (
        retrieved[0].hits >= 1
    )  # touched (once by curator, once more by this retrieve call)


# -- refine ------------------------------------------------------------------


def test_refine_preserves_created_at_and_hits(env):
    existing = env.manager.record(
        context="user asks about SQL performance widget-frobnicator-xyz",
        content="add an index on created_at",
        entity_id="alice",
    )
    # Simulate prior retrieval activity before the refine happens.
    env.backend.update(existing.id, hits=7)
    original_created_at = existing.created_at

    generated = GeneratedLearning(
        context="user asks about SQL performance widget-frobnicator-xyz",
        content="add a composite index on (agent_id, created_at)",
        scope=Scope.personal,
    )
    judge = FakeJudge(
        JudgeVerdict(
            verdict=Verdict.refine, related_learning_id=existing.id, learning=generated
        )
    )
    curator = env.make_curator(judge)

    result = curator.persist(
        env.agent_id,
        _messages("more detail on that SQL performance widget-frobnicator-xyz tip"),
        entity_id="alice",
    )

    assert result.decision == "persisted"
    assert result.verdict is Verdict.refine
    assert result.learning_id == existing.id  # same row, not a new one

    retrieved = env.manager.retrieve(
        "SQL performance widget-frobnicator-xyz", entity_id="alice"
    )
    assert len(retrieved) == 1
    refined = retrieved[0]
    assert "composite index" in refined.content
    assert refined.hits >= 7  # NOT reset to 0 by the upsert
    assert refined.created_at == original_created_at  # identity preserved


# -- contradict --------------------------------------------------------------


def test_contradict_supersedes_old_and_creates_new(env):
    existing = env.manager.record(
        context="user asks about default timeout widget-frobnicator-xyz",
        content="default timeout is 30 seconds",
        entity_id="alice",
    )

    generated = GeneratedLearning(
        context="user asks about default timeout widget-frobnicator-xyz",
        content="default timeout is actually 60 seconds, not 30",
        scope=Scope.personal,
    )
    judge = FakeJudge(
        JudgeVerdict(
            verdict=Verdict.contradict,
            related_learning_id=existing.id,
            learning=generated,
        )
    )
    curator = env.make_curator(judge)

    result = curator.persist(
        env.agent_id,
        _messages("actually the timeout widget-frobnicator-xyz is 60 seconds"),
        entity_id="alice",
    )

    assert result.decision == "persisted"
    assert result.verdict is Verdict.contradict
    assert result.superseded_id == existing.id
    assert result.learning_id != existing.id
    assert _row_status(env, existing.id) == "superseded"
    assert _row_status(env, result.learning_id) == "active"

    retrieved = env.manager.retrieve(
        "default timeout widget-frobnicator-xyz", entity_id="alice"
    )
    assert len(retrieved) == 1  # superseded row excluded from retrieval
    assert "60 seconds" in retrieved[0].content


# -- hallucinated related_learning_id ----------------------------------------


def test_contradict_with_unknown_related_id_falls_back_to_new(env, caplog):
    generated = GeneratedLearning(
        context="user asks about retry policy widget-frobnicator-xyz",
        content="retries use exponential backoff",
        scope=Scope.personal,
    )
    judge = FakeJudge(
        JudgeVerdict(
            verdict=Verdict.contradict,
            related_learning_id="does-not-exist",
            learning=generated,
        )
    )
    curator = env.make_curator(judge)

    result = curator.persist(
        env.agent_id,
        _messages("what's the retry policy widget-frobnicator-xyz?"),
        entity_id="alice",
    )

    assert result.decision == "persisted"
    assert result.verdict is Verdict.new  # fallback, honestly reported
    assert result.superseded_id is None


def test_same_with_unknown_related_id_is_rejected(env):
    judge = FakeJudge(
        JudgeVerdict(verdict=Verdict.same, related_learning_id="does-not-exist")
    )
    curator = env.make_curator(judge)

    result = curator.persist(env.agent_id, _messages("some message"), entity_id="alice")

    assert result.decision == "rejected"
    assert "does-not-exist" in result.reason
