"""Single entry point for the library.

The manager covers the vector *ingestion*, *retrieval*, and *curated persist*
paths:

* ``record``  — embed a candidate and upsert it. Raw write path, no curation.
* ``retrieve`` / ``retrieve_for_conversation`` — hybrid relevance search via
  ``HybridRetriever``.
* ``persist_from_conversation`` — the curated write path (SDD §6): asks a
  ``Judge`` whether a conversation contains a durable lesson, and if so
  persists it (new / refine / supersede) via ``LearningCurator``.
* ``format_for_prompt`` — render retrieved learnings as compact prompt context.

``promote_to_global`` is intentionally left out of scope for now.
"""

from __future__ import annotations

from .backend import SearchFilter, VectorStoreBackend
from .curator import LearningCurator
from .embedder import Embedder
from .judge import Judge
from .models import (
    AgentStats,
    Learning,
    Message,
    MostUsedLearning,
    OperationTokenTotals,
    Outcome,
    PersistResult,
    Scope,
    Status,
    TokenUsageStats,
    format_learnings_for_prompt,
    query_from_messages,
)
from .retriever import HybridRetriever

# Fields a caller may patch via ``update_learning``. Isolation/lifecycle columns
# (agent_id, entity_id, scope, id, created_at, hits) are deliberately excluded.
_EDITABLE_FIELDS = ("context", "content", "category", "tags", "reason", "outcome")


