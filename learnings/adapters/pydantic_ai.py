"""PydanticAI adapter.

Registers ``store_learning`` and ``get_learnings`` as agent tools. The host app
supplies an ``entity_id_resolver`` that derives "who this is for" from its own
``RunContext`` — the core never needs to know the host's identity model.

Requires the ``pydantic-ai`` extra.
"""

from __future__ import annotations

from typing import Callable

from ..manager import LearningManager
from ..models import Outcome, Scope


def register_tools(
    agent,
    manager: LearningManager,
    entity_id_resolver: Callable[[object], str | None],
) -> None:
    """Attach learning tools to a PydanticAI ``agent``.

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
