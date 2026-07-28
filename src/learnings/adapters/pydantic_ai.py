"""PydanticAI adapter.

Registers ``store_learning`` and ``get_learnings`` as agent tools. The host app
supplies an ``entity_id_resolver`` that derives "who this is for" from its own
``RunContext`` — the core never needs to know the host's identity model.

Two backends are supported for where the tools send their work:

* :func:`register_tools`  — in-process, calls a :class:`LearningManager`
  directly. For single-service deployments.
* :func:`register_tools_via_api` — the two-tier path: calls a
  :class:`~learnings.client.LearningClient` over HTTP, so the thin SDK carries
  no embedder/judge/DB weight. This is the layer that sits on top of the API.

Requires the ``pydantic-ai`` extra.
"""

from __future__ import annotations

from typing import Callable

from ..client import LearningClient
from ..exceptions import LearningsAPIError
from ..manager import LearningManager
from ..models import Message, Outcome, Scope


def register_tools(
    agent,
    manager: LearningManager,
    entity_id_resolver: Callable[[object], str | None],
) -> None:
    """Attach learning tools to a PydanticAI ``agent`` (in-process manager).

    ``entity_id_resolver`` takes the tool's ``RunContext`` and returns the
    entity id for the current run (or ``None`` for a global-only context).
    """

    @agent.tool
    def store_learning(
        ctx,
        context: str,
        content: str,
        outcome: str = "neutral",
        is_global: bool = False,
    ) -> str:
        """Persist a durable lesson learned from this interaction."""
        entity_id = entity_id_resolver(ctx)
        scope = Scope.global_ if is_global else Scope.personal
        learning = manager.record(
            context=context,
            content=content,
            scope=scope,
            entity_id=entity_id,
            outcome=Outcome(outcome),
        )
        return f"stored learning {learning.id}"

    @agent.tool
    def get_learnings(ctx, query: str, limit: int = 5) -> str:
        """Retrieve relevant learnings from past interactions."""
        entity_id = entity_id_resolver(ctx)
        learnings = manager.retrieve(query=query, entity_id=entity_id, limit=limit)
        return manager.format_for_prompt(learnings)


def register_tools_via_api(
    agent,
    client: LearningClient,
    entity_id_resolver: Callable[[object], str | None],
) -> None:
    """Attach learning tools that reach the store over HTTP via ``client``.

    The two-tier equivalent of :func:`register_tools`: the tools do no local
    embedding, judging, or DB work — they hand a conversation snapshot to the
    API and let the server do everything. Each tool call is one HTTP request.

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
        return _format_for_prompt(learnings)


def _format_for_prompt(learnings) -> str:
    """Render learnings as a concise, applicable block for a system prompt.

    Mirrors ``LearningManager.format_for_prompt`` so the API-backed tools
    produce identical output to the in-process ones.
    """
    if not learnings:
        return ""
    lines = ["Relevant learnings from past interactions:"]
    for learning in learnings:
        lines.append(f"- When {learning.context}: {learning.content}")
    return "\n".join(lines)
