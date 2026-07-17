"""Data model for a single learning.

Only ``context`` + ``content`` are embedded; every other field travels as
metadata on the same record, used for isolation, filtering, and ranking.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field


class Scope(str, Enum):
    personal = "personal"
    global_ = "global"


class Outcome(str, Enum):
    positive = "positive"
    negative = "negative"
    neutral = "neutral"


class Status(str, Enum):
    active = "active"
    superseded = "superseded"
    rejected = "rejected"


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Learning(BaseModel):
    """The unit of knowledge stored and retrieved by the library."""

    id: str = Field(default_factory=lambda: str(uuid4()))

    # Isolation boundary.
    agent_id: str
    entity_id: str | None = None  # None for global learnings
    scope: Scope = Scope.personal

    # Lifecycle.
    status: Status = Status.active
    supersedes: str | None = None

    # Embedded semantic content.
    context: str
    content: str

    # Payload detail (for the model's own understanding).
    outcome: Outcome = Outcome.neutral
    reason: str | None = None
    original_output: str | None = None
    corrected_output: str | None = None
    category: str | None = None
    tags: list[str] = Field(default_factory=list)

    # Ranking / curation signals.
    created_at: datetime = Field(default_factory=_now)
    last_used_at: datetime | None = None
    hits: int = 0

    def embedding_text(self) -> str:
        """The text that gets embedded and full-text indexed."""
        return f"{self.context} {self.content}"


class Message(BaseModel):
    """One turn of a conversation snapshot handed to the retrieval API."""

    role: str
    content: str


def query_from_messages(messages: list[Message]) -> str:
    """Flatten a conversation snapshot into a single search query.

    The base version uses every provided message (no cap yet — message
    limiting is deferred). Empty contents are dropped.
    """
    return " ".join(m.content for m in messages if m.content)


class MostUsedLearning(BaseModel):
    """A compact reference to a frequently retrieved learning (for stats)."""

    id: str
    context: str
    content: str
    hits: int


class AgentStats(BaseModel):
    """Aggregate statistics for a single agent's stored learnings."""

    agent_id: str
    total: int
    by_status: dict[str, int]  # active / superseded / rejected
    by_scope: dict[str, int]  # personal / global
    total_hits: int
    avg_hits: float
    distinct_entities: int
    last_used_at: datetime | None = None
    last_created_at: datetime | None = None
    most_used: list[MostUsedLearning] = Field(default_factory=list)
