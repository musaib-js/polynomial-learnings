"""Tests for LearningManager.persist_from_conversation — the SDK entry point
that wires a Judge + LearningCurator onto the manager (Phase 6).

Real Postgres/pgvector + real HuggingFaceEmbedder + real HybridRetriever;
only the Judge is faked. Set DATABASE_URL to run, same as the other suites.
"""

from __future__ import annotations

import os
import uuid

import pytest

from learnings import HuggingFaceEmbedder, LearningManager, PgVectorBackend
from learnings.judge import FakeJudge
from learnings.models import GeneratedLearning, JudgeVerdict, Message, Scope, Verdict

DSN = os.environ.get("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DSN, reason="DATABASE_URL not set")

EMBEDDER = HuggingFaceEmbedder()


@pytest.fixture
def backend():
    b = PgVectorBackend(DSN)
    yield b
    b.close()


def test_manager_without_judge_raises_on_persist(backend):
    agent_id = f"test-mgr-{uuid.uuid4()}"
    manager = LearningManager(agent_id=agent_id, backend=backend, embedder=EMBEDDER)

    with pytest.raises(ValueError, match="requires a judge"):
        manager.persist_from_conversation([Message(role="user", content="hi")], entity_id="alice")


def test_manager_with_judge_persists_end_to_end(backend):
    agent_id = f"test-mgr-{uuid.uuid4()}"
    judge = FakeJudge(
        JudgeVerdict(
            verdict=Verdict.new,
            learning=GeneratedLearning(
                context="user asks about API rate limits sdk-smoke-test-xyz",
                content="the free tier allows 30 requests per minute",
                scope=Scope.personal,
            ),
        )
    )
    manager = LearningManager(agent_id=agent_id, backend=backend, embedder=EMBEDDER, judge=judge)

    result = manager.persist_from_conversation(
        [Message(role="user", content="what are the rate limits sdk-smoke-test-xyz?")],
        entity_id="alice",
    )
    assert result.decision == "persisted"
    assert result.verdict is Verdict.new

    # Round-trip: the write path feeds the (unmodified) read path.
    retrieved = manager.retrieve("rate limits sdk-smoke-test-xyz", entity_id="alice")
    assert len(retrieved) == 1
    assert "30 requests" in retrieved[0].content

    with backend._pool.connection() as conn:
        conn.execute("DELETE FROM learnings WHERE agent_id = %s", [agent_id])


def test_retrieval_only_manager_still_works_without_judge(backend):
    """Regression guard: existing /retrieve-style usage must be unaffected."""
    agent_id = f"test-mgr-{uuid.uuid4()}"
    manager = LearningManager(agent_id=agent_id, backend=backend, embedder=EMBEDDER)

    learning = manager.record(
        context="user asks about pagination sdk-smoke-test-xyz",
        content="use cursor-based pagination",
        entity_id="alice",
    )
    results = manager.retrieve_for_conversation(
        [Message(role="user", content="how does pagination sdk-smoke-test-xyz work?")],
        entity_id="alice",
    )
    assert len(results) == 1
    assert results[0].id == learning.id

    with backend._pool.connection() as conn:
        conn.execute("DELETE FROM learnings WHERE agent_id = %s", [agent_id])
