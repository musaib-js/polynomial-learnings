"""End-to-end ingestion + retrieval tests against a live pgvector database.

Set ``DATABASE_URL`` to run these, e.g.::

    docker compose up -d
    export DATABASE_URL=postgresql://polynomial:polynomial@localhost:5432/learnings
    pytest

Each test runs against an isolated agent_id and cleans up after itself, so the
suite is safe to run repeatedly against the same database.
"""

from __future__ import annotations

import os
import uuid

import pytest

from learnings import (
    HuggingFaceEmbedder,
    LearningManager,
    PgVectorBackend,
    Outcome,
    Scope,
    init_schema,
    reciprocal_rank_fusion,
)
from learnings.models import Learning

DSN = os.environ.get("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DSN, reason="DATABASE_URL not set")

# Loaded once for the whole suite (model download is cached after first run).
EMBEDDER = HuggingFaceEmbedder()


@pytest.fixture(scope="session", autouse=True)
def _schema():
    if DSN:
        init_schema(DSN, EMBEDDER.dimension)


@pytest.fixture
def manager():
    agent_id = f"test-agent-{uuid.uuid4()}"
    backend = PgVectorBackend(DSN)
    mgr = LearningManager(agent_id=agent_id, backend=backend, embedder=EMBEDDER)
    yield mgr
    backend._conn.execute("DELETE FROM learnings WHERE agent_id = %s", [agent_id])
    backend.close()


def test_ingest_and_retrieve(manager):
    manager.record(
        context="user asks for revenue by region",
        content="join orders to regions table on region_id",
        entity_id="alice",
        outcome=Outcome.positive,
    )
    results = manager.retrieve(query="revenue by region", entity_id="alice")
    assert len(results) == 1
    assert "region_id" in results[0].content


def test_personal_isolation(manager):
    manager.record(
        context="alice prefers metric tons",
        content="always report weight in metric tons",
        entity_id="alice",
    )
    # Bob must never see Alice's personal learning.
    bob_results = manager.retrieve(query="metric tons weight", entity_id="bob")
    assert bob_results == []
    alice_results = manager.retrieve(query="metric tons weight", entity_id="alice")
    assert len(alice_results) == 1


def test_global_visible_to_all(manager):
    manager.record(
        context="any user asks about fiscal year",
        content="fiscal year starts in April",
        scope=Scope.global_,
    )
    for entity in ("alice", "bob", None):
        results = manager.retrieve(query="fiscal year start", entity_id=entity)
        assert len(results) == 1
        assert "April" in results[0].content


def test_touch_increments_hits(manager):
    manager.record(
        context="user asks about churn",
        content="churn is measured monthly",
        entity_id="alice",
    )
    first = manager.retrieve(query="churn measured", entity_id="alice")
    assert first[0].hits == 1
    second = manager.retrieve(query="churn measured", entity_id="alice")
    assert second[0].hits == 2


def test_personal_requires_entity_id(manager):
    with pytest.raises(ValueError):
        manager.record(context="x", content="y", scope=Scope.personal)


def test_hybrid_finds_keyword_and_semantic(manager):
    # A learning whose exact keyword matches, and another that shares words.
    manager.record(
        context="report about quarterly SQL performance tuning",
        content="add an index on the created_at column",
        entity_id="alice",
    )
    manager.record(
        context="user asks about SQL query speed",
        content="use EXPLAIN ANALYZE to inspect the plan",
        entity_id="alice",
    )
    results = manager.retrieve(query="SQL performance", entity_id="alice", limit=5)
    assert len(results) == 2


def test_rrf_fusion_unit():
    # Pure unit test of the fusion function (no DB needed).
    a = Learning(id="a", agent_id="x", context="c", content="c")
    b = Learning(id="b", agent_id="x", context="c", content="c")
    c = Learning(id="c", agent_id="x", context="c", content="c")
    # b appears high in both lists -> should rank first.
    fused = reciprocal_rank_fusion([[a, b], [b, c]])
    assert fused[0][0].id == "b"
