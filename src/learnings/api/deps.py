"""FastAPI dependencies.

The embedder, backend, and (if configured) judge are process-wide singletons
(created at startup and stored on ``app.state``); a ``LearningManager`` is
cheap and built per request, bound to the ``agent_id`` from the path.
"""

from __future__ import annotations

import os
from functools import lru_cache

from fastapi import Depends, HTTPException, Request
from fastapi.security import APIKeyHeader

from ..backend import VectorStoreBackend
from ..manager import LearningManager
from ..reranker import CrossEncoderReranker
from ..retriever import HybridRetriever

_authorization_header = APIKeyHeader(name="Authorization", auto_error=False)


def require_api_key(
    request: Request,
    authorization: str | None = Depends(_authorization_header),
) -> None:
    """Enforce ``Authorization: Bearer <key>`` when ``LEARNINGS_API_KEY`` is set.

    No-op when the server has no key configured, mirroring the optional
    ``GROQ_API_KEY``/judge pattern below — local/dev deployments keep working
    without it, but any real deployment should set one.
    """
    expected = getattr(request.app.state, "api_key", None)
    if expected is None:
        return
    if authorization != f"Bearer {expected}":
        raise HTTPException(status_code=401, detail="invalid or missing API key")


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
    )

    return LearningManager(
        agent_id=agent_id,
        backend=request.app.state.backend,
        embedder=request.app.state.embedder,
        # None when no GROQ_API_KEY was configured at startup — retrieval
        # routes never need a judge, so they keep working either way; only
        # /persist requires one (see routes.persist's 503 handling).
        judge=getattr(request.app.state, "judge", None),
        retriever=retriever,
    )
