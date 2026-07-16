"""Confirms BAAI/bge-small-en-v1.5 is a drop-in for the existing
HuggingFaceEmbedder — same 384-dim output as the current all-MiniLM-L6-v2
default, so schema.sql (`vector(384)`) needs no change.

This is a config choice (``HuggingFaceEmbedder(model=...)``), not a change
to the class default — the default stays whatever the retrieval-engine
owner has already benchmarked against. See AGENT.md / DATABASE_DESIGN.md
discussion and the plan's open question on this.

Downloads the model on first run, then cached; requires the `huggingface`
extra like the rest of the embedder tests.
"""

from __future__ import annotations

from learnings.embedder import HuggingFaceEmbedder


def test_bge_small_matches_current_384_dim_schema():
    embedder = HuggingFaceEmbedder(model="BAAI/bge-small-en-v1.5")
    assert embedder.dimension == 384


def test_bge_small_embed_is_normalized_and_batched():
    embedder = HuggingFaceEmbedder(model="BAAI/bge-small-en-v1.5")
    vectors = embedder.embed(["always format currency as $X.XX", "unrelated sentence"])
    assert len(vectors) == 2
    assert all(len(v) == 384 for v in vectors)
    # normalize_embeddings=True in HuggingFaceEmbedder.embed -> unit vectors.
    magnitude = sum(x * x for x in vectors[0]) ** 0.5
    assert abs(magnitude - 1.0) < 1e-4
