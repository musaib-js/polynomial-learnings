"""Plain-psycopg data access for the SaaS tenancy tables.

Deliberately a separate module/pool from ``learnings/pgvector_backend.py``:
this data has no vectors and isn't part of the ``VectorStoreBackend``
Protocol. Mirrors that module's connection-pool pattern (autocommit, pooled)
for consistency, but owns its own pool since the two concerns (vector store
vs. tenancy/identity) can scale/fail independently.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Sequence

from psycopg_pool import ConnectionPool

from .models import AgentRecord, ApiKeyRecord, Organization, User


def _new_id() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class AuthStore:
    def __init__(self, dsn: str | None = None, min_size: int = 1, max_size: int = 5):
        self._dsn = dsn or os.environ["DATABASE_URL"]
        self._pool = ConnectionPool(
            self._dsn,
            min_size=min_size,
            max_size=max_size,
            kwargs={"autocommit": True},
            open=True,
        )

    def close(self) -> None:
        self._pool.close()

    # -- users --------------------------------------------------------------

    def create_user(
        self, email: str, password_hash: str, name: str | None = None
    ) -> User:
        with self._pool.connection() as conn:
            row = conn.execute(
                """
                INSERT INTO users (id, email, password_hash, name)
                VALUES (%s, %s, %s, %s)
                RETURNING id, email, name, role, email_verified, created_at, last_login_at
                """,
                [_new_id(), email.lower(), password_hash, name],
            ).fetchone()
        return _row_to_user(row)

    def get_user_by_email(self, email: str) -> tuple[User, str] | None:
        """Return ``(User, password_hash)`` or ``None``."""
        with self._pool.connection() as conn:
            row = conn.execute(
                """
                SELECT id, email, name, role, email_verified, created_at,
                       last_login_at, password_hash
                FROM users WHERE email = %s
                """,
                [email.lower()],
            ).fetchone()
        if row is None:
            return None
        return _row_to_user(row[:7]), row[7]

    def get_user_by_id(self, user_id: str) -> User | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                """
                SELECT id, email, name, role, email_verified, created_at, last_login_at
                FROM users WHERE id = %s
                """,
                [user_id],
            ).fetchone()
        return _row_to_user(row) if row is not None else None

    def touch_last_login(self, user_id: str) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                "UPDATE users SET last_login_at = now() WHERE id = %s", [user_id]
            )

    def update_password(self, user_id: str, password_hash: str) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                "UPDATE users SET password_hash = %s WHERE id = %s",
                [password_hash, user_id],
            )

    def update_profile(self, user_id: str, *, name: str | None) -> User | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                """
                UPDATE users SET name = %s WHERE id = %s
                RETURNING id, email, name, role, email_verified, created_at, last_login_at
                """,
                [name, user_id],
            ).fetchone()
        return _row_to_user(row) if row is not None else None

    # -- organizations --------------------------------------------------------

    def create_personal_organization(self, user_id: str, name: str) -> Organization:
        org_id = _new_id()
        with self._pool.connection() as conn:
            row = conn.execute(
                """
                INSERT INTO organizations (id, name, is_personal, owner_user_id)
                VALUES (%s, %s, TRUE, %s)
                RETURNING id, name, is_personal, owner_user_id, created_at
                """,
                [org_id, name, user_id],
            ).fetchone()
            conn.execute(
                """
                INSERT INTO organization_members (org_id, user_id, role)
                VALUES (%s, %s, 'owner')
                """,
                [org_id, user_id],
            )
        return _row_to_org(row)

    def get_default_org_for_user(self, user_id: str) -> Organization | None:
        """The user's first (today: only) organization."""
        with self._pool.connection() as conn:
            row = conn.execute(
                """
                SELECT o.id, o.name, o.is_personal, o.owner_user_id, o.created_at
                FROM organizations o
                JOIN organization_members m ON m.org_id = o.id
                WHERE m.user_id = %s
                ORDER BY o.created_at ASC
                LIMIT 1
                """,
                [user_id],
            ).fetchone()
        return _row_to_org(row) if row is not None else None

    def is_org_member(self, org_id: str, user_id: str) -> bool:
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM organization_members WHERE org_id = %s AND user_id = %s",
                [org_id, user_id],
            ).fetchone()
        return row is not None

    # -- agents (ownership registry) ------------------------------------------

    def create_agent(self, org_id: str, display_name: str) -> AgentRecord:
        agent_id = f"agt_{uuid.uuid4().hex[:20]}"
        with self._pool.connection() as conn:
            row = conn.execute(
                """
                INSERT INTO agents (agent_id, org_id, display_name)
                VALUES (%s, %s, %s)
                RETURNING agent_id, org_id, display_name, require_approval,
                          created_at, updated_at
                """,
                [agent_id, org_id, display_name],
            ).fetchone()
        return _row_to_agent(row)

    def get_agent(self, agent_id: str) -> AgentRecord | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                """
                SELECT agent_id, org_id, display_name, require_approval,
                       created_at, updated_at
                FROM agents WHERE agent_id = %s
                """,
                [agent_id],
            ).fetchone()
        return _row_to_agent(row) if row is not None else None

    def list_agents_for_org(self, org_id: str) -> list[AgentRecord]:
        with self._pool.connection() as conn:
            rows = conn.execute(
                """
                SELECT agent_id, org_id, display_name, require_approval,
                       created_at, updated_at
                FROM agents WHERE org_id = %s
                ORDER BY created_at DESC
                """,
                [org_id],
            ).fetchall()
        return [_row_to_agent(r) for r in rows]

    def agent_belongs_to_org(self, agent_id: str, org_id: str) -> bool:
        agent = self.get_agent(agent_id)
        return agent is not None and agent.org_id == org_id

    def set_agent_require_approval(self, agent_id: str, require_approval: bool) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                "UPDATE agents SET require_approval = %s, updated_at = now() WHERE agent_id = %s",
                [require_approval, agent_id],
            )

    # -- API keys --------------------------------------------------------------

    def create_api_key(
        self, org_id: str, created_by: str, name: str, key_prefix: str, key_hash: str
    ) -> ApiKeyRecord:
        with self._pool.connection() as conn:
            row = conn.execute(
                """
                INSERT INTO api_keys (id, org_id, created_by, name, key_prefix, key_hash)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id, org_id, created_by, name, key_prefix, key_hash, scopes,
                          created_at, last_used_at, expires_at, revoked_at
                """,
                [_new_id(), org_id, created_by, name, key_prefix, key_hash],
            ).fetchone()
        return _row_to_api_key(row)

    def list_api_keys(self, org_id: str) -> list[ApiKeyRecord]:
        with self._pool.connection() as conn:
            rows = conn.execute(
                """
                SELECT id, org_id, created_by, name, key_prefix, key_hash, scopes,
                       created_at, last_used_at, expires_at, revoked_at
                FROM api_keys WHERE org_id = %s
                ORDER BY created_at DESC
                """,
                [org_id],
            ).fetchall()
        return [_row_to_api_key(r) for r in rows]

    def get_api_key(self, key_id: str) -> ApiKeyRecord | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                """
                SELECT id, org_id, created_by, name, key_prefix, key_hash, scopes,
                       created_at, last_used_at, expires_at, revoked_at
                FROM api_keys WHERE id = %s
                """,
                [key_id],
            ).fetchone()
        return _row_to_api_key(row) if row is not None else None

    def get_api_key_by_hash(self, key_hash: str) -> ApiKeyRecord | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                """
                SELECT id, org_id, created_by, name, key_prefix, key_hash, scopes,
                       created_at, last_used_at, expires_at, revoked_at
                FROM api_keys WHERE key_hash = %s
                """,
                [key_hash],
            ).fetchone()
        return _row_to_api_key(row) if row is not None else None

    def touch_api_key_last_used(self, key_id: str) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                "UPDATE api_keys SET last_used_at = now() WHERE id = %s", [key_id]
            )

    def revoke_api_key(self, key_id: str) -> ApiKeyRecord | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                """
                UPDATE api_keys SET revoked_at = now() WHERE id = %s AND revoked_at IS NULL
                RETURNING id, org_id, created_by, name, key_prefix, key_hash, scopes,
                          created_at, last_used_at, expires_at, revoked_at
                """,
                [key_id],
            ).fetchone()
        return _row_to_api_key(row) if row is not None else None

    # -- password reset --------------------------------------------------------

    def create_password_reset_token(
        self, user_id: str, token_hash: str, ttl_seconds: int
    ) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                """
                INSERT INTO password_reset_tokens (id, user_id, token_hash, expires_at)
                VALUES (%s, %s, %s, now() + make_interval(secs => %s))
                """,
                [_new_id(), user_id, token_hash, ttl_seconds],
            )

    def consume_password_reset_token(self, token_hash: str) -> str | None:
        """Mark the token used and return the owning ``user_id``, or ``None``
        if it doesn't exist, is expired, or was already used."""
        with self._pool.connection() as conn:
            row = conn.execute(
                """
                UPDATE password_reset_tokens
                SET used_at = now()
                WHERE token_hash = %s AND used_at IS NULL AND expires_at > now()
                RETURNING user_id
                """,
                [token_hash],
            ).fetchone()
        return str(row[0]) if row is not None else None

    # -- refresh tokens ----------------------------------------------------

    def create_refresh_token(
        self, user_id: str, token_hash: str, ttl_seconds: int
    ) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                """
                INSERT INTO refresh_tokens (id, user_id, token_hash, expires_at)
                VALUES (%s, %s, %s, now() + make_interval(secs => %s))
                """,
                [_new_id(), user_id, token_hash, ttl_seconds],
            )

    def get_active_refresh_token_user(self, token_hash: str) -> str | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                """
                SELECT user_id FROM refresh_tokens
                WHERE token_hash = %s AND revoked_at IS NULL AND expires_at > now()
                """,
                [token_hash],
            ).fetchone()
        return str(row[0]) if row is not None else None

    def revoke_refresh_token(self, token_hash: str) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                "UPDATE refresh_tokens SET revoked_at = now() WHERE token_hash = %s",
                [token_hash],
            )

    # -- audit log -----------------------------------------------------------

    def record_audit_event(
        self,
        *,
        actor_user_id: str | None,
        org_id: str | None,
        action: str,
        target_id: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        import json

        with self._pool.connection() as conn:
            conn.execute(
                """
                INSERT INTO audit_log (id, actor_user_id, org_id, action, target_id, metadata)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                [
                    _new_id(),
                    actor_user_id,
                    org_id,
                    action,
                    target_id,
                    json.dumps(metadata or {}),
                ],
            )

    # -- learning events (analytics) ------------------------------------------

    def record_learning_event(
        self,
        *,
        learning_id: str,
        agent_id: str,
        entity_id: str | None,
        event_type: str,
    ) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                """
                INSERT INTO learning_events (id, learning_id, agent_id, entity_id, event_type)
                VALUES (%s, %s, %s, %s, %s)
                """,
                [_new_id(), learning_id, agent_id, entity_id, event_type],
            )


def _row_to_user(row: Sequence) -> User:
    from .models import UserRole

    return User(
        id=str(row[0]),
        email=row[1],
        name=row[2],
        role=UserRole(row[3]),
        email_verified=row[4],
        created_at=row[5],
        last_login_at=row[6],
    )


def _row_to_org(row: Sequence) -> Organization:
    return Organization(
        id=str(row[0]),
        name=row[1],
        is_personal=row[2],
        owner_user_id=str(row[3]),
        created_at=row[4],
    )


def _row_to_agent(row: Sequence) -> AgentRecord:
    return AgentRecord(
        agent_id=row[0],
        org_id=str(row[1]),
        display_name=row[2],
        require_approval=row[3],
        created_at=row[4],
        updated_at=row[5],
    )


def _row_to_api_key(row: Sequence) -> ApiKeyRecord:
    return ApiKeyRecord(
        id=str(row[0]),
        org_id=str(row[1]),
        created_by=str(row[2]),
        name=row[3],
        key_prefix=row[4],
        key_hash=row[5],
        scopes=list(row[6]) if row[6] else [],
        created_at=row[7],
        last_used_at=row[8],
        expires_at=row[9],
        revoked_at=row[10],
    )
