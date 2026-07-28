"""PydanticAI adapter.

Registers ``store_learning`` and ``get_learnings`` as agent tools. The host app
supplies an ``entity_id_resolver`` that derives "who this is for" from its own
``RunContext`` — the core never needs to know the host's identity model.

:func:`register_tools_via_api` is the only backend: the tools call a
:class:`~learnings.client.LearningClient` over HTTP, so the agent process
carries no embedder/judge/DB weight — each tool call is one round trip to the
API.

Requires the ``pydantic-ai`` extra.
"""

from __future__ import annotations

from collections.abc import Callable

from ..client import LearningClient
from ..exceptions import LearningsAPIError
from ..models import Message, format_learnings_for_prompt


def register_tools_via_api(
    agent,
    client: LearningClient,
    entity_id_resolver: Callable[[object], str | None],
) -> None:
    """Attach learning tools that reach the store over HTTP via ``client``.

    The tools do no local embedding, judging, or DB work — they hand a
    conversation snapshot to the API and let the server do everything. Each
    tool call is one HTTP request.

    Both tools are message-based to match the API contract: the agent passes a
    few recent conversation turns as ``messages`` (``{"role", "content"}``
    dicts), the server derives the query / candidate learning from them.
    """

    def _to_snapshot(messages: list[dict]) -> list[Message]:
        return [Message(role=m["role"], content=m["content"]) for m in messages]

    @agent.tool
    def store_learning(ctx, messages: list[dict]) -> str:
        """Persist a durable lesson from recent conversation turns, if warranted.

        Pass the last few ``{"role", "content"}`` turns that contain the lesson;
        the server judges whether to store, refine, supersede, or reject.
        """
        entity_id = entity_id_resolver(ctx)
        try:
            result = client.persist(_to_snapshot(messages), entity_id=entity_id)
        except LearningsAPIError as exc:
            return f"could not store learning: {exc}"
        if result.decision == "rejected":
            return f"not stored ({result.verdict.value}): {result.reason or 'not worth keeping'}"
        return f"stored learning {result.learning_id} ({result.verdict.value})"

    @agent.tool
    def get_learnings(ctx, messages: list[dict], limit: int = 5) -> str:
        """Retrieve relevant learnings for the current conversation (no LLM call)."""
        entity_id = entity_id_resolver(ctx)
        try:
            learnings = client.retrieve(
                _to_snapshot(messages), entity_id=entity_id, limit=limit
            )
        except LearningsAPIError as exc:
            return f"could not retrieve learnings: {exc}"
        return format_learnings_for_prompt(learnings)
