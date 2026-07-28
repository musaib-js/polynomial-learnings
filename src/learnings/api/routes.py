"""API routes.

Handlers are sync (``def``) so FastAPI runs them in its threadpool — the
embedder and psycopg calls are blocking, and this keeps them off the event loop.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ..auth.deps import require_admin, require_agent_ownership
from ..auth.models import AuthPrincipal, User
from ..backend import VectorStoreBackend
from ..manager import LearningManager
from ..models import (
    AgentStats,
    AgentSummary,
    Learning,
    PersistResult,
    Scope,
    TokenUsageStats,
)
from .deps import get_backend, get_manager
from .schemas import (
    LearningsByScope,
    PersistRequest,
    RetrieveRequest,
    UpdateLearningRequest,
)

# No router-level auth dependency: each route declares its own guard, because
# they differ — require_agent_ownership for per-agent routes, require_admin for
# the cross-tenant roster. See learnings/auth/deps.py.
router = APIRouter(prefix="/v1")


@router.get(
    "/agents",
    response_model=list[AgentSummary],
    summary="List every agent the store has seen (platform staff only)",
)
def list_agents(
    backend: VectorStoreBackend = Depends(get_backend),
    _admin: User = Depends(require_admin),
) -> list[AgentSummary]:
    # Cross-tenant roster: admin-gated, since this returns every agent_id
    # ever seen across every organization with no per-tenant scoping.
    # Ordinary customers should use GET /v1/dashboard/agents instead
    # (dashboard_routes.py::list_my_agents), which is scoped to their org.
    return [AgentSummary(**row) for row in backend.list_agents()]


def _require(learning: Learning | None) -> Learning:
    """404 if the learning is missing or belongs to another agent."""
    if learning is None:
        raise HTTPException(status_code=404, detail="learning not found")
    return learning


def _audit(
    request: Request, principal: AuthPrincipal, action: str, target_id: str
) -> None:
    """Best-effort audit trail for learning-management actions.

    Same non-fatal principle as curator.py's token-usage recording:
    observability must never sink an otherwise-successful request. Answers
    AGENT.md's previously-open "no rejection audit trail" question for the
    human-review actions (approve/disapprove/edit/delete).
    """
    auth_store = getattr(request.app.state, "auth_store", None)
    if auth_store is None:
        return
    try:
        auth_store.record_audit_event(
            actor_user_id=principal.user_id if principal else None,
            org_id=principal.org_id if principal else None,
            action=action,
            target_id=target_id,
        )
    except Exception:
        import logging

        logging.getLogger("learnings.audit").warning(
            "failed to record audit event %s for %s", action, target_id, exc_info=True
        )


@router.post(
    "/agents/{agent_id}/retrieve",
    response_model=list[Learning],
    summary="Retrieve relevant learnings for a conversation snapshot",
)
def retrieve(
    agent_id: str,
    req: RetrieveRequest,
    manager: LearningManager = Depends(get_manager),
    _principal: AuthPrincipal = Depends(require_agent_ownership),
) -> list[Learning]:
    return manager.retrieve_for_conversation(
        messages=req.messages, entity_id=req.entity_id, limit=req.limit
    )


@router.post(
    "/agents/{agent_id}/persist",
    response_model=PersistResult,
    summary="Curate a conversation snapshot and persist a durable learning, if warranted",
)
def persist(
    agent_id: str,
    req: PersistRequest,
    manager: LearningManager = Depends(get_manager),
    _principal: AuthPrincipal = Depends(require_agent_ownership),
) -> PersistResult:
    try:
        return manager.persist_from_conversation(
            messages=req.messages, entity_id=req.entity_id
        )
    except ValueError as exc:
        # Raised by LearningManager when no judge is configured for this
        # agent (e.g. GROQ_API_KEY unset) — a server configuration issue,
        # not a bad request.
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get(
    "/agents/{agent_id}/learnings",
    response_model=LearningsByScope,
    summary="List this agent's global learnings and one entity's personal learnings",
)
def list_all_learnings(
    agent_id: str,
    entity_id: str = Query(..., description="Whose personal learnings to include."),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    manager: LearningManager = Depends(get_manager),
    _principal: AuthPrincipal = Depends(require_agent_ownership),
) -> LearningsByScope:
    """Both visible scopes in one round-trip.

    Convenience over calling ``/learnings/personal`` and ``/learnings/global``
    separately — the common case for an agent loading its context before a turn.
    """
    return LearningsByScope(
        personal=manager.list_learnings(
            Scope.personal, entity_id=entity_id, limit=limit, offset=offset
        ),
        global_=manager.list_learnings(Scope.global_, limit=limit, offset=offset),
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
    _principal: AuthPrincipal = Depends(require_agent_ownership),
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
    _principal: AuthPrincipal = Depends(require_agent_ownership),
) -> list[Learning]:
    return manager.list_learnings(Scope.global_, limit=limit, offset=offset)


# -- single-learning management -------------------------------------------
@router.post(
    "/agents/{agent_id}/learnings/{learning_id}/approve",
    response_model=Learning,
    summary="Approve a learning (mark active)",
)
def approve(
    agent_id: str,
    learning_id: str,
    request: Request,
    manager: LearningManager = Depends(get_manager),
    principal: AuthPrincipal = Depends(require_agent_ownership),
) -> Learning:
    result = _require(manager.approve_learning(learning_id))
    _audit(request, principal, "learning.approve", learning_id)
    return result


@router.post(
    "/agents/{agent_id}/learnings/{learning_id}/disapprove",
    response_model=Learning,
    summary="Disapprove a learning (mark rejected)",
)
def disapprove(
    agent_id: str,
    learning_id: str,
    request: Request,
    manager: LearningManager = Depends(get_manager),
    principal: AuthPrincipal = Depends(require_agent_ownership),
) -> Learning:
    result = _require(manager.disapprove_learning(learning_id))
    _audit(request, principal, "learning.disapprove", learning_id)
    return result


@router.patch(
    "/agents/{agent_id}/learnings/{learning_id}",
    response_model=Learning,
    summary="Update editable fields on a learning",
)
def update_learning(
    agent_id: str,
    learning_id: str,
    req: UpdateLearningRequest,
    request: Request,
    manager: LearningManager = Depends(get_manager),
    principal: AuthPrincipal = Depends(require_agent_ownership),
) -> Learning:
    fields = req.model_dump(exclude_unset=True)
    result = _require(manager.update_learning(learning_id, **fields))
    _audit(request, principal, "learning.edit", learning_id)
    return result


@router.delete(
    "/agents/{agent_id}/learnings/{learning_id}",
    response_model=Learning,
    summary="Soft-delete a learning (mark rejected, retained for audit)",
)
def delete_learning(
    agent_id: str,
    learning_id: str,
    request: Request,
    manager: LearningManager = Depends(get_manager),
    principal: AuthPrincipal = Depends(require_agent_ownership),
) -> Learning:
    result = _require(manager.delete_learning(learning_id))
    _audit(request, principal, "learning.delete", learning_id)
    return result


# -- statistics -----------------------------------------------------------
@router.get(
    "/agents/{agent_id}/stats",
    response_model=AgentStats,
    summary="Aggregate statistics for this agent's learnings",
)
def stats(
    agent_id: str,
    top_n: int = Query(5, ge=0, le=50),
    manager: LearningManager = Depends(get_manager),
    _principal: AuthPrincipal = Depends(require_agent_ownership),
) -> AgentStats:
    return manager.stats(top_n=top_n)


# -- token accounting -----------------------------------------------------
@router.get(
    "/agents/{agent_id}/tokens",
    response_model=TokenUsageStats,
    summary="Aggregate token consumption for this agent",
)
def token_usage(
    agent_id: str,
    manager: LearningManager = Depends(get_manager),
    _principal: AuthPrincipal = Depends(require_agent_ownership),
) -> TokenUsageStats:
    return manager.token_stats()
