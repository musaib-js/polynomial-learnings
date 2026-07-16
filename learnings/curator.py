"""Curated persistence — the Persist Learning API's decision engine (SDD §6).

``LearningCurator`` is what ``LearningManager.record``'s docstring has been
pointing at since the raw ingestion path was built: it wraps a conversation
in the two SDD judgements (novelty, then worth-keeping), delegated to a
pluggable ``Judge``, and turns the verdict into the correct database write —
new / same / refine / contradict.

Retrieval is a real, external dependency here (``HybridRetriever``, owned by
another part of the codebase) — this module never bypasses it to query the
backend directly, and never touches ``learnings/retriever.py``.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from .backend import VectorStoreBackend
from .embedder import Embedder
from .exceptions import CurationError
from .judge import Judge
from .models import (
    GeneratedLearning,
    JudgeVerdict,
    Learning,
    Message,
    PersistResult,
    Scope,
    Status,
    Verdict,
    query_from_messages,
)
from .prompts import build_judge_prompt
from .retriever import HybridRetriever

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class LearningCurator:
    """Runs the novelty + worth-keeping checks before anything is persisted.

    Owns the store / touch / refine / supersede / reject decision — the
    ``LearningCurator`` from the SDD's architecture (§4, §9).
    """

    def __init__(
        self,
        backend: VectorStoreBackend,
        embedder: Embedder,
        judge: Judge,
        retriever: HybridRetriever,
        top_k: int = 5,
        max_messages: int = 4,
    ):
        self._backend = backend
        self._embedder = embedder
        self._judge = judge
        self._retriever = retriever
        self._top_k = top_k
        self._max_messages = max_messages

    def persist(
        self,
        agent_id: str,
        messages: list[Message],
        entity_id: str | None = None,
    ) -> PersistResult:
        """Decide whether ``messages`` contains a durable lesson and, if so,
        persist it (new / refine / supersede) or discard it as a duplicate.

        Only ``role == "user"`` messages are considered, per the brief — no
        assistant turns feed the judge. Empty input is a reject.
        """
        user_messages = [m for m in messages if m.role == "user"]
        if self._max_messages > 0:
            user_messages = user_messages[-self._max_messages :]
        if not user_messages:
            logger.info("rejected: no user messages in conversation")
            return PersistResult(
                decision="rejected",
                verdict=Verdict.reject,
                reason="no user messages in conversation",
            )

        # Real hybrid retrieval (semantic + keyword + RRF) — the retrieval
        # engine's actual output, not a stub. See module docstring.
        neighbours = self._retriever.retrieve(
            agent_id=agent_id,
            query=query_from_messages(user_messages),
            entity_id=entity_id,
            limit=self._top_k,
        )
        by_id = {learning.id: learning for learning in neighbours}

        prompt = build_judge_prompt(user_messages, neighbours)
        verdict = self._judge.evaluate(prompt)

        try:
            return self._dispatch(agent_id, entity_id, verdict, by_id)
        except CurationError as exc:
            logger.info("rejected: %s", exc)
            return PersistResult(decision="rejected", verdict=Verdict.reject, reason=str(exc))

    # -- dispatch -----------------------------------------------------------

    def _dispatch(
        self,
        agent_id: str,
        request_entity_id: str | None,
        verdict: JudgeVerdict,
        by_id: dict[str, Learning],
    ) -> PersistResult:
        if verdict.verdict is Verdict.reject:
            logger.info("rejected: %s", verdict.reason)
            return PersistResult(
                decision="rejected", verdict=Verdict.reject, reason=verdict.reason
            )

        if verdict.verdict is Verdict.same:
            existing = by_id.get(verdict.related_learning_id)
            if existing is None:
                raise CurationError(
                    "judge verdict 'same' referenced a learning id not among "
                    f"the retrieved neighbours: {verdict.related_learning_id!r}"
                )
            self._touch(existing)
            return PersistResult(decision="persisted", verdict=Verdict.same, learning_id=existing.id)

        if verdict.verdict is Verdict.refine:
            existing = by_id.get(verdict.related_learning_id)
            if existing is None:
                logger.warning(
                    "judge verdict 'refine' referenced an unknown learning id %r; "
                    "treating as a new learning instead",
                    verdict.related_learning_id,
                )
                return self._persist_new(agent_id, request_entity_id, verdict.learning)
            return self._persist_refine(existing, verdict.learning, request_entity_id)

        if verdict.verdict is Verdict.contradict:
            existing = by_id.get(verdict.related_learning_id)
            if existing is None:
                logger.warning(
                    "judge verdict 'contradict' referenced an unknown learning id %r; "
                    "treating as a new learning instead",
                    verdict.related_learning_id,
                )
                return self._persist_new(agent_id, request_entity_id, verdict.learning)
            return self._persist_contradict(agent_id, existing, verdict.learning, request_entity_id)

        # verdict.verdict is Verdict.new
        return self._persist_new(agent_id, request_entity_id, verdict.learning)

    # -- scope / isolation ----------------------------------------------

    def _resolve_entity_id(
        self, generated: GeneratedLearning, request_entity_id: str | None
    ) -> str | None:
        """The judge decides ``scope``; the curator resolves ``entity_id``
        from that decision deterministically — never left to the LLM.

        global  -> entity_id is always None, regardless of the request.
        personal -> entity_id must come from the request; missing it is a
                    reject, not a silent global write (isolation stays
                    structural, per the SDD, not dependent on the judge
                    getting this right).
        """
        if generated.scope is Scope.global_:
            return None
        if not request_entity_id:
            raise CurationError(
                "judge produced a personal-scope learning but no entity_id "
                "was supplied for this conversation"
            )
        return request_entity_id

    # -- writes -----------------------------------------------------------

    def _embed_and_upsert(self, learning: Learning) -> None:
        embedding = self._embedder.embed([learning.embedding_text()])[0]
        self._backend.upsert(learning, embedding)

    def _touch(self, existing: Learning) -> None:
        self._backend.update(existing.id, hits=existing.hits + 1, last_used_at=_now())

    def _persist_new(
        self,
        agent_id: str,
        request_entity_id: str | None,
        generated: GeneratedLearning,
        verdict_type: Verdict = Verdict.new,
    ) -> PersistResult:
        entity_id = self._resolve_entity_id(generated, request_entity_id)
        learning = Learning(
            agent_id=agent_id,
            entity_id=entity_id,
            scope=generated.scope,
            context=generated.context,
            content=generated.content,
            outcome=generated.outcome,
            reason=generated.reason,
            original_output=generated.original_output,
            corrected_output=generated.corrected_output,
            category=generated.category,
            tags=generated.tags,
        )
        self._embed_and_upsert(learning)
        return PersistResult(decision="persisted", verdict=verdict_type, learning_id=learning.id)

    def _persist_refine(
        self,
        existing: Learning,
        generated: GeneratedLearning,
        request_entity_id: str | None,
    ) -> PersistResult:
        entity_id = self._resolve_entity_id(generated, request_entity_id)
        # model_copy preserves every field we don't override — critically
        # `id`, `created_at`, `hits`, `last_used_at`, `agent_id`, `supersedes`.
        # Re-upserting a freshly-constructed Learning here would silently
        # reset hits to 0 and last_used_at to NULL (upsert's ON CONFLICT DO
        # UPDATE writes exactly what we hand it); model_copy is the fix.
        merged = existing.model_copy(
            update={
                "scope": generated.scope,
                "entity_id": entity_id,
                "context": generated.context,
                "content": generated.content,
                "outcome": generated.outcome,
                "reason": generated.reason,
                "original_output": generated.original_output,
                "corrected_output": generated.corrected_output,
                "category": generated.category,
                "tags": generated.tags,
            }
        )
        self._embed_and_upsert(merged)
        return PersistResult(decision="persisted", verdict=Verdict.refine, learning_id=merged.id)

    def _persist_contradict(
        self,
        agent_id: str,
        existing: Learning,
        generated: GeneratedLearning,
        request_entity_id: str | None,
    ) -> PersistResult:
        entity_id = self._resolve_entity_id(generated, request_entity_id)
        self._backend.update(existing.id, status=Status.superseded.value)
        new_learning = Learning(
            agent_id=agent_id,
            entity_id=entity_id,
            scope=generated.scope,
            supersedes=existing.id,
            context=generated.context,
            content=generated.content,
            outcome=generated.outcome,
            reason=generated.reason,
            original_output=generated.original_output,
            corrected_output=generated.corrected_output,
            category=generated.category,
            tags=generated.tags,
        )
        self._embed_and_upsert(new_learning)
        return PersistResult(
            decision="persisted",
            verdict=Verdict.contradict,
            learning_id=new_learning.id,
            superseded_id=existing.id,
        )
