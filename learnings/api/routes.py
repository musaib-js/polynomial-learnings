"""API routes.

Handlers are sync (``def``) so FastAPI runs them in its threadpool — the
embedder and psycopg calls are blocking, and this keeps them off the event loop.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from ..manager import LearningManager
from ..models import Learning, Scope
from .deps import get_manager
from .schemas import RetrieveRequest

router = APIRouter(prefix="/v1")


@router.post(
    "/agents/{agent_id}/retrieve",
    response_model=list[Learning],
    summary="Retrieve relevant learnings for a conversation snapshot",
)
def retrieve(
    agent_id: str,
    req: RetrieveRequest,
    manager: LearningManager = Depends(get_manager),
) -> list[Learning]:
    return manager.retrieve_for_conversation(
        messages=req.messages, entity_id=req.entity_id, limit=req.limit
    )


@router.get(
    "/agents/{agent_id}/learnings/personal",
    response_model=list[Learning],
    summary="List an entity's personal learnings for this agent",
)
def list_personal(
    agent_id: str,
    entity_id: str = Query(..., description="Whose personal learnings to list."),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    manager: LearningManager = Depends(get_manager),
) -> list[Learning]:
    return manager.list_learnings(
        Scope.personal, entity_id=entity_id, limit=limit, offset=offset
    )


@router.get(
    "/agents/{agent_id}/learnings/global",
    response_model=list[Learning],
    summary="List this agent's global learnings",
)
def list_global(
    agent_id: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    manager: LearningManager = Depends(get_manager),
) -> list[Learning]:
    return manager.list_learnings(Scope.global_, limit=limit, offset=offset)
