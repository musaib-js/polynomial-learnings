"""API key enforcement on the /v1 routes.

No database needed: the backend is stubbed, so these run everywhere (unlike
``test_api.py``, which is gated on ``DATABASE_URL``). ``/v1/agents`` is used
throughout because it is the one route that only needs ``get_backend``.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from learnings.api.app import create_app

AGENTS = "/v1/agents"


def build_client(api_key: str | None) -> TestClient:
    """An app with ``api_key`` configured and a stubbed backend."""
    app = create_app()
    app.state.api_key = api_key
    backend = MagicMock()
    backend.list_agents.return_value = []
    app.state.backend = backend
    return TestClient(app)


def test_no_key_configured_leaves_routes_open():
    client = build_client(None)
    assert client.get(AGENTS).status_code == 200


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer wrong"},
        {"Authorization": "s3cret"},  # right key, missing the Bearer scheme
    ],
)
def test_bad_credentials_are_rejected(headers):
    client = build_client("s3cret")
    assert client.get(AGENTS, headers=headers).status_code == 401


def test_valid_key_is_accepted():
    client = build_client("s3cret")
    response = client.get(AGENTS, headers={"Authorization": "Bearer s3cret"})
    assert response.status_code == 200


def test_health_is_never_gated():
    client = build_client("s3cret")
    assert client.get("/health").status_code == 200