class LearningManager:
    def __init__(
        self,
        agent_id: str,
        backend: VectorStoreBackend,
        embedder: Embedder,
        retriever: HybridRetriever | None = None,
        judge: Judge | None = None,
        curator: LearningCurator | None = None,
    ):
        self._agent_id = agent_id
        self._backend = backend
        self._embedder = embedder
        self._retriever = retriever or HybridRetriever(backend, embedder)
        self._judge = judge
        # A curator needs a judge to do anything useful; only build one
        # (or accept a caller-supplied one) when a judge is actually
        # available, so retrieval-only managers (e.g. the existing /retrieve
        # API route) keep working with zero curation overhead.
        self._curator = curator or (
            LearningCurator(backend, embedder, judge, self._retriever)
            if judge
            else None
        )

    def record(
        self,
        context: str,
        content: str,
        scope: Scope = Scope.personal,
        entity_id: str | None = None,
        outcome: Outcome = Outcome.neutral,
        **fields,
    ) -> Learning:
        """Ingest a learning: embed its semantic content and store it.

        NOTE: curation (novelty + worth-keeping checks) is not yet applied —
        this is the raw write path. When the curator lands, it wraps this method.
        """
        if scope is Scope.personal and entity_id is None:
            raise ValueError("personal learnings require an entity_id")

        learning = Learning(
            agent_id=self._agent_id,
            entity_id=entity_id,
            scope=scope,
            context=context,
            content=content,
            outcome=outcome,
            **fields,
        )
        embedding = self._embedder.embed([learning.embedding_text()])[0]
        self._backend.upsert(learning, embedding)
        # Mark that this agent now has learnings, so the curated store path can
        # skip the neighbour search only when the agent is genuinely empty.
        self._backend.set_agent_has_learnings(self._agent_id, True)
        return learning

    def retrieve(
        self,
        query: str,
        entity_id: str | None = None,
        limit: int = 5,
    ) -> list[Learning]:
        return self._retriever.retrieve(
            agent_id=self._agent_id,
            query=query,
            entity_id=entity_id,
            limit=limit,
        )

    def retrieve_for_conversation(
        self,
        messages: list[Message],
        entity_id: str | None = None,
        limit: int = 5,
    ) -> list[Learning]:
        """Retrieve relevant learnings from a conversation snapshot.

        Flattens the messages into a single query, then runs hybrid retrieval.
        This is the read path behind the ``/retrieve`` API endpoint.
        """
        return self.retrieve(
            query=query_from_messages(messages),
            entity_id=entity_id,
            limit=limit,
        )

    def persist_from_conversation(
        self,
        messages: list[Message],
        entity_id: str | None = None,
    ) -> PersistResult:
        """Curated write path: decide whether ``messages`` contains a durable
        lesson and, if so, persist it (SDD §6 — novelty then worth-keeping).

        Requires a ``judge`` (or ``curator``) to have been supplied at
        construction time; raises otherwise, since there is nothing to
        curate with.
        """
        if self._curator is None:
            raise ValueError(
                "persist_from_conversation requires a judge (or curator) to "
                "be supplied to LearningManager — this manager was built "
                "retrieval-only"
            )
        return self._curator.persist(self._agent_id, messages, entity_id=entity_id)

    def list_learnings(
        self,
        scope: Scope,
        entity_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Learning]:
        """List this agent's active learnings for a single scope.

        Powers the "get personal / global learnings" endpoints. Personal
        listing requires an ``entity_id``.
        """
        if scope is Scope.personal and entity_id is None:
            raise ValueError("personal listing requires an entity_id")
        flt = SearchFilter(
            agent_id=self._agent_id,
            scope=scope.value,
            entity_id=entity_id,
            status="active",
        )
        return self._backend.list(flt, limit, offset)

    # -- single-learning operations --------------------------------------
    def get_learning(self, learning_id: str) -> Learning | None:
        """Fetch one of *this agent's* learnings, or ``None`` if not found.

        Enforces isolation: a learning belonging to another agent reads as
        missing, so callers can safely 404 on ``None``.
        """
        learning = self._backend.get(learning_id)
        if learning is None or learning.agent_id != self._agent_id:
            return None
        return learning

    def _set_status(self, learning_id: str, status: Status) -> Learning | None:
        learning = self.get_learning(learning_id)
        if learning is None:
            return None
        self._backend.update(learning_id, status=status.value)
        learning.status = status
        return learning

    def approve_learning(self, learning_id: str) -> Learning | None:
        """Approve a learning: mark it ``active`` so retrieval can surface it."""
        return self._set_status(learning_id, Status.active)

    def disapprove_learning(self, learning_id: str) -> Learning | None:
        """Disapprove a learning: mark it ``rejected`` (kept for audit)."""
        return self._set_status(learning_id, Status.rejected)

    def delete_learning(self, learning_id: str) -> Learning | None:
        """Soft-delete: mark ``rejected`` and retain the row for audit.

        Per the retention policy, rows are never hard-deleted here; superseded/
        rejected records age out to long-term storage separately.
        """
        return self._set_status(learning_id, Status.rejected)

    def update_learning(self, learning_id: str, **fields) -> Learning | None:
        """Patch editable fields on one of this agent's learnings.

        Only ``_EDITABLE_FIELDS`` may be changed. If ``context`` or ``content``
        changes, the learning is re-embedded so its vector stays consistent with
        its text (the ``search_tsv`` full-text column updates automatically).
        """
        learning = self.get_learning(learning_id)
        if learning is None:
            return None

        unknown = set(fields) - set(_EDITABLE_FIELDS)
        if unknown:
            raise ValueError(f"cannot update fields: {sorted(unknown)}")

        text_changed = False
        for key, value in fields.items():
            if value is None:
                continue
            if key == "outcome" and not isinstance(value, Outcome):
                value = Outcome(value)
            setattr(learning, key, value)
            if key in ("context", "content"):
                text_changed = True

        if text_changed:
            # Re-embed and upsert so the stored vector matches the new text.
            embedding = self._embedder.embed([learning.embedding_text()])[0]
            self._backend.upsert(learning, embedding)
        else:
            self._backend.update(
                learning_id,
                category=learning.category,
                tags=learning.tags,
                reason=learning.reason,
                outcome=learning.outcome.value,
            )
        return learning

    def stats(self, top_n: int = 5) -> AgentStats:
        """Aggregate statistics for this agent's learnings."""
        raw = self._backend.stats(self._agent_id, top_n=top_n)
        return AgentStats(
            agent_id=self._agent_id,
            total=raw["total"],
            by_status=raw["by_status"],
            by_scope=raw["by_scope"],
            total_hits=raw["total_hits"],
            avg_hits=raw["avg_hits"],
            distinct_entities=raw["distinct_entities"],
            last_used_at=raw["last_used_at"],
            last_created_at=raw["last_created_at"],
            most_used=[MostUsedLearning(**m) for m in raw["most_used"]],
        )

    def token_stats(self) -> TokenUsageStats:
        """Aggregate token consumption for this agent (cost accounting)."""
        raw = self._backend.token_usage_stats(self._agent_id)
        return TokenUsageStats(
            agent_id=self._agent_id,
            total_calls=raw["total_calls"],
            prompt_tokens=raw["prompt_tokens"],
            completion_tokens=raw["completion_tokens"],
            total_tokens=raw["total_tokens"],
            by_operation=[OperationTokenTotals(**op) for op in raw["by_operation"]],
            by_model=raw["by_model"],
        )

    def format_for_prompt(self, learnings: list[Learning]) -> str:
        """Render learnings as a concise, applicable block for a system prompt."""
        return format_learnings_for_prompt(learnings)
