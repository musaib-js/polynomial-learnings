"""``/v1/dashboard/*`` — JWT-authenticated control-plane API for the SPA.

Distinct from the existing ``/v1/agents/...`` agent-runtime API (API-key
authenticated, unchanged route shapes — see ``routes.py``). Everything here
is scoped to "my organization" (resolved from the caller's JWT), never to an
arbitrary ``agent_id`` supplied without an ownership check.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ..analytics import learnings_growth, usage_trends
from ..auth.deps import get_auth_store, get_current_principal, require_admin
from ..auth.models import AuthPrincipal, User
from ..auth.security import generate_api_key
from ..auth.store import AuthStore
from ..backend import VectorStoreBackend
from .auth_schemas import (
    AgentResponse,
    ApiKeyCreatedResponse,
    ApiKeyResponse,
    CreateAgentRequest,
    CreateApiKeyRequest,
    UpdateAgentRequest,
)

router = APIRouter(prefix="/v1/dashboard", tags=["dashboard"])


def _iso(dt) -> str | None:
    return dt.isoformat() if dt is not None else None


# -- API keys -----------------------------------------------------------------


@router.get(
    "/api-keys", response_model=list[ApiKeyResponse], summary="List my org's API keys"
)
def list_api_keys(
    request: Request, principal: AuthPrincipal = Depends(get_current_principal)
) -> list[ApiKeyResponse]:
    store: AuthStore = get_auth_store(request)
    return [
        ApiKeyResponse(
            id=k.id,
            name=k.name,
            key_prefix=k.key_prefix,
            created_at=_iso(k.created_at),
            last_used_at=_iso(k.last_used_at),
            expires_at=_iso(k.expires_at),
            revoked_at=_iso(k.revoked_at),
        )
        for k in store.list_api_keys(principal.org_id)
    ]


@router.post(
    "/api-keys",
    response_model=ApiKeyCreatedResponse,
    summary="Create an API key (raw key shown once)",
)
def create_api_key(
    req: CreateApiKeyRequest,
    request: Request,
    principal: AuthPrincipal = Depends(get_current_principal),
) -> ApiKeyCreatedResponse:
    store: AuthStore = get_auth_store(request)
    raw_key, key_prefix, key_hash = generate_api_key()
    record = store.create_api_key(
        org_id=principal.org_id,
        created_by=principal.user_id,
        name=req.name,
        key_prefix=key_prefix,
        key_hash=key_hash,
    )
    store.record_audit_event(
        actor_user_id=principal.user_id,
        org_id=principal.org_id,
        action="api_key.create",
        target_id=record.id,
    )
    return ApiKeyCreatedResponse(
        id=record.id,
        name=record.name,
        key_prefix=record.key_prefix,
        raw_key=raw_key,
        created_at=_iso(record.created_at),
    )


def _require_owned_key(store: AuthStore, key_id: str, org_id: str):
    record = store.get_api_key(key_id)
    if record is None or record.org_id != org_id:
        raise HTTPException(status_code=404, detail="api key not found")
    return record


@router.post(
    "/api-keys/{key_id}/revoke",
    response_model=ApiKeyResponse,
    summary="Revoke an API key",
)
def revoke_api_key(
    key_id: str,
    request: Request,
    principal: AuthPrincipal = Depends(get_current_principal),
) -> ApiKeyResponse:
    store: AuthStore = get_auth_store(request)
    _require_owned_key(store, key_id, principal.org_id)
    record = store.revoke_api_key(key_id)
    if record is None:
        raise HTTPException(status_code=409, detail="api key already revoked")
    store.record_audit_event(
        actor_user_id=principal.user_id,
        org_id=principal.org_id,
        action="api_key.revoke",
        target_id=key_id,
    )
    return ApiKeyResponse(
        id=record.id,
        name=record.name,
        key_prefix=record.key_prefix,
        created_at=_iso(record.created_at),
        last_used_at=_iso(record.last_used_at),
        expires_at=_iso(record.expires_at),
        revoked_at=_iso(record.revoked_at),
    )


@router.post(
    "/api-keys/{key_id}/regenerate",
    response_model=ApiKeyCreatedResponse,
    summary="Revoke this key and issue a new one with the same name",
)
def regenerate_api_key(
    key_id: str,
    request: Request,
    principal: AuthPrincipal = Depends(get_current_principal),
) -> ApiKeyCreatedResponse:
    store: AuthStore = get_auth_store(request)
    old = _require_owned_key(store, key_id, principal.org_id)
    store.revoke_api_key(key_id)
    raw_key, key_prefix, key_hash = generate_api_key()
    record = store.create_api_key(
        org_id=principal.org_id,
        created_by=principal.user_id,
        name=old.name,
        key_prefix=key_prefix,
        key_hash=key_hash,
    )
    store.record_audit_event(
        actor_user_id=principal.user_id,
        org_id=principal.org_id,
        action="api_key.regenerate",
        target_id=record.id,
        metadata={"replaced_key_id": key_id},
    )
    return ApiKeyCreatedResponse(
        id=record.id,
        name=record.name,
        key_prefix=record.key_prefix,
        raw_key=raw_key,
        created_at=_iso(record.created_at),
    )


# -- agents (ownership registry) -----------------------------------------------


@router.get(
    "/agents", response_model=list[AgentResponse], summary="List my org's agents"
)
def list_my_agents(
    request: Request, principal: AuthPrincipal = Depends(get_current_principal)
) -> list[AgentResponse]:
    store: AuthStore = get_auth_store(request)
    return [
        AgentResponse(
            agent_id=a.agent_id,
            display_name=a.display_name,
            require_approval=a.require_approval,
            created_at=_iso(a.created_at),
            updated_at=_iso(a.updated_at),
        )
        for a in store.list_agents_for_org(principal.org_id)
    ]


@router.post("/agents", response_model=AgentResponse, summary="Register a new agent")
def create_agent(
    req: CreateAgentRequest,
    request: Request,
    principal: AuthPrincipal = Depends(get_current_principal),
) -> AgentResponse:
    store: AuthStore = get_auth_store(request)
    record = store.create_agent(principal.org_id, req.display_name)
    return AgentResponse(
        agent_id=record.agent_id,
        display_name=record.display_name,
        require_approval=record.require_approval,
        created_at=_iso(record.created_at),
        updated_at=_iso(record.updated_at),
    )


def _require_owned_agent(store: AuthStore, agent_id: str, org_id: str):
    agent = store.get_agent(agent_id)
    if agent is None or agent.org_id != org_id:
        raise HTTPException(status_code=404, detail="agent not found")
    return agent


@router.patch(
    "/agents/{agent_id}",
    response_model=AgentResponse,
    summary="Update agent settings (e.g. require_approval)",
)
def update_agent(
    agent_id: str,
    req: UpdateAgentRequest,
    request: Request,
    principal: AuthPrincipal = Depends(get_current_principal),
) -> AgentResponse:
    store: AuthStore = get_auth_store(request)
    agent = _require_owned_agent(store, agent_id, principal.org_id)
    if req.require_approval is not None:
        store.set_agent_require_approval(agent_id, req.require_approval)
        agent = _require_owned_agent(store, agent_id, principal.org_id)
    return AgentResponse(
        agent_id=agent.agent_id,
        display_name=agent.display_name,
        require_approval=agent.require_approval,
        created_at=_iso(agent.created_at),
        updated_at=_iso(agent.updated_at),
    )


@router.get(
    "/agents/{agent_id}/overview",
    summary="Learnings + token stats for one of my agents",
)
def agent_overview(
    agent_id: str,
    request: Request,
    principal: AuthPrincipal = Depends(get_current_principal),
) -> dict:
    store: AuthStore = get_auth_store(request)
    _require_owned_agent(store, agent_id, principal.org_id)
    backend: VectorStoreBackend = request.app.state.backend
    return {
        "stats": backend.stats(agent_id),
        "tokens": backend.token_usage_stats(agent_id),
    }


@router.get(
    "/agents/{agent_id}/learnings",
    summary="Cross-entity aggregate learnings listing (search/sort/paginate)",
)
def list_agent_learnings(
    agent_id: str,
    request: Request,
    principal: AuthPrincipal = Depends(get_current_principal),
    scope: str | None = Query(
        default=None, description="'personal' | 'global' | omit for both"
    ),
    status_: str | None = Query(default=None, alias="status"),
    q: str | None = Query(
        default=None, description="substring search over context/content"
    ),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict:
    """Unlike ``GET /v1/agents/{agent_id}/learnings/personal|global`` (which
    always require an ``entity_id`` for personal listings), this endpoint is
    for the dashboard's Learnings table: every learning under this agent,
    across all entities, with search/filter/sort/pagination — requirement
    the split personal/global endpoints don't serve on their own.
    """
    store: AuthStore = get_auth_store(request)
    _require_owned_agent(store, agent_id, principal.org_id)
    backend: VectorStoreBackend = request.app.state.backend

    scopes = [scope] if scope else ["personal", "global"]
    statuses = (
        [status_]
        if status_
        else ["active", "pending_approval", "rejected", "superseded"]
    )

    rows = []
    for sc in scopes:
        for st in statuses:
            # `personal` listing mode requires entity_id in backend.list()'s
            # SearchFilter (see backend._where); a cross-entity view isn't
            # supported by that method, so this uses the raw SQL escape
            # hatch below instead.
            rows.extend(_list_cross_entity(backend, agent_id, sc, st))

    if q:
        needle = q.lower()
        rows = [
            r
            for r in rows
            if needle in r.context.lower() or needle in r.content.lower()
        ]

    rows.sort(key=lambda r: r.created_at, reverse=True)
    total = len(rows)
    page = rows[offset : offset + limit]
    return {"total": total, "items": [r.model_dump(mode="json") for r in page]}


def _list_cross_entity(
    backend: VectorStoreBackend, agent_id: str, scope: str, status: str
):
    """List every learning for (agent_id, scope, status) regardless of
    entity_id. ``VectorStoreBackend.list()``'s personal mode requires an
    explicit ``entity_id``, since it was designed for the single-entity
    "my personal learnings" read path — this dashboard listing needs the
    cross-entity view instead, so it talks to the pgvector connection pool
    directly rather than adding a new Protocol method for one caller.
    """
    from ..pgvector_backend import PgVectorBackend, _COLUMNS, _row_to_learning

    if not isinstance(backend, PgVectorBackend):
        raise HTTPException(
            status_code=500, detail="cross-entity listing requires PgVectorBackend"
        )
    with backend._pool.connection() as conn:  # noqa: SLF001 - same-package escape hatch
        cur = conn.execute(
            f"SELECT {_COLUMNS} FROM learnings WHERE agent_id = %s AND scope = %s AND status = %s "
            "ORDER BY created_at DESC",
            [agent_id, scope, status],
        )
        return [_row_to_learning(r) for r in cur.fetchall()]


# -- analytics ------------------------------------------------------------


@router.get("/agents/{agent_id}/analytics/learnings", summary="Growth rollups")
def analytics_learnings(
    agent_id: str,
    request: Request,
    principal: AuthPrincipal = Depends(get_current_principal),
    bucket: str = Query(default="day", pattern="^(day|week|month)$"),
) -> dict:
    store: AuthStore = get_auth_store(request)
    _require_owned_agent(store, agent_id, principal.org_id)
    backend: VectorStoreBackend = request.app.state.backend
    return learnings_growth(backend, agent_id, bucket=bucket)


@router.get("/agents/{agent_id}/analytics/usage", summary="Retrieval usage/trend data")
def analytics_usage(
    agent_id: str,
    request: Request,
    principal: AuthPrincipal = Depends(get_current_principal),
    bucket: str = Query(default="day", pattern="^(day|week|month)$"),
) -> dict:
    store: AuthStore = get_auth_store(request)
    _require_owned_agent(store, agent_id, principal.org_id)
    backend: VectorStoreBackend = request.app.state.backend
    return usage_trends(backend, agent_id, bucket=bucket)


# -- admin-only cross-tenant roster -------------------------------------------


@router.get(
    "/admin/agents",
    summary="Every agent_id ever seen, across all tenants (platform staff only)",
)
def admin_list_all_agents(
    request: Request, _admin: User = Depends(require_admin)
) -> list[dict]:
    backend: VectorStoreBackend = request.app.state.backend
    return backend.list_agents()
