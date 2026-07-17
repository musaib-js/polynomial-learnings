"""End-to-end HTTP tests for POST /v1/agents/{agent_id}/persist (Phase 7).

Real Postgres/pgvector + real HuggingFaceEmbedder + real HybridRetriever, same
conventions as tests/test_api.py. Only the Judge is faked — injected onto
app.state *after* the TestClient's lifespan has run (the lifespan sets
app.state.judge unconditionally, so pre-lifespan overrides would be lost).

Set DATABASE_URL to run these, same gate as the other suites.
"""

from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient

from learnings import HuggingFaceEmbedder, PgVectorBackend
from learnings.api.app import create_app
from learnings.judge import FakeJudge
from learnings.models import GeneratedLearning, JudgeVerdict, Scope, Verdict

DSN = os.environ.get("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DSN, reason="DATABASE_URL not set")

EMBEDDER = HuggingFaceEmbedder()


@pytest.fixture
def agent_id():
    return f"test-agent-{uuid.uuid4()}"


@pytest.fixture
def client():
    app = create_app()
    with TestClient(app) as c:
        # Reuse the cached embedder/backend, same pattern as test_api.py.
        app.state.embedder = EMBEDDER
        app.state.backend = PgVectorBackend(DSN)
        yield c
    app.state.backend.close()


def _cleanup(client, agent_id):
    with client.app.state.backend._pool.connection() as conn:
        conn.execute("DELETE FROM learnings WHERE agent_id = %s", [agent_id])


# -- judge-not-configured (regression guard for /retrieve) -------------------


def test_persist_without_judge_configured_returns_503(client, agent_id):
    client.app.state.judge = None  # simulates GROQ_API_KEY unset
    resp = client.post(
        f"/v1/agents/{agent_id}/persist",
        json={"messages": [{"role": "user", "content": "hi"}], "entity_id": "alice"},
    )
    assert resp.status_code == 503


def test_retrieve_route_still_works_without_a_judge(client, agent_id):
    """Adding /persist and threading judge through get_manager must not
    break the existing retrieval routes when no judge is configured."""
    client.app.state.judge = None
    resp = client.post(
        f"/v1/agents/{agent_id}/retrieve",
        json={
            "messages": [{"role": "user", "content": "anything"}],
            "entity_id": "alice",
        },
    )
    assert resp.status_code == 200
    assert resp.json() == []


# -- persist: reject / new / round-trip ---------------------------------


def test_persist_rejected(client, agent_id):
    client.app.state.judge = FakeJudge(
        JudgeVerdict(verdict=Verdict.reject, reason="trivial")
    )
    resp = client.post(
        f"/v1/agents/{agent_id}/persist",
        json={
            "messages": [{"role": "user", "content": "thanks, bye!"}],
            "entity_id": "alice",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["decision"] == "rejected"
    assert body["verdict"] == "reject"
    assert body["learning_id"] is None


def test_persist_new_learning_and_round_trip_via_retrieve(client, agent_id):
    client.app.state.judge = FakeJudge(
        JudgeVerdict(
            verdict=Verdict.new,
            learning=GeneratedLearning(
                context="user asks about pagination style http-api-smoke-xyz",
                content="use cursor-based pagination",
                scope=Scope.personal,
            ),
        )
    )
    resp = client.post(
        f"/v1/agents/{agent_id}/persist",
        json={
            "messages": [
                {"role": "user", "content": "how should I paginate http-api-smoke-xyz?"}
            ],
            "entity_id": "alice",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["decision"] == "persisted"
    assert body["verdict"] == "new"
    assert body["learning_id"]

    # Round-trip through the senior's existing /retrieve route.
    retrieve_resp = client.post(
        f"/v1/agents/{agent_id}/retrieve",
        json={
            "messages": [
                {"role": "user", "content": "pagination approach http-api-smoke-xyz?"}
            ],
            "entity_id": "alice",
        },
    )
    assert retrieve_resp.status_code == 200
    retrieved = retrieve_resp.json()
    assert len(retrieved) == 1
    assert retrieved[0]["id"] == body["learning_id"]

    _cleanup(client, agent_id)


def test_persist_personal_scope_without_entity_id_is_rejected_not_500(client, agent_id):
    client.app.state.judge = FakeJudge(
        JudgeVerdict(
            verdict=Verdict.new,
            learning=GeneratedLearning(context="c", content="v", scope=Scope.personal),
        )
    )
    resp = client.post(
        f"/v1/agents/{agent_id}/persist",
        json={
            "messages": [{"role": "user", "content": "some message"}]
        },  # no entity_id
    )
    assert resp.status_code == 200
    assert resp.json()["decision"] == "rejected"
