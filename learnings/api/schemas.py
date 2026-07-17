"""Request/response schemas for the API.

Responses reuse the core ``Learning`` model directly, so the API and the SDK
share one shape.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..models import Message, Outcome


class RetrieveRequest(BaseModel):
    """Body of ``POST /v1/agents/{agent_id}/retrieve``."""

    messages: list[Message] = Field(
        ..., description="Conversation snapshot to fetch relevant learnings for."
    )
    entity_id: str | None = Field(
        default=None,
        description="Whom the retrieval is for; unlocks that entity's personal learnings.",
    )
    limit: int = Field(default=5, ge=1, le=50)


class UpdateLearningRequest(BaseModel):
    """Body of ``PATCH /v1/agents/{agent_id}/learnings/{learning_id}``.

    All fields optional; only those provided are changed. Editing ``context`` or
    ``content`` triggers a re-embed on the server.
    """

    context: str | None = None
    content: str | None = None
    category: str | None = None
    tags: list[str] | None = None
    reason: str | None = None
    outcome: Outcome | None = None


class PersistRequest(BaseModel):
    """Body of ``POST /v1/agents/{agent_id}/persist``."""

    messages: list[Message] = Field(
        ...,
        description=(
            "Conversation snapshot to curate. Only role='user' messages are "
            "considered by the judge."
        ),
    )
    entity_id: str | None = Field(
        default=None,
        description="Whom a personal-scope learning would belong to, if the judge decides one.",
    )
