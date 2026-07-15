"""FastAPI dependencies.

The embedder and backend are process-wide singletons (created at startup and
stored on ``app.state``); a ``LearningManager`` is cheap and built per request,
bound to the ``agent_id`` from the path.
"""

from __future__ import annotations

from fastapi import Request

from ..manager import LearningManager


def get_manager(agent_id: str, request: Request) -> LearningManager:
    return LearningManager(
        agent_id=agent_id,
        backend=request.app.state.backend,
        embedder=request.app.state.embedder,
    )
