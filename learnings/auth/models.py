"""Data models for the SaaS tenancy/identity layer.

These sit *above* the existing ``learnings.Learning`` engine: a ``User``
belongs to one or more ``Organization``s (every signup gets an implicit
personal org), an ``Organization`` owns ``ApiKeyRecord``s and ``AgentRecord``s
(the ownership registry for the pre-existing, unconstrained ``agent_id``
string used throughout ``learnings/pgvector_backend.py``).
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class UserRole(str, Enum):
    """Platform-level role — distinct from an org membership role.

    ``admin`` is platform staff (gates the cross-tenant agent roster and the
    dashboard's raw agent-targeting "Advanced" section); ``member`` is every
    ordinary customer.
    """

    member = "member"
    admin = "admin"


class OrgRole(str, Enum):
    """A user's role within one organization. Both values exist from day
    one (even though every org is a single-member "personal" org today) so
    "invite a teammate" can ship later with zero schema change."""

    owner = "owner"
    member = "member"


class User(BaseModel):
    id: str
    email: str
    name: str | None = None
    role: UserRole = UserRole.member
    email_verified: bool = False
    created_at: datetime
    last_login_at: datetime | None = None


class Organization(BaseModel):
    id: str
    name: str
    is_personal: bool = True
    owner_user_id: str
    created_at: datetime


class OrganizationMember(BaseModel):
    org_id: str
    user_id: str
    role: OrgRole = OrgRole.owner
    created_at: datetime


class AgentRecord(BaseModel):
    """Ownership-registry row for an ``agent_id`` used in ``learnings.*``.

    ``learnings.agent_id`` itself stays a free-text column (see
    ``schema.sql``); this table is the only place that says which
    organization a given ``agent_id`` belongs to.
    """

    agent_id: str
    org_id: str
    display_name: str
    require_approval: bool = False
    created_at: datetime
    updated_at: datetime


class ApiKeyRecord(BaseModel):
    """A stored API key row. ``key_hash`` is ``sha256(raw_key)`` — the raw
    key itself is never persisted and can only be shown once, at creation
    time (see ``learnings/auth/security.py::generate_api_key``)."""

    id: str
    org_id: str
    created_by: str
    name: str
    key_prefix: str
    key_hash: str
    scopes: list[str] = Field(default_factory=list)
    created_at: datetime
    last_used_at: datetime | None = None
    expires_at: datetime | None = None
    revoked_at: datetime | None = None

    @property
    def is_active(self) -> bool:
        if self.revoked_at is not None:
            return False
        if self.expires_at is not None and self.expires_at <= datetime.now(
            self.expires_at.tzinfo
        ):
            return False
        return True


class AuthPrincipal(BaseModel):
    """Resolved identity for one authenticated request.

    Produced either by ``get_current_user`` (JWT -> user + their default org)
    or by ``get_api_key_principal`` (API key -> org). Everything downstream
    (ownership checks, audit logging) only depends on this shape, not on
    *how* the principal was authenticated.
    """

    org_id: str
    user_id: str | None = None
    api_key_id: str | None = None
    role: UserRole = UserRole.member
