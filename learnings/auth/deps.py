"""FastAPI dependencies for the tenancy/identity layer.

Two independent ways to authenticate a request, matching the two audiences
described in the SaaS plan:

* ``get_current_user`` — JWT bearer token, for the browser dashboard SPA
  (``/v1/auth/*``, ``/v1/dashboard/*``).
* ``get_api_key_principal`` — API key, for the pip package's runtime calls
  (``/v1/agents/*``).

``require_agent_ownership`` accepts *either* and is what gets attached to
every existing ``/v1/agents/{agent_id}/...`` route so that route continues
to work unchanged for its request/response shape, but now 404s (not silently
serves) when the caller's org doesn't own that ``agent_id``.
"""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException, Request

from .models import AuthPrincipal, User, UserRole
from .security import decode_access_token, verify_api_key
from .store import AuthStore


def get_auth_store(request: Request) -> AuthStore:
    return request.app.state.auth_store


def _bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != "bearer" or not value:
        return None
    return value


def get_current_user(
    request: Request,
    authorization: str | None = Header(default=None),
) -> User:
    """Resolve the JWT bearer token on this request to a ``User``.

    Raises 401 if the token is missing, malformed, expired, or no longer
    refers to an existing user.
    """
    token = _bearer_token(authorization)
    if token is None:
        raise HTTPException(status_code=401, detail="missing bearer token")
    payload = decode_access_token(token)
    if payload is None:
        raise HTTPException(status_code=401, detail="invalid or expired token")
    store: AuthStore = request.app.state.auth_store
    user = store.get_user_by_id(payload["sub"])
    if user is None:
        raise HTTPException(status_code=401, detail="user no longer exists")
    return user


def get_current_principal(
    request: Request,
    user: User = Depends(get_current_user),
) -> AuthPrincipal:
    """``AuthPrincipal`` for the current JWT-authenticated user's default org.

    Used by ``/v1/dashboard/*`` routes, which are scoped to "my organization"
    rather than to an arbitrary org resolved from an API key.
    """
    store: AuthStore = request.app.state.auth_store
    org = store.get_default_org_for_user(user.id)
    if org is None:
        raise HTTPException(status_code=500, detail="user has no organization")
    return AuthPrincipal(org_id=org.id, user_id=user.id, role=user.role)


def get_api_key_principal(
    request: Request,
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> AuthPrincipal:
    """Resolve an API key (``Authorization: Bearer sk_live_...`` or
    ``X-API-Key: sk_live_...``) to an :class:`AuthPrincipal`.

    This is the narrow integration point for the teammate's pip-package
    communication layer — see ``learnings/auth/security.py::verify_api_key``.
    """
    raw_key = _bearer_token(authorization) or x_api_key
    if raw_key is None:
        raise HTTPException(status_code=401, detail="missing API key")
    store: AuthStore = request.app.state.auth_store
    principal = verify_api_key(raw_key, store)
    if principal is None:
        raise HTTPException(status_code=401, detail="invalid or revoked API key")
    return principal


def require_agent_ownership(
    agent_id: str,
    request: Request,
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> AuthPrincipal:
    """Authenticate via API key and confirm the caller's org owns ``agent_id``.

    Attached to every existing ``/v1/agents/{agent_id}/...`` route (see
    ``learnings/api/routes.py``) so those routes keep their exact
    request/response shape but stop being reachable by anyone who merely
    guesses an ``agent_id`` string.
    """
    principal = get_api_key_principal(request, authorization, x_api_key)
    store: AuthStore = request.app.state.auth_store
    if not store.agent_belongs_to_org(agent_id, principal.org_id):
        # 404, not 403: don't confirm to an unauthorized caller that this
        # agent_id exists at all.
        raise HTTPException(status_code=404, detail="agent not found")
    return principal


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != UserRole.admin:
        raise HTTPException(status_code=403, detail="admin role required")
    return user
