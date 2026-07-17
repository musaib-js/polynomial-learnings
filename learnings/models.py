"""Data model for a single learning.

Only ``context`` + ``content`` are embedded; every other field travels as
metadata on the same record, used for isolation, filtering, and ranking.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator


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


# -- Persist Learning API (curation) -------------------------------------
#
# These models describe the Judge's decision and its effect, per SDD §6/§8.
# The Judge itself decides `scope` (see GeneratedLearning) as well as the
# novelty verdict; `entity_id` is never in its hands — it is resolved by the
# curator from the caller's request, which is the structural half of the
# isolation guarantee (a `global` verdict always forces entity_id to None;
# a `personal` verdict always uses the caller-supplied entity_id).


class Verdict(str, Enum):
    """The Judge's classification of a candidate learning.

    ``reject``     — not worth persisting (trivial, unsafe, one-off).
    ``new``        — worth persisting, no close match among retrieved neighbours.
    ``same``       — restates an existing active learning; discarded, existing touched.
    ``refine``     — same lesson family as an existing learning; merge into it.
    ``contradict`` — conflicts with an existing learning; supersede it.
    """

    reject = "reject"
    new = "new"
    same = "same"
    refine = "refine"
    contradict = "contradict"


class GeneratedLearning(BaseModel):
    """The learning content authored by the Judge when it decides to persist.

    Mirrors the persistable fields of :class:`Learning`, minus everything the
    curator (not the LLM) is responsible for: ``id``, ``agent_id``,
    ``entity_id``, ``status``, ``supersedes``, and the ranking/timestamp
    signals. ``scope`` is included because the Judge decides it.
    """

    context: str
    content: str
    outcome: Outcome = Outcome.neutral
    scope: Scope = Scope.personal
    reason: str | None = None
    original_output: str | None = None
    corrected_output: str | None = None
    category: str | None = None
    tags: list[str] = Field(default_factory=list)


class JudgeVerdict(BaseModel):
    """The Judge's full structured output for one persist attempt."""

    verdict: Verdict
    reason: str | None = None
    related_learning_id: str | None = None
    learning: GeneratedLearning | None = None

    @model_validator(mode="after")
    def _check_verdict_invariants(self) -> "JudgeVerdict":
        if self.verdict is Verdict.reject and self.learning is not None:
            raise ValueError("a rejected verdict must not carry a generated learning")
        if self.verdict in (Verdict.same, Verdict.refine, Verdict.contradict):
            if not self.related_learning_id:
                raise ValueError(
                    f"verdict={self.verdict.value!r} requires related_learning_id"
                )
        if self.verdict in (Verdict.new, Verdict.refine, Verdict.contradict):
            if self.learning is None:
                raise ValueError(
                    f"verdict={self.verdict.value!r} requires a generated learning"
                )
        return self


class PersistResult(BaseModel):
    """What the Persist Learning API returns for one conversation."""

    decision: Literal["persisted", "rejected"]
    verdict: Verdict
    learning_id: str | None = None
    superseded_id: str | None = None
    reason: str | None = None

    @model_validator(mode="after")
    def _check_decision_invariants(self) -> "PersistResult":
        if self.decision == "rejected":
            if self.learning_id is not None or self.superseded_id is not None:
                raise ValueError("a rejected result must not carry learning ids")
        else:
            if self.learning_id is None:
                raise ValueError("a persisted result requires learning_id")
            if (
                self.superseded_id is not None
                and self.verdict is not Verdict.contradict
            ):
                raise ValueError("superseded_id is only set for verdict=contradict")
        return self
