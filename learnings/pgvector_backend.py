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
from .models import Learning, Outcome, Scope, Status

_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema.sql"

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
            conn.execute(
                f"UPDATE learnings SET {assignments} WHERE id = %s", params
            )

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
