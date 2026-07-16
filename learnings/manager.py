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
from .models import Learning, Message, Outcome, PersistResult, Scope, query_from_messages
from .retriever import HybridRetriever


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
            LearningCurator(backend, embedder, judge, self._retriever) if judge else None
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

    def format_for_prompt(self, learnings: list[Learning]) -> str:
        """Render learnings as a concise, applicable block for a system prompt."""
        if not learnings:
            return ""
        lines = ["Relevant learnings from past interactions:"]
        for learning in learnings:
            lines.append(f"- When {learning.context}: {learning.content}")
        return "\n".join(lines)
