"""Single entry point for the library.

For this deliverable the manager covers the vector *ingestion* and *retrieval*
paths only:

* ``record``  — embed a candidate and upsert it (the future curation gate,
  §6, slots in right here without changing callers).
* ``retrieve`` — hybrid relevance search via ``HybridRetriever``.
* ``format_for_prompt`` — render retrieved learnings as compact prompt context.

``promote_to_global`` is intentionally left out of scope for now.
"""

from __future__ import annotations

from .backend import VectorStoreBackend
from .embedder import Embedder
from .models import Learning, Outcome, Scope
from .retriever import HybridRetriever


class LearningManager:
    def __init__(
        self,
        agent_id: str,
        backend: VectorStoreBackend,
        embedder: Embedder,
        retriever: HybridRetriever | None = None,
    ):
        self._agent_id = agent_id
        self._backend = backend
        self._embedder = embedder
        self._retriever = retriever or HybridRetriever(backend, embedder)

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

    def format_for_prompt(self, learnings: list[Learning]) -> str:
        """Render learnings as a concise, applicable block for a system prompt."""
        if not learnings:
            return ""
        lines = ["Relevant learnings from past interactions:"]
        for learning in learnings:
            lines.append(f"- When {learning.context}: {learning.content}")
        return "\n".join(lines)
