"""SaaS tenancy tables: users, organizations, api_keys, agents, analytics.

Does not touch learnings/token_usage/agent_learnings (owned by schema.sql /
init_schema()) — see alembic/env.py docstring.

Revision ID: 0001_saas_tenancy_tables
Revises:
Create Date: 2026-07-28
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "0001_saas_tenancy_tables"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')  # gen_random_uuid()

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            email          TEXT NOT NULL UNIQUE,
            password_hash  TEXT NOT NULL,
            name           TEXT,
            email_verified BOOLEAN NOT NULL DEFAULT FALSE,
            role           TEXT NOT NULL DEFAULT 'member',
            created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            last_login_at  TIMESTAMPTZ
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS organizations (
            id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name          TEXT NOT NULL,
            is_personal   BOOLEAN NOT NULL DEFAULT TRUE,
            owner_user_id UUID NOT NULL REFERENCES users(id),
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS organization_members (
            org_id     UUID NOT NULL REFERENCES organizations(id),
            user_id    UUID NOT NULL REFERENCES users(id),
            role       TEXT NOT NULL DEFAULT 'owner',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (org_id, user_id)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS agents (
            agent_id         TEXT PRIMARY KEY,
            org_id           UUID NOT NULL REFERENCES organizations(id),
            display_name     TEXT NOT NULL,
            require_approval BOOLEAN NOT NULL DEFAULT FALSE,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS agents_org_idx ON agents (org_id)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS api_keys (
            id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id       UUID NOT NULL REFERENCES organizations(id),
            created_by   UUID NOT NULL REFERENCES users(id),
            name         TEXT NOT NULL,
            key_prefix   TEXT NOT NULL,
            key_hash     TEXT NOT NULL UNIQUE,
            scopes       JSONB NOT NULL DEFAULT '[]',
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            last_used_at TIMESTAMPTZ,
            expires_at   TIMESTAMPTZ,
            revoked_at   TIMESTAMPTZ
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS api_keys_org_idx ON api_keys (org_id)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS password_reset_tokens (
            id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id    UUID NOT NULL REFERENCES users(id),
            token_hash TEXT NOT NULL UNIQUE,
            expires_at TIMESTAMPTZ NOT NULL,
            used_at    TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS refresh_tokens (
            id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id    UUID NOT NULL REFERENCES users(id),
            token_hash TEXT NOT NULL UNIQUE,
            expires_at TIMESTAMPTZ NOT NULL,
            revoked_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS learning_events (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            learning_id UUID NOT NULL,
            agent_id    TEXT NOT NULL,
            entity_id   TEXT,
            event_type  TEXT NOT NULL,
            occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS learning_events_agent_time_idx "
        "ON learning_events (agent_id, occurred_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS learning_events_learning_idx "
        "ON learning_events (learning_id, occurred_at DESC)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_log (
            id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            actor_user_id UUID REFERENCES users(id),
            org_id        UUID REFERENCES organizations(id),
            action        TEXT NOT NULL,
            target_id     TEXT,
            metadata      JSONB NOT NULL DEFAULT '{}',
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS usage_limits (
            org_id              UUID PRIMARY KEY REFERENCES organizations(id),
            requests_per_minute INTEGER,
            monthly_quota       INTEGER,
            plan                TEXT NOT NULL DEFAULT 'free'
        )
        """
    )

    # Time-bucketed rollups (growth charts) read learnings.created_at by
    # agent_id; schema.sql's own composite index is filter-first, not
    # time-first, so add a dedicated index for analytics.py's queries
    # without touching schema.sql itself.
    op.execute(
        "CREATE INDEX IF NOT EXISTS learnings_agent_created_idx "
        "ON learnings (agent_id, created_at)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS learnings_agent_created_idx")
    op.execute("DROP TABLE IF EXISTS usage_limits")
    op.execute("DROP TABLE IF EXISTS audit_log")
    op.execute("DROP TABLE IF EXISTS learning_events")
    op.execute("DROP TABLE IF EXISTS refresh_tokens")
    op.execute("DROP TABLE IF EXISTS password_reset_tokens")
    op.execute("DROP TABLE IF EXISTS api_keys")
    op.execute("DROP TABLE IF EXISTS agents")
    op.execute("DROP TABLE IF EXISTS organization_members")
    op.execute("DROP TABLE IF EXISTS organizations")
    op.execute("DROP TABLE IF EXISTS users")
