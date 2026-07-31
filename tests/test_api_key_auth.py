"""API-key authentication and per-organization agent ownership.

Replaces the old shared-env-var gate (tests/test_api_auth.py). No database
needed: the auth store is stubbed, so these run anywhere.

The two properties under test are the ones the scheme exists for — a key is
only usable while it is active, and it only reaches its own org's agents.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from learnings.api.app import create_app
from learnings.auth.models import ApiKeyRecord
from learnings.auth.security import hash_api_key

ORG_A = "11111111-1111-1111-1111-111111111111"
ORG_B = "22222222-2222-2222-2222-222222222222"
AGENT_A = "agt_owned_by_org_a"
AGENT_B = "agt_owned_by_org_b"

RAW_KEY = "sk_live_org-a-key"
MESSAGES = {"messages": [{"role": "user", "content": "hello"}], "limit": 5}


def make_key(**overrides) -> ApiKeyRecord:
    """An active key belonging to ORG_A, unless overridden."""
    fields = {
        "id": "key-1",
        "org_id": ORG_A,
        "created_by": "user-1",
        "name": "test key",
        "key_prefix": RAW_KEY[:16],
        "key_hash": hash_api_key(RAW_KEY),
        "created_at": datetime.now(timezone.utc),
    }
    fields.update(overrides)
    return ApiKeyRecord(**fields)


def build_client(key_record: ApiKeyRecord | None) -> tuple[TestClient, MagicMock]:
    """App whose auth store returns ``key_record`` for any key hash.

    ``None`` simulates a hash that matches no row at all.
    """
    app = create_app()
    store = MagicMock()
    store.get_api_key_by_hash.return_value = key_record
    # ORG_A owns AGENT_A and nothing else.
    store.agent_belongs_to_org.side_effect = lambda agent_id, org_id: (
        agent_id == AGENT_A and org_id == ORG_A
    )
    store.get_agent.return_value = None
    app.state.auth_store = store
    app.state.backend = MagicMock()
    app.state.embedder = MagicMock()
    app.state.judge = None
    return TestClient(app), store


def retrieve(client: TestClient, agent_id: str, key: str | None = RAW_KEY):
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    return client.post(
        f"/v1/agents/{agent_id}/retrieve", json=MESSAGES, headers=headers
    )


# -- the key itself ----------------------------------------------------------


def test_missing_key_is_rejected():
    client, _ = build_client(make_key())
    assert retrieve(client, AGENT_A, key=None).status_code == 401


def test_unknown_key_is_rejected():
    # No row matches the presented hash.
    client, _ = build_client(None)
    assert retrieve(client, AGENT_A).status_code == 401


def test_revoked_key_is_rejected():
    client, _ = build_client(make_key(revoked_at=datetime.now(timezone.utc)))
    assert retrieve(client, AGENT_A).status_code == 401


def test_expired_key_is_rejected():
    past = datetime.now(timezone.utc) - timedelta(seconds=1)
    client, _ = build_client(make_key(expires_at=past))
    assert retrieve(client, AGENT_A).status_code == 401


def test_valid_key_on_own_agent_is_accepted():
    client, _ = build_client(make_key())
    assert retrieve(client, AGENT_A).status_code == 200


def test_key_is_looked_up_by_hash_never_by_raw_value():
    client, store = build_client(make_key())
    retrieve(client, AGENT_A)
    (looked_up,), _ = store.get_api_key_by_hash.call_args
    assert looked_up == hash_api_key(RAW_KEY)
    assert RAW_KEY not in looked_up


def test_successful_call_stamps_last_used():
    client, store = build_client(make_key())
    retrieve(client, AGENT_A)
    store.touch_api_key_last_used.assert_called_once_with("key-1")


# -- ownership ---------------------------------------------------------------


def test_another_orgs_agent_is_404_not_403():
    """404 on purpose: a 403 would confirm the agent_id exists."""
    client, _ = build_client(make_key())
    assert retrieve(client, AGENT_B).status_code == 404


@pytest.mark.parametrize(
    "path",
    [
        f"/v1/agents/{AGENT_B}/learnings?entity_id=alice",
        f"/v1/agents/{AGENT_B}/learnings/global",
        f"/v1/agents/{AGENT_B}/stats",
        f"/v1/agents/{AGENT_B}/tokens",
    ],
)
def test_every_agent_scoped_get_enforces_ownership(path):
    """Guards live per-route, so a route added without one would be open.

    /learnings in particular shipped without a guard and was reachable by
    anyone who guessed an agent_id.
    """
    client, _ = build_client(make_key())
    response = client.get(path, headers={"Authorization": f"Bearer {RAW_KEY}"})
    assert response.status_code == 404
