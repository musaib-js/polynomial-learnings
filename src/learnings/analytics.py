"""Dashboard analytics: growth rollups and retrieval-usage trends.

Two different data sources, two different techniques (see the SaaS plan §7):

* Learnings growth (totals by status/scope, daily/weekly/monthly counts) is
  fully derivable from ``learnings.created_at``/``status``/``scope`` — no new
  table needed, just ``GROUP BY date_trunc(...)`` (backed by the
  ``learnings_agent_created_idx`` index added in the Alembic migration).
* Retrieval usage (frequency/trend, most-used, recently-retrieved) needs the
  new ``learning_events`` table (populated by ``HybridRetriever._touch()``'s
  optional ``event_recorder`` — see ``retriever.py`` and ``api/deps.py``),
  since ``hits``/``last_used_at`` are a running counter and a single
  timestamp, not a time series.

Real-time SQL aggregation for now (see plan §7 for the precomputed-rollup
upgrade path once volume warrants it — not needed yet, and there's no
scheduler/worker infra in this repo to run one).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .backend import VectorStoreBackend

_BUCKETS = {"day": "day", "week": "week", "month": "month"}


def _trunc(bucket: str) -> str:
    return _BUCKETS.get(bucket, "day")


def learnings_growth(
    backend: "VectorStoreBackend", agent_id: str, bucket: str = "day"
) -> dict:
    """Counts by status/scope, plus a time-bucketed growth series.

    ``backend`` must be a ``PgVectorBackend`` (the only concrete
    implementation today) — this reaches into its connection pool directly,
    mirroring the same escape hatch used by
    ``dashboard_routes.py::_list_cross_entity``, since these aggregate
    queries are dashboard-specific and don't belong on the general-purpose
    ``VectorStoreBackend`` Protocol.
    """
    from .pgvector_backend import PgVectorBackend

    if not isinstance(backend, PgVectorBackend):
        raise TypeError("learnings_growth requires a PgVectorBackend")

    trunc = _trunc(bucket)
    with backend._pool.connection() as conn:  # noqa: SLF001
        totals = conn.execute(
            """
            SELECT
                count(*) AS total,
                count(*) FILTER (WHERE scope = 'personal') AS personal,
                count(*) FILTER (WHERE scope = 'global') AS global,
                count(*) FILTER (WHERE status = 'active') AS approved,
                count(*) FILTER (WHERE status = 'pending_approval') AS pending,
                count(*) FILTER (WHERE status = 'rejected') AS rejected
            FROM learnings WHERE agent_id = %s
            """,
            [agent_id],
        ).fetchone()

        series = conn.execute(
            """
            SELECT date_trunc(%s, created_at) AS bucket, count(*) AS created
            FROM learnings
            WHERE agent_id = %s
            GROUP BY bucket
            ORDER BY bucket ASC
            """,
            [trunc, agent_id],
        ).fetchall()

    return {
        "total": totals[0],
        "personal": totals[1],
        "global": totals[2],
        "approved": totals[3],
        "pending": totals[4],
        "rejected": totals[5],
        "series": [{"bucket": row[0].isoformat(), "created": row[1]} for row in series],
    }


def usage_trends(
    backend: "VectorStoreBackend", agent_id: str, bucket: str = "day", top_n: int = 10
) -> dict:
    """Retrieval frequency/trend, most-used, and recently-retrieved learnings.

    Reads the new ``learning_events`` table (see module docstring) rather
    than ``learnings.hits``/``last_used_at``, which cannot answer "how many
    retrievals per day" (a time series) or "which N were retrieved most
    recently" (an ordered event log), only "how many total" and "when last".
    """
    from .pgvector_backend import PgVectorBackend

    if not isinstance(backend, PgVectorBackend):
        raise TypeError("usage_trends requires a PgVectorBackend")

    trunc = _trunc(bucket)
    with backend._pool.connection() as conn:  # noqa: SLF001
        series = conn.execute(
            """
            SELECT date_trunc(%s, occurred_at) AS bucket, count(*) AS retrievals
            FROM learning_events
            WHERE agent_id = %s AND event_type = 'retrieved'
            GROUP BY bucket
            ORDER BY bucket ASC
            """,
            [trunc, agent_id],
        ).fetchall()

        most_used = conn.execute(
            """
            SELECT learning_id, count(*) AS retrievals
            FROM learning_events
            WHERE agent_id = %s AND event_type = 'retrieved'
            GROUP BY learning_id
            ORDER BY retrievals DESC
            LIMIT %s
            """,
            [agent_id, top_n],
        ).fetchall()

        recent = conn.execute(
            """
            SELECT DISTINCT ON (learning_id) learning_id, occurred_at
            FROM learning_events
            WHERE agent_id = %s AND event_type = 'retrieved'
            ORDER BY learning_id, occurred_at DESC
            """,
            [agent_id],
        ).fetchall()
        recent_sorted = sorted(recent, key=lambda r: r[1], reverse=True)[:top_n]

    return {
        "series": [
            {"bucket": row[0].isoformat(), "retrievals": row[1]} for row in series
        ],
        "most_used": [
            {"learning_id": str(row[0]), "retrievals": row[1]} for row in most_used
        ],
        "recently_retrieved": [
            {"learning_id": str(row[0]), "occurred_at": row[1].isoformat()}
            for row in recent_sorted
        ],
    }
