# polynomial-learnings

A framework-agnostic long-term **learning** module for AI agents. This repo
implements the **vector ingestion and retrieval** foundation from the solution
design: durable learnings are embedded and stored in Postgres + pgvector, and
retrieved by hybrid (semantic + keyword) relevance search with strict
per-entity isolation.

> Scope of this deliverable: raw ingestion (embed → upsert) and hybrid
> retrieval only. Curation (the judge-model novelty / worth-keeping gate) is
> designed for but not yet built — it slots into `LearningManager.record`.

## Concepts

- **agent_id** — which agent a learning belongs to.
- **entity_id** — who a *personal* learning belongs to (user / tenant / bot id).
- **scope** — `personal` (visible only to that entity) or `global` (visible to all).
- **Learning** — `context` + `content` (embedded), plus outcome, tags, and
  ranking signals. See [`models.py`](learnings/models.py).

Isolation is enforced as a SQL **pre-filter** (`agent_id`, and `scope=global`
OR `entity_id=<this>`) applied before ranking — a personal learning of one
entity is never a candidate for another.

## Quickstart

```bash
pip install -e '.[dev,huggingface]'

# 1. Start Postgres with pgvector
docker compose up -d

export DATABASE_URL=postgresql://polynomial:polynomial@localhost:5433/learnings
```

```python
from learnings import (
    HuggingFaceEmbedder, PgVectorBackend, LearningManager, init_schema, Scope, Outcome,
)

# Real embeddings from a Hugging Face sentence-transformer (all-MiniLM-L6-v2, 384 dims).
embedder = HuggingFaceEmbedder()
init_schema(DATABASE_URL, embedder.dimension)

backend = PgVectorBackend(DATABASE_URL)
manager = LearningManager(agent_id="insights-bot", backend=backend, embedder=embedder)

# Ingest
manager.record(
    context="user asks for revenue by region",
    content="join orders to regions on region_id",
    entity_id="acme-corp",
    outcome=Outcome.positive,
)
manager.record(
    context="any user asks about the fiscal year",
    content="fiscal year starts in April",
    scope=Scope.global_,
)

# Retrieve (hybrid, isolated to this entity + globals)
learnings = manager.retrieve(query="revenue by region", entity_id="acme-corp")
print(manager.format_for_prompt(learnings))
```

## Architecture

| Component | Responsibility |
|-----------|----------------|
| `LearningManager` | Single entry point: `record`, `retrieve`, `format_for_prompt`. |
| `HybridRetriever` | Semantic + keyword search fused with Reciprocal Rank Fusion. |
| `Embedder` | Pluggable text→vector. `HuggingFaceEmbedder` (default, sentence-transformers). |
| `VectorStoreBackend` | Pluggable storage contract. `PgVectorBackend` implements it. |

Everything above `VectorStoreBackend` is storage-agnostic; swapping the vector
engine is a config change.

## PydanticAI adapter

```python
from learnings.adapters.pydantic_ai import register_tools

register_tools(agent, manager, entity_id_resolver=lambda ctx: ctx.deps.tenant_id)
```

Exposes `store_learning` and `get_learnings` as agent tools; the
`entity_id_resolver` lets the host app decide "who this is for."

## Tests

```bash
docker compose up -d
export DATABASE_URL=postgresql://polynomial:polynomial@localhost:5432/learnings
pytest
```

Tests use `HuggingFaceEmbedder` (downloads the model once, then runs offline)
and cover ingestion, retrieval, personal/global isolation, hybrid fusion, and
hit tracking.
