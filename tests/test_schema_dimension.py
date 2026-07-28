"""``init_schema`` guards against an embedder/table dimension mismatch.

Set ``DATABASE_URL`` to run these, e.g.::

    export DATABASE_URL=postgresql://polynomial:polynomial@localhost:5433/learnings
    pytest tests/test_schema_dimension.py

Non-destructive: the mismatching call hits ``CREATE TABLE IF NOT EXISTS`` (a
no-op) and then only reads, so the shared table is never altered.
"""

from __future__ import annotations

import os

import pytest

from learnings import HuggingFaceEmbedder, SchemaDimensionError, init_schema

DSN = os.environ.get("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DSN, reason="DATABASE_URL not set")

EMBEDDER = HuggingFaceEmbedder()


@pytest.fixture(scope="module", autouse=True)
def _schema():
    """Establish the table at the real dimension before anything else.

    Ordering matters: if the mismatching test ran against a database with no
    ``learnings`` table, it would *create* one at the wrong width and poison
    every other suite.
    """
    init_schema(DSN, EMBEDDER.dimension)


def test_matching_dimension_is_idempotent():
    init_schema(DSN, EMBEDDER.dimension)
    init_schema(DSN, EMBEDDER.dimension)


def test_mismatched_dimension_raises():
    wrong_dim = EMBEDDER.dimension + 1
    with pytest.raises(SchemaDimensionError) as exc_info:
        init_schema(DSN, wrong_dim)

    # The message must name both widths — that's the whole point of failing here
    # instead of letting the first insert blow up deep inside psycopg.
    message = str(exc_info.value)
    assert str(wrong_dim) in message
    assert str(EMBEDDER.dimension) in message
