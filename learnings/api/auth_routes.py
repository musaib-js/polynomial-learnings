"""``/v1/auth/*`` — signup, login, logout, refresh, forgot/reset password, profile.

JWT-issuing routes for the browser dashboard SPA. Distinct auth scheme and
prefix from the existing agent-runtime API (``/v1/agents/...``, API-key
authenticated) and from ``/v1/dashboard/*`` (JWT-authenticated, see
``dashboard_routes.py``).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from ..auth.deps import get_current_user, get_auth_store
from ..auth.models import User
from ..auth.security import (
    create_access_token,
    generate_opaque_token,
    hash_opaque_token,
    hash_password,
    verify_password,
)
from ..auth.store import AuthStore
from ..settings import settings
from .auth_schemas import (
    ForgotPasswordRequest,
    LoginRequest,
    LogoutRequest,
    MeResponse,
    RefreshRequest,
    ResetPasswordRequest,
    SignupRequest,
    TokenPair,
    UpdateProfileRequest,
)

router = APIRouter(prefix="/v1/auth", tags=["auth"])


def _issue_token_pair(store: AuthStore, user_id: str, org_id: str) -> TokenPair:
    access_token = create_access_token(user_id, org_id)
    raw_refresh, refresh_hash = generate_opaque_token()
    store.create_refresh_token(
        user_id, refresh_hash, settings.jwt_refresh_token_ttl_seconds
    )
    return TokenPair(access_token=access_token, refresh_token=raw_refresh)


@router.post("/signup", response_model=TokenPair, summary="Create an account")
def signup(req: SignupRequest, request: Request) -> TokenPair:
    store: AuthStore = get_auth_store(request)
    if store.get_user_by_email(req.email) is not None:
        raise HTTPException(status_code=409, detail="email already registered")

    user = store.create_user(req.email, hash_password(req.password), name=req.name)
    # Every signup gets an implicit personal org, so teams/orgs can be added
    # later without a schema change or a "migrate existing users" step.
    org = store.create_personal_organization(user.id, name=req.name or req.email)
    return _issue_token_pair(store, user.id, org.id)


@router.post("/login", response_model=TokenPair, summary="Log in")
def login(req: LoginRequest, request: Request) -> TokenPair:
    store: AuthStore = get_auth_store(request)
    found = store.get_user_by_email(req.email)
    if found is None:
        raise HTTPException(status_code=401, detail="invalid email or password")
    user, password_hash = found
    if not verify_password(req.password, password_hash):
        raise HTTPException(status_code=401, detail="invalid email or password")

    org = store.get_default_org_for_user(user.id)
    if org is None:
        raise HTTPException(status_code=500, detail="user has no organization")
    store.touch_last_login(user.id)
    return _issue_token_pair(store, user.id, org.id)


@router.post("/refresh", response_model=TokenPair, summary="Exchange a refresh token")
def refresh(req: RefreshRequest, request: Request) -> TokenPair:
    store: AuthStore = get_auth_store(request)
    token_hash = hash_opaque_token(req.refresh_token)
    user_id = store.get_active_refresh_token_user(token_hash)
    if user_id is None:
        raise HTTPException(status_code=401, detail="invalid or expired refresh token")

    org = store.get_default_org_for_user(user_id)
    if org is None:
        raise HTTPException(status_code=500, detail="user has no organization")

    # Rotate: revoke the used refresh token and issue a brand new pair.
    store.revoke_refresh_token(token_hash)
    return _issue_token_pair(store, user_id, org.id)


@router.post("/logout", status_code=204, summary="Revoke a refresh token")
def logout(req: LogoutRequest, request: Request) -> None:
    store: AuthStore = get_auth_store(request)
    store.revoke_refresh_token(hash_opaque_token(req.refresh_token))


@router.post(
    "/forgot-password",
    status_code=204,
    summary="Request a password reset token (emailed out-of-band)",
)
def forgot_password(req: ForgotPasswordRequest, request: Request) -> None:
    store: AuthStore = get_auth_store(request)
    found = store.get_user_by_email(req.email)
    # Always 204, whether or not the email exists — do not leak account
    # existence via response shape/timing.
    if found is None:
        return
    user, _ = found
    raw_token, token_hash = generate_opaque_token()
    store.create_password_reset_token(user.id, token_hash, ttl_seconds=60 * 60)
    # Email delivery is intentionally out of scope / pluggable for MVP (see
    # plan §4) — logged here so the flow is exercisable in dev without SMTP.
    import logging

    logging.getLogger("learnings.auth").info(
        "password reset token generated for %s (delivery not wired up)", user.email
    )
    _ = raw_token  # would be emailed to the user, never returned by this endpoint


@router.post(
    "/reset-password", status_code=204, summary="Consume a password reset token"
)
def reset_password(req: ResetPasswordRequest, request: Request) -> None:
    store: AuthStore = get_auth_store(request)
    user_id = store.consume_password_reset_token(hash_opaque_token(req.token))
    if user_id is None:
        raise HTTPException(status_code=400, detail="invalid or expired reset token")
    store.update_password(user_id, hash_password(req.new_password))


@router.get("/me", response_model=MeResponse, summary="Current user profile")
def me(user: User = Depends(get_current_user)) -> User:
    return user


@router.patch("/me", response_model=MeResponse, summary="Update profile")
def update_me(
    req: UpdateProfileRequest,
    request: Request,
    user: User = Depends(get_current_user),
) -> User:
    store: AuthStore = get_auth_store(request)
    updated = store.update_profile(user.id, name=req.name)
    assert updated is not None
    return updated
