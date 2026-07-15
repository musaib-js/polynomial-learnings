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
    # Reuse the shared embedder rather than reloading the model per test.
    app = create_app()
    app.state.embedder = EMBEDDER
    app.state.backend = PgVectorBackend(DSN)
    with TestClient(app) as c:
        yield c
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
