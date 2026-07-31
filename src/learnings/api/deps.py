"""FastAPI dependencies.

The embedder, backend, and (if configured) judge are process-wide singletons
(created at startup and stored on ``app.state``); a ``LearningManager`` is
cheap and built per request, bound to the ``agent_id`` from the path.
"""

from __future__ import annotations

import os
from functools import lru_cache

from fastapi import Request

from ..backend import VectorStoreBackend
from ..manager import LearningManager
from ..reranker import CrossEncoderReranker
from ..retriever import HybridRetriever


@lru_cache
def get_reranker() -> CrossEncoderReranker:
    # No hardcoded fallback string here on purpose: duplicating the model
    # name in two places let this env var silently pin the OLD default
    # (ms-marco-MiniLM-L-6-v2) even after CrossEncoderReranker's own default
    # was upgraded to mxbai-rerank-base-v1. Deferring to the class default
    # keeps this the single source of truth for which model ships by default.
    model = os.getenv("RERANKER_MODEL")
    return CrossEncoderReranker(model=model) if model else CrossEncoderReranker()


def get_backend(request: Request) -> VectorStoreBackend:
    """The process-wide backend singleton (for cross-agent, agent-less routes)."""
    return request.app.state.backend


def _make_event_recorder(request: Request):
    """Additive analytics side-channel for ``HybridRetriever._touch()``.

    None of this affects ranking or the returned learnings — it only appends
    a row to ``learning_events`` so ``learnings/analytics.py`` can answer
    "retrieval trend"/"recently retrieved" questions that ``hits`` /
    ``last_used_at`` alone cannot (see analytics.py's module docstring).
    Falls back to a no-op if the auth store isn't wired up (e.g. some test
    fixtures construct the app without it).
    """
    auth_store = getattr(request.app.state, "auth_store", None)
    if auth_store is None:
        return None

    def _record(learning) -> None:
        # Best-effort, same principle as curator.py's token-usage recording:
        # analytics is observability, not correctness, and must never sink an
        # otherwise-successful retrieval (e.g. if the learning_events table
        # doesn't exist yet in an environment that hasn't run the Alembic
        # migration in alembic/versions/0001_saas_tenancy_tables.py).
        try:
            auth_store.record_learning_event(
                learning_id=learning.id,
                agent_id=learning.agent_id,
                entity_id=learning.entity_id,
                event_type="retrieved",
            )
        except Exception:
            import logging

            logging.getLogger("learnings.analytics").warning(
                "failed to record learning_event for %s", learning.id, exc_info=True
            )

    return _record


def get_manager(agent_id: str, request: Request) -> LearningManager:
    reranker = get_reranker()
    # Sigmoid [0, 1] scale (CrossEncoderReranker default). 0.52 is the
    # measured sweet spot for mxbai-rerank-base-v1 — see reranker.py for the
    # full comparison against ms-marco-MiniLM-L-6-v2 and BAAI/bge-reranker-base.
    threshold = float(os.getenv("RERANK_THRESHOLD", "0.52"))

    retriever = HybridRetriever(
        backend=request.app.state.backend,
        embedder=request.app.state.embedder,
        reranker=reranker,
        rerank_threshold=threshold,
        event_recorder=_make_event_recorder(request),
    )

    # Opt-in pre-publish gate (see models.Status.pending_approval): looked up
    # from the agents ownership registry, defaulting to False for agent_ids
    # that aren't registered there (e.g. pre-SaaS/self-hosted use, or tests
    # that construct a manager without the auth store wired up) so existing
    # behavior is unchanged unless a customer explicitly opts in.
    require_approval = False
    auth_store = getattr(request.app.state, "auth_store", None)
    if auth_store is not None:
        agent = auth_store.get_agent(agent_id)
        if agent is not None:
            require_approval = agent.require_approval

    return LearningManager(
        agent_id=agent_id,
        backend=request.app.state.backend,
        embedder=request.app.state.embedder,
        # None when no GROQ_API_KEY was configured at startup — retrieval
        # routes never need a judge, so they keep working either way; only
        # /persist requires one (see routes.persist's 503 handling).
        judge=getattr(request.app.state, "judge", None),
        retriever=retriever,
        require_approval=require_approval,
    )
