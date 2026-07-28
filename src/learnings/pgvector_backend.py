"""Postgres + pgvector implementation of ``VectorStoreBackend``.

Uses psycopg 3 and the ``pgvector.psycopg`` adapter. All isolation filtering is
done in the SQL WHERE clause, *before* any similarity or keyword ranking, so a
learning belonging to another entity is never a candidate.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Sequence

import psycopg
from pgvector.psycopg import register_vector
from psycopg_pool import ConnectionPool

from .backend import SearchFilter
from .models import Learning, Outcome, Scope, Status, TokenUsageRecord

# Shipped inside the package (see ``tool.setuptools.package-data``) so
# ``init_schema`` works from an installed wheel, not just a source checkout.
_SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"

# Columns selected when reconstructing a Learning, in a fixed order.
_COLUMNS = (
    "id, agent_id, entity_id, scope, status, supersedes, "
    "context, content, outcome, reason, original_output, corrected_output, "
    "category, tags, created_at, last_used_at, hits"
)


def init_schema(dsn: str, dim: int) -> None:
    """Create the extension, table, and indexes if they do not exist.

    ``dim`` must match the embedder's vector dimension.
    """
    sql = _SCHEMA_PATH.read_text().replace("{dim}", str(int(dim)))
    with psycopg.connect(dsn) as conn:
        conn.execute(sql)
        conn.commit()


def _row_to_learning(row: tuple) -> Learning:
    return Learning(
        id=str(row[0]),
        agent_id=row[1],
        entity_id=row[2],
        scope=Scope(row[3]),
        status=Status(row[4]),
        supersedes=str(row[5]) if row[5] is not None else None,
        context=row[6],
        content=row[7],
        outcome=Outcome(row[8]),
        reason=row[9],
        original_output=row[10],
        corrected_output=row[11],
        category=row[12],
        tags=list(row[13]) if row[13] is not None else [],
        created_at=row[14],
        last_used_at=row[15],
        hits=row[16],
    )


def _where(flt: SearchFilter) -> tuple[str, list]:
    """Build the isolation pre-filter WHERE clause and its parameters.

    Two modes:

    * ``scope`` unset (retrieval): visible scope — always global, plus personal
      only for this entity. This is the hybrid-search pre-filter.
    * ``scope`` set (listing): match that scope exactly. ``personal`` additionally
      requires the given ``entity_id``; ``global`` ignores entity.
    """
    clauses = ["agent_id = %s"]
    params: list = [flt["agent_id"]]

    clauses.append("status = %s")
    params.append(flt.get("status", "active"))

    scope = flt.get("scope")
    if scope is not None:
        clauses.append("scope = %s")
        params.append(scope)
        if scope == "personal":
            clauses.append("entity_id = %s")
            params.append(flt.get("entity_id"))
    else:
        # Visible scope: always global; personal only for this entity.
        entity_id = flt.get("entity_id")
        if entity_id is not None:
            clauses.append("(scope = 'global' OR entity_id = %s)")
            params.append(entity_id)
        else:
            clauses.append("scope = 'global'")

    return " AND ".join(clauses), params


class PgVectorBackend:
    def __init__(
        self,
        dsn: str | None = None,
        min_size: int = 1,
        max_size: int = 10,
    ):
        self._dsn = dsn or os.environ["DATABASE_URL"]
        # A pool so the backend is safe under concurrent API requests. Each
        # pooled connection is autocommit and has the pgvector adapter registered.
        self._pool = ConnectionPool(
            self._dsn,
            min_size=min_size,
            max_size=max_size,
            kwargs={"autocommit": True},
            configure=register_vector,
            open=True,
        )

    def close(self) -> None:
        self._pool.close()

    # -- writes -----------------------------------------------------------
    def upsert(self, learning: Learning, embedding: Sequence[float]) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                """
            INSERT INTO learnings (
                id, agent_id, entity_id, scope, status, supersedes,
                context, content, outcome, reason, original_output,
                corrected_output, category, tags,
                created_at, last_used_at, hits, embedding
            ) VALUES (
                %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s, %s::vector
            )
            ON CONFLICT (id) DO UPDATE SET
                status = EXCLUDED.status,
                supersedes = EXCLUDED.supersedes,
                context = EXCLUDED.context,
                content = EXCLUDED.content,
                outcome = EXCLUDED.outcome,
                reason = EXCLUDED.reason,
                original_output = EXCLUDED.original_output,
                corrected_output = EXCLUDED.corrected_output,
                category = EXCLUDED.category,
                tags = EXCLUDED.tags,
                last_used_at = EXCLUDED.last_used_at,
                hits = EXCLUDED.hits,
                embedding = EXCLUDED.embedding
            """,
                (
                    learning.id,
                    learning.agent_id,
                    learning.entity_id,
                    learning.scope.value,
                    learning.status.value,
                    learning.supersedes,
                    learning.context,
                    learning.content,
                    learning.outcome.value,
                    learning.reason,
                    learning.original_output,
                    learning.corrected_output,
                    learning.category,
                    learning.tags,
                    learning.created_at,
                    learning.last_used_at,
                    learning.hits,
                    list(embedding),
                ),
            )

    def update(self, learning_id: str, **fields) -> None:
        if not fields:
            return
        assignments = ", ".join(f"{col} = %s" for col in fields)
        params = list(fields.values()) + [learning_id]
        with self._pool.connection() as conn:
            conn.execute(f"UPDATE learnings SET {assignments} WHERE id = %s", params)

    # -- reads ------------------------------------------------------------
    def vector_search(
        self, query_embedding: Sequence[float], flt: SearchFilter, top_k: int
    ) -> list[tuple[Learning, float]]:
        where, params = _where(flt)
        # 1 - cosine_distance  ->  cosine similarity in [0, 1].
        with self._pool.connection() as conn:
            cur = conn.execute(
                f"""
                SELECT {_COLUMNS}, 1 - (embedding <=> %s::vector) AS score
                FROM learnings
                WHERE {where}
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                [list(query_embedding), *params, list(query_embedding), top_k],
            )
            return [(_row_to_learning(r), float(r[-1])) for r in cur.fetchall()]

    def keyword_search(
        self, query_text: str, flt: SearchFilter, top_k: int
    ) -> list[tuple[Learning, float]]:
        where, params = _where(flt)
        with self._pool.connection() as conn:
            cur = conn.execute(
                f"""
                SELECT {_COLUMNS}, ts_rank(search_tsv, plainto_tsquery('english', %s)) AS score
                FROM learnings
                WHERE {where} AND search_tsv @@ plainto_tsquery('english', %s)
                ORDER BY score DESC
                LIMIT %s
                """,
                [query_text, *params, query_text, top_k],
            )
            return [(_row_to_learning(r), float(r[-1])) for r in cur.fetchall()]

    def list(
        self, flt: SearchFilter, limit: int = 50, offset: int = 0
    ) -> list[Learning]:
        """List learnings matching ``flt``, most recently used first.

        Unlike the search methods this does no ranking — it is the read path
        behind the "get personal / global learnings" API endpoints.
        """
        where, params = _where(flt)
        with self._pool.connection() as conn:
            cur = conn.execute(
                f"""
                SELECT {_COLUMNS}
                FROM learnings
                WHERE {where}
                ORDER BY last_used_at DESC NULLS LAST, created_at DESC
                LIMIT %s OFFSET %s
                """,
                [*params, limit, offset],
            )
            return [_row_to_learning(r) for r in cur.fetchall()]

    def get(self, learning_id: str) -> Learning | None:
        with self._pool.connection() as conn:
            cur = conn.execute(
                f"SELECT {_COLUMNS} FROM learnings WHERE id = %s", [learning_id]
            )
            row = cur.fetchone()
        return _row_to_learning(row) if row is not None else None

    def stats(self, agent_id: str, top_n: int = 5) -> dict:
        with self._pool.connection() as conn:
            agg = conn.execute(
                """
                SELECT
                    count(*)                                            AS total,
                    count(*) FILTER (WHERE status = 'active')           AS active,
                    count(*) FILTER (WHERE status = 'superseded')       AS superseded,
                    count(*) FILTER (WHERE status = 'rejected')         AS rejected,
                    count(*) FILTER (WHERE scope = 'personal')          AS personal,
                    count(*) FILTER (WHERE scope = 'global')            AS global,
                    coalesce(sum(hits), 0)                              AS total_hits,
                    coalesce(avg(hits), 0)                              AS avg_hits,
                    count(DISTINCT entity_id)                           AS distinct_entities,
                    max(last_used_at)                                   AS last_used_at,
                    max(created_at)                                     AS last_created_at
                FROM learnings
                WHERE agent_id = %s
                """,
                [agent_id],
            ).fetchone()

            top = conn.execute(
                """
                SELECT id, context, content, hits
                FROM learnings
                WHERE agent_id = %s AND hits > 0
                ORDER BY hits DESC, last_used_at DESC
                LIMIT %s
                """,
                [agent_id, top_n],
            ).fetchall()

        return {
            "total": agg[0],
            "by_status": {
                "active": agg[1],
                "superseded": agg[2],
                "rejected": agg[3],
            },
            "by_scope": {"personal": agg[4], "global": agg[5]},
            "total_hits": int(agg[6]),
            "avg_hits": float(agg[7]),
            "distinct_entities": agg[8],
            "last_used_at": agg[9],
            "last_created_at": agg[10],
            "most_used": [
                {"id": str(r[0]), "context": r[1], "content": r[2], "hits": r[3]}
                for r in top
            ],
        }

    def list_agents(self) -> list[dict]:
        """Derive the agent roster from the learnings and token tables.

        Any ``agent_id`` that has stored a learning *or* merely spent tokens
        (e.g. a persist that the Judge rejected) counts as a known agent, so
        the roster unions both sources. Ordered by most recent activity.
        """
        with self._pool.connection() as conn:
            rows = conn.execute(
                """
                WITH ids AS (
                    SELECT DISTINCT agent_id FROM learnings
                    UNION
                    SELECT DISTINCT agent_id FROM token_usage
                )
                SELECT
                    ids.agent_id,
                    coalesce(l.total, 0)             AS total_learnings,
                    coalesce(l.active, 0)            AS active,
                    coalesce(l.distinct_entities, 0) AS distinct_entities,
                    l.last_activity
                FROM ids
                LEFT JOIN (
                    SELECT
                        agent_id,
                        count(*)                                  AS total,
                        count(*) FILTER (WHERE status = 'active') AS active,
                        count(DISTINCT entity_id)                 AS distinct_entities,
                        greatest(max(last_used_at), max(created_at)) AS last_activity
                    FROM learnings
                    GROUP BY agent_id
                ) l ON l.agent_id = ids.agent_id
                ORDER BY l.last_activity DESC NULLS LAST, ids.agent_id
                """
            ).fetchall()

        return [
            {
                "agent_id": r[0],
                "total_learnings": int(r[1]),
                "active": int(r[2]),
                "distinct_entities": int(r[3]),
                "last_activity": r[4],
            }
            for r in rows
        ]

    # -- token accounting -------------------------------------------------
    def record_token_usage(self, record: TokenUsageRecord) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                """
                INSERT INTO token_usage (
                    id, agent_id, entity_id, operation, model,
                    prompt_tokens, completion_tokens, total_tokens, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    record.id,
                    record.agent_id,
                    record.entity_id,
                    record.operation,
                    record.model,
                    record.prompt_tokens,
                    record.completion_tokens,
                    record.total_tokens,
                    record.created_at,
                ),
            )

    def token_usage_stats(self, agent_id: str) -> dict:
        with self._pool.connection() as conn:
            agg = conn.execute(
                """
                SELECT
                    count(*)                              AS total_calls,
                    coalesce(sum(prompt_tokens), 0)       AS prompt_tokens,
                    coalesce(sum(completion_tokens), 0)   AS completion_tokens,
                    coalesce(sum(total_tokens), 0)        AS total_tokens
                FROM token_usage
                WHERE agent_id = %s
                """,
                [agent_id],
            ).fetchone()

            by_operation = conn.execute(
                """
                SELECT
                    operation,
                    count(*)                              AS calls,
                    coalesce(sum(prompt_tokens), 0)       AS prompt_tokens,
                    coalesce(sum(completion_tokens), 0)   AS completion_tokens,
                    coalesce(sum(total_tokens), 0)        AS total_tokens
                FROM token_usage
                WHERE agent_id = %s
                GROUP BY operation
                ORDER BY total_tokens DESC
                """,
                [agent_id],
            ).fetchall()

            by_model = conn.execute(
                """
                SELECT coalesce(model, 'unknown'), coalesce(sum(total_tokens), 0)
                FROM token_usage
                WHERE agent_id = %s
                GROUP BY model
                """,
                [agent_id],
            ).fetchall()

        return {
            "total_calls": agg[0],
            "prompt_tokens": int(agg[1]),
            "completion_tokens": int(agg[2]),
            "total_tokens": int(agg[3]),
            "by_operation": [
                {
                    "operation": r[0],
                    "calls": r[1],
                    "prompt_tokens": int(r[2]),
                    "completion_tokens": int(r[3]),
                    "total_tokens": int(r[4]),
                }
                for r in by_operation
            ],
            "by_model": {r[0]: int(r[1]) for r in by_model},
        }

    # -- agent learnings flag --------------------------------------------
    def get_agent_has_learnings(self, agent_id: str) -> bool:
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT has_learnings FROM agent_learnings WHERE agent_id = %s",
                [agent_id],
            ).fetchone()
        return bool(row[0]) if row is not None else False

    def set_agent_has_learnings(self, agent_id: str, has_learnings: bool = True) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                """
                INSERT INTO agent_learnings (agent_id, has_learnings)
                VALUES (%s, %s)
                ON CONFLICT (agent_id) DO UPDATE SET
                    has_learnings = EXCLUDED.has_learnings,
                    updated_at = now()
                """,
                [agent_id, has_learnings],
            )
