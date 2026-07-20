"""FastAPI dependencies.

The embedder, backend, and (if configured) judge are process-wide singletons
(created at startup and stored on ``app.state``); a ``LearningManager`` is
cheap and built per request, bound to the ``agent_id`` from the path.
"""

from __future__ import annotations

import os
from functools import lru_cache

from fastapi import Request

from ..manager import LearningManager
from ..reranker import CrossEncoderReranker
from ..retriever import HybridRetriever


@lru_cache()
def get_reranker() -> CrossEncoderReranker:
    # No hardcoded fallback string here on purpose: duplicating the model
    # name in two places let this env var silently pin the OLD default
    # (ms-marco-MiniLM-L-6-v2) even after CrossEncoderReranker's own default
    # was upgraded to mxbai-rerank-base-v1. Deferring to the class default
    # keeps this the single source of truth for which model ships by default.
    model = os.getenv("RERANKER_MODEL")
    return CrossEncoderReranker(model=model) if model else CrossEncoderReranker()


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
