"""Request/response schemas for /v1/auth/* and /v1/dashboard/*."""

from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field

from ..auth.models import User


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    name: str | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(min_length=8)


class UpdateProfileRequest(BaseModel):
    name: str | None = None


class MeResponse(User):
    pass


class CreateApiKeyRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class ApiKeyCreatedResponse(BaseModel):
    """Returned only once, at creation — the raw key is never shown again."""

    id: str
    name: str
    key_prefix: str
    raw_key: str
    created_at: str


class ApiKeyResponse(BaseModel):
    id: str
    name: str
    key_prefix: str
    created_at: str
    last_used_at: str | None = None
    expires_at: str | None = None
    revoked_at: str | None = None


class CreateAgentRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=200)


class AgentResponse(BaseModel):
    agent_id: str
    display_name: str
    require_approval: bool
    created_at: str
    updated_at: str


class UpdateAgentRequest(BaseModel):
    require_approval: bool | None = None
