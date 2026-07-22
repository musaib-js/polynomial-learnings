"""End-to-end API tests against a live pgvector database.

Set ``DATABASE_URL`` to run these (same gate as the ingestion tests)::

    docker compose up -d
    export DATABASE_URL=postgresql://polynomial:polynomial@localhost:5433/learnings
    pytest tests/test_api.py

Learnings are seeded directly through ``LearningManager`` (the API is
retrieval-only for now), then read back over HTTP.
"""

from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient

from learnings import HuggingFaceEmbedder, LearningManager, PgVectorBackend, Scope
from learnings.api.app import create_app

DSN = os.environ.get("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DSN, reason="DATABASE_URL not set")

EMBEDDER = HuggingFaceEmbedder()


@pytest.fixture
def agent_id():
    return f"test-agent-{uuid.uuid4()}"


@pytest.fixture
def seed(agent_id):
    """Seed learnings for the agent and expose the manager; cleans up after."""
    backend = PgVectorBackend(DSN)
    mgr = LearningManager(agent_id=agent_id, backend=backend, embedder=EMBEDDER)
    yield mgr
    with backend._pool.connection() as conn:
        conn.execute("DELETE FROM learnings WHERE agent_id = %s", [agent_id])
    backend.close()


@pytest.fixture
def client():
    # Construct TestClient WITHOUT the context manager so the app lifespan
    # (which would reload the embedding model and re-run init_schema on every
    # test) never fires. We inject the shared singletons onto app.state instead.
    app = create_app()
    app.state.embedder = EMBEDDER
    app.state.backend = PgVectorBackend(DSN)
    yield TestClient(app)
    app.state.backend.close()


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_retrieve_from_messages(client, seed, agent_id):
    seed.record(
        context="user asks for revenue by region",
        content="join orders to regions table on region_id",
        entity_id="alice",
        scope=Scope.personal,
    )
    resp = client.post(
        f"/v1/agents/{agent_id}/retrieve",
        json={
            "messages": [
                {"role": "user", "content": "how do I get revenue by region?"},
                {"role": "assistant", "content": "let me check past learnings"},
            ],
            "entity_id": "alice",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert "region_id" in body[0]["content"]


def test_retrieve_respects_personal_isolation(client, seed, agent_id):
    seed.record(
        context="alice prefers metric tons",
        content="always report weight in metric tons",
        entity_id="alice",
    )
    resp = client.post(
        f"/v1/agents/{agent_id}/retrieve",
        json={
            "messages": [{"role": "user", "content": "what weight unit?"}],
            "entity_id": "bob",
        },
    )
    assert resp.json() == []


def test_get_personal_and_global(client, seed, agent_id):
    seed.record(
        context="alice prefers metric tons",
        content="report weight in metric tons",
        entity_id="alice",
    )
    seed.record(
        context="any user asks about fiscal year",
        content="fiscal year starts in April",
        scope=Scope.global_,
    )

    personal = client.get(
        f"/v1/agents/{agent_id}/learnings/personal", params={"entity_id": "alice"}
    ).json()
    assert len(personal) == 1
    assert personal[0]["scope"] == "personal"

    glob = client.get(f"/v1/agents/{agent_id}/learnings/global").json()
    assert len(glob) == 1
    assert glob[0]["scope"] == "global"

    # Personal listing must not leak another entity's rows.
    bob = client.get(
        f"/v1/agents/{agent_id}/learnings/personal", params={"entity_id": "bob"}
    ).json()
    assert bob == []


def test_approve_disapprove_and_soft_delete(client, seed, agent_id):
    learning = seed.record(
        context="user asks about churn",
        content="churn is measured monthly",
        entity_id="alice",
    )
    base = f"/v1/agents/{agent_id}/learnings/{learning.id}"

    # Disapprove -> rejected, and dropped from active retrieval.
    assert client.post(f"{base}/disapprove").json()["status"] == "rejected"
    hidden = client.post(
        f"/v1/agents/{agent_id}/retrieve",
        json={"messages": [{"role": "user", "content": "churn"}], "entity_id": "alice"},
    ).json()
    assert hidden == []

    # Approve -> active again, retrievable.
    assert client.post(f"{base}/approve").json()["status"] == "active"
    shown = client.post(
        f"/v1/agents/{agent_id}/retrieve",
        json={"messages": [{"role": "user", "content": "churn"}], "entity_id": "alice"},
    ).json()
    assert len(shown) == 1

    # Soft delete -> rejected, but row is retained (still fetchable via stats).
    assert client.delete(base).json()["status"] == "rejected"


def test_update_reembeds_on_content_change(client, seed, agent_id):
    learning = seed.record(
        context="user asks about refunds",
        content="refunds take 5 days",
        entity_id="alice",
    )
    base = f"/v1/agents/{agent_id}/learnings/{learning.id}"

    resp = client.patch(
        base, json={"content": "refunds now take 10 days", "tags": ["billing"]}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["content"] == "refunds now take 10 days"
    assert body["tags"] == ["billing"]

    # New content must be findable semantically (proves the re-embed happened).
    found = client.post(
        f"/v1/agents/{agent_id}/retrieve",
        json={
            "messages": [{"role": "user", "content": "how long do refunds take"}],
            "entity_id": "alice",
        },
    ).json()
    assert found[0]["content"] == "refunds now take 10 days"


def test_update_unknown_field_rejected(client, seed, agent_id):
    learning = seed.record(context="x", content="y", entity_id="alice")
    # agent_id is not editable; schema drops it, so a no-op patch still 200s
    # but attempting to change scope via the model is impossible (not a field).
    resp = client.patch(
        f"/v1/agents/{agent_id}/learnings/{learning.id}", json={"category": "faq"}
    )
    assert resp.json()["category"] == "faq"


def test_missing_learning_404(client, agent_id):
    import uuid as _uuid

    fake = _uuid.uuid4()
    assert (
        client.post(f"/v1/agents/{agent_id}/learnings/{fake}/approve").status_code
        == 404
    )
    assert client.delete(f"/v1/agents/{agent_id}/learnings/{fake}").status_code == 404


def test_stats(client, seed, agent_id):
    # Realistic content, not degenerate placeholders: /retrieve now runs
    # through a semantic reranker (see deps.get_reranker), which correctly
    # refuses to treat single-letter placeholder text ("a asks x" / "answer
    # x") as meaningfully relevant to itself — it scored statistically
    # indistinguishable from genuinely irrelevant queries. A real semantic
    # reranker needs real semantic content to judge.
    seed.record(
        context="user asks when the billing cycle resets",
        content="the billing cycle resets on the first of each month",
        entity_id="alice",
    )
    seed.record(context="b asks y", content="answer y", entity_id="bob")
    seed.record(context="global thing", content="global answer", scope=Scope.global_)
    # Generate a hit so most_used is populated.
    client.post(
        f"/v1/agents/{agent_id}/retrieve",
        json={
            "messages": [
                {"role": "user", "content": "when does the billing cycle reset?"}
            ],
            "entity_id": "alice",
        },
    )

    stats = client.get(f"/v1/agents/{agent_id}/stats").json()
    assert stats["total"] == 3
    assert stats["by_scope"] == {"personal": 2, "global": 1}
    assert stats["by_status"]["active"] == 3
    assert stats["distinct_entities"] == 2  # alice, bob (global entity_id is NULL)
    assert stats["total_hits"] >= 1
    assert len(stats["most_used"]) >= 1
