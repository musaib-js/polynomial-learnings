"""Unit tests for the HTTP client layer (``LearningClient``).

No live server: an ``httpx.MockTransport`` captures each request and returns a
canned response, so we assert the client hits the right URL, sends the right
body, parses responses into models, and maps errors to ``LearningsAPIError``.
"""

from __future__ import annotations

import json

import httpx
import pytest

from learnings.client import LearningClient
from learnings.exceptions import LearningsAPIError
from learnings.models import Learning, Message


def _client(handler) -> LearningClient:
    transport = httpx.MockTransport(handler)
    http = httpx.Client(base_url="http://test", transport=transport)
    return LearningClient("agent-1", base_url="http://test", client=http)


def test_retrieve_hits_endpoint_and_parses_learnings():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = request.url.path
        captured["body"] = json.loads(request.content)
        learning = Learning(agent_id="agent-1", context="ctx", content="do the thing")
        return httpx.Response(200, json=[learning.model_dump(mode="json")])

    client = _client(handler)
    out = client.retrieve(
        [Message(role="user", content="how do I X?")], entity_id="u1", limit=3
    )

    assert captured["url"] == "/v1/agents/agent-1/retrieve"
    assert captured["body"] == {
        "messages": [{"role": "user", "content": "how do I X?"}],
        "entity_id": "u1",
        "limit": 3,
    }
    assert len(out) == 1
    assert isinstance(out[0], Learning)
    assert out[0].content == "do the thing"


def test_retrieve_accepts_raw_dict_messages():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["messages"] == [{"role": "user", "content": "hi"}]
        return httpx.Response(200, json=[])

    client = _client(handler)
    assert client.retrieve([{"role": "user", "content": "hi"}]) == []


def test_persist_parses_result():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/agents/agent-1/persist"
        return httpx.Response(
            200,
            json={"decision": "persisted", "verdict": "new", "learning_id": "L1"},
        )

    client = _client(handler)
    result = client.persist([{"role": "user", "content": "note"}], entity_id="u1")
    assert result.decision == "persisted"
    assert result.learning_id == "L1"


def test_non_2xx_raises_with_status_and_detail():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"detail": "no judge configured"})

    client = _client(handler)
    with pytest.raises(LearningsAPIError) as exc_info:
        client.persist([{"role": "user", "content": "x"}])
    assert exc_info.value.status_code == 503
    assert "no judge configured" in str(exc_info.value)


def test_transport_error_raises_without_status():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    client = _client(handler)
    with pytest.raises(LearningsAPIError) as exc_info:
        client.retrieve([{"role": "user", "content": "x"}])
    assert exc_info.value.status_code is None
