"""FastAPI dependencies.

The embedder, backend, and (if configured) judge are process-wide singletons
(created at startup and stored on ``app.state``); a ``LearningManager`` is
cheap and built per request, bound to the ``agent_id`` from the path.
"""

from __future__ import annotations

from fastapi import Request

from ..backend import VectorStoreBackend
from ..manager import LearningManager


def get_backend(request: Request) -> VectorStoreBackend:
    """The process-wide backend singleton (for cross-agent, agent-less routes)."""
    return request.app.state.backend


def get_manager(agent_id: str, request: Request) -> LearningManager:
    return LearningManager(
        agent_id=agent_id,
        backend=request.app.state.backend,
        embedder=request.app.state.embedder,
        # None when no GROQ_API_KEY was configured at startup — retrieval
        # routes never need a judge, so they keep working either way; only
        # /persist requires one (see routes.persist's 503 handling).
        judge=getattr(request.app.state, "judge", None),
    )
