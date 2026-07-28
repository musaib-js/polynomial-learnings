"""HTTP client layer for adapters (the two-tier deployment).

In the two-tier topology the adapter runs inside the user's thin SDK while the
embedder, judge, and vector store live behind the API on a server we can scale
and load-balance. This module is the seam between them: a small, synchronous
client that mirrors the *agent-facing* API endpoints as plain functions.

Only the two hot-path operations an agent actually needs live here:

* :meth:`LearningClient.retrieve` -> ``POST /v1/agents/{agent_id}/retrieve``
* :meth:`LearningClient.persist`  -> ``POST /v1/agents/{agent_id}/persist``

The management endpoints (approve / disapprove / stats / list / patch / delete)
are deliberately *not* exposed here — those belong to a human review UI, not to
the agent's runtime.

Design rule this file enforces: **one function == one HTTP round-trip.** All the
multi-step work (retrieve neighbours, judge, CRUD) happens server-side inside a
single endpoint, so the thin client never makes the network chatty.

Requires the ``httpx`` dependency (declared under the ``pydantic-ai`` / ``api``
extras via ``httpx``).
"""

from __future__ import annotations

from collections.abc import Sequence

import httpx

from .exceptions import LearningsAPIError
from .models import Learning, Message, PersistResult

_DEFAULT_TIMEOUT = 30.0


def _to_messages(messages: Sequence[Message | dict]) -> list[dict]:
    """Normalise a caller's messages into the JSON shape the API expects.

    Accepts either :class:`Message` instances or raw ``{"role", "content"}``
    dicts, so an adapter can hand over whatever it has without converting.
    """
    out: list[dict] = []
    for m in messages:
        if isinstance(m, Message):
            out.append({"role": m.role, "content": m.content})
        else:
            out.append({"role": m["role"], "content": m["content"]})
    return out


class LearningClient:
    """Thin synchronous client over the learnings API, bound to one agent.

    Synchronous on purpose: adapter tools (e.g. PydanticAI's ``@agent.tool``)
    call these from a threadpool, mirroring how the API's own handlers are sync.

    Pass an existing ``httpx.Client`` via ``client`` to reuse a connection pool
    (or to inject a ``MockTransport`` in tests); otherwise one is created and
    owned by this instance. ``headers`` is merged into every request — the
    natural place for an ``Authorization`` bearer token once the API is
    protected.
    """

    def __init__(
        self,
        agent_id: str,
        base_url: str,
        *,
        timeout: float = _DEFAULT_TIMEOUT,
        headers: dict[str, str] | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self._agent_id = agent_id
        self._prefix = f"/v1/agents/{agent_id}"
        if client is not None:
            self._client = client
            self._owns_client = False
        else:
            self._client = httpx.Client(
                base_url=base_url.rstrip("/"), timeout=timeout, headers=headers
            )
            self._owns_client = True

    # -- context management ------------------------------------------------

    def close(self) -> None:
        """Close the underlying connection pool, if this client owns it."""
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> LearningClient:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- hot-path operations ----------------------------------------------

    def retrieve(
        self,
        messages: Sequence[Message | dict],
        *,
        entity_id: str | None = None,
        limit: int = 5,
    ) -> list[Learning]:
        """Fetch relevant learnings for a conversation snapshot (no LLM call).

        Mirrors ``POST /retrieve``; returns the active learnings the server's
        hybrid retriever considers most relevant, already parsed into
        :class:`Learning` models.
        """
        payload = {
            "messages": _to_messages(messages),
            "entity_id": entity_id,
            "limit": limit,
        }
        data = self._post("/retrieve", payload)
        return [Learning.model_validate(item) for item in data]

    def persist(
        self,
        messages: Sequence[Message | dict],
        *,
        entity_id: str | None = None,
    ) -> PersistResult:
        """Curate a conversation snapshot and persist a learning if warranted.

        Mirrors ``POST /persist``; the server runs the judge and the correct
        create/refine/supersede write, then returns the :class:`PersistResult`.
        A 503 (no judge configured server-side) surfaces as
        :class:`LearningsAPIError` with ``status_code == 503``.
        """
        payload = {
            "messages": _to_messages(messages),
            "entity_id": entity_id,
        }
        data = self._post("/persist", payload)
        return PersistResult.model_validate(data)

    # -- transport ---------------------------------------------------------

    def _post(self, path: str, json: dict) -> object:
        """POST ``json`` to ``{prefix}{path}`` and return decoded JSON.

        Wraps every failure mode — transport errors and non-2xx responses — in
        :class:`LearningsAPIError`, so adapters catch one exception type and
        never see raw ``httpx`` internals.
        """
        url = f"{self._prefix}{path}"
        try:
            response = self._client.post(url, json=json)
        except httpx.HTTPError as exc:  # transport: unreachable, timeout, DNS
            raise LearningsAPIError(f"request to {url} failed: {exc}") from exc

        if response.is_success:
            return response.json()

        # Non-2xx: surface FastAPI's ``{"detail": ...}`` when present.
        detail: str
        try:
            body = response.json()
            detail = body.get("detail", response.text) if isinstance(body, dict) else response.text
        except ValueError:
            detail = response.text
        raise LearningsAPIError(
            f"{url} returned {response.status_code}: {detail}",
            status_code=response.status_code,
        )
