"""Tenancy/identity layer: users, organizations, API keys, agent ownership.

Kept as its own package (not folded into ``learnings/backend.py``) because
this data has no vectors and is not part of the ``VectorStoreBackend``
Protocol — it is the SaaS control-plane, layered *above* the existing
agent_id/entity_id engine rather than inside it.
"""

from __future__ import annotations

from .models import (
    AgentRecord,
    ApiKeyRecord,
    AuthPrincipal,
    Organization,
    OrganizationMember,
    User,
)
from .store import AuthStore

__all__ = [
    "User",
    "Organization",
    "OrganizationMember",
    "ApiKeyRecord",
    "AgentRecord",
    "AuthPrincipal",
    "AuthStore",
]
