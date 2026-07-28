# polynomial-learnings

A framework-agnostic long-term memory library for AI agents, built on
PostgreSQL + pgvector.

`polynomial-learnings` gives an agent a durable, curated store of **learnings**
— short, generalisable lessons drawn from past conversations ("this user wants
amounts written as `1200 USD`, never `$1200`") — and hands the relevant ones
back on the next turn. It covers the whole loop:

- **record** a lesson directly — embed it and store it, no LLM involved
- **retrieve** the lessons relevant to a conversation, by hybrid
  semantic + keyword search, fused and optionally reranked
- **persist** a conversation through an LLM **judge** that decides whether it
  contains a durable lesson at all, and whether that lesson is new, a
  duplicate, a refinement, or a contradiction of something already stored
- **manage** what was stored — list, patch, approve, disapprove, soft-delete
- **measure** it — per-agent learning statistics and per-model token spend
- **isolate** it — every read is pre-filtered by agent and entity in SQL,
  before any ranking runs

It is a library first: import `LearningManager` and call it in-process. An
optional FastAPI server and a thin HTTP client ship alongside, for the two-tier
deployment where the embedder, judge, and database live on a server and the
agent carries none of that weight.

---

## Install

Which extra you need depends on which side of the wire you are on.

**Agent side (the thin SDK)** — talks HTTP and nothing else:

```bash
pip install "polynomial-learnings[pydantic-ai]"       # PydanticAI adapter + httpx client
pip install "polynomial-learnings[client]"            # just the httpx thin client
```

**Server side** — runs the embedder, judge, and database:

```bash
pip install "polynomial-learnings[api]"               # FastAPI/uvicorn + Postgres driver
pip install "polynomial-learnings[huggingface]"       # sentence-transformers embedder & reranker
pip install "polynomial-learnings[groq]"              # Groq-backed judge (curated persist)
pip install "polynomial-learnings[server]"            # just the Postgres/pgvector stack
pip install "polynomial-learnings[all]"               # everything
```

`pydantic` is the only hard dependency. Everything else — the Postgres driver
included — is an opt-in extra, so an agent process installing the SDK does
**not** get `psycopg`, `torch`, or `fastapi`. Model- and provider-backed classes
import their dependency lazily inside `__init__`, and `PgVectorBackend` /
`init_schema` are resolved lazily off the package root, so `import learnings`
stays cheap regardless of what is installed.

Each layer has a pluggable protocol and a shipped implementation, so the extras
are genuinely optional — bring your own `Embedder`, `Judge`, `Reranker`, or
`VectorStoreBackend` and install nothing beyond the core.

---

## Required setup: Postgres with pgvector

The one piece of infrastructure this library needs is a Postgres database with
the `vector` extension available.

```bash
docker run -d --name learnings-pg -p 5433:5432 \
  -e POSTGRES_USER=polynomial -e POSTGRES_PASSWORD=polynomial -e POSTGRES_DB=learnings \
  pgvector/pgvector:pg16

export DATABASE_URL=postgresql://polynomial:polynomial@localhost:5433/learnings
```

Then create the schema once, with the **dimension of the embedder you intend to
use** — the `embedding` column is typed `vector(dim)` and a mismatch is a hard
error at insert time, not a silent degradation:

```python
from learnings import HuggingFaceEmbedder, init_schema

embedder = HuggingFaceEmbedder()          # all-MiniLM-L6-v2 -> 384 dims
init_schema(DATABASE_URL, embedder.dimension)
```

`init_schema()` is idempotent (`CREATE ... IF NOT EXISTS` throughout) and reads
`schema.sql` from inside the installed package, so it works from a wheel as
well as from a checkout. It creates three tables — `learnings`, `token_usage`,
`agent_learnings` — and their indexes; see
[Storage schema](#storage-schema) for the full layout.

Optional environment variables:

| Variable           | Used by                        | Meaning                                                    |
| ------------------ | ------------------------------ | ---------------------------------------------------------- |
| `DATABASE_URL`     | `PgVectorBackend`, API         | Postgres DSN. Required. The only setting with no default.  |
| `GROQ_API_KEY`     | `GroqJudge`, API               | Enables the curated persist path. Without it, `/persist` returns 503. |
| `LEARNINGS_API_KEY`| API                            | Requires `Authorization: Bearer <key>` on every `/v1` route. Unset leaves the API open. |
| `EMBEDDER_MODEL`   | API                            | Override the sentence-transformers model. Needs a database whose vector column matches the new dimension. |
| `RERANKER_MODEL`   | API                            | Override the cross-encoder model. Defaults to the class default. |
| `RERANK_THRESHOLD` | API                            | Relevance cutoff after reranking. Default `0.52`.          |

---

## Quick start

```python
from learnings import (
    HuggingFaceEmbedder, PgVectorBackend, LearningManager,
    init_schema, Scope, Outcome,
)

embedder = HuggingFaceEmbedder()
init_schema(DATABASE_URL, embedder.dimension)

backend = PgVectorBackend(DATABASE_URL)
manager = LearningManager(agent_id="insights-bot", backend=backend, embedder=embedder)

# Ingest — a personal lesson, scoped to one entity
manager.record(
    context="user asks for revenue by region",
    content="join orders to regions on region_id",
    entity_id="acme-corp",
    outcome=Outcome.positive,
    category="sql",
    tags=["revenue", "regions"],
)

# Ingest — a global lesson, true for every user of this agent
manager.record(
    context="any user asks about the fiscal year",
    content="fiscal year starts in April",
    scope=Scope.global_,
)

# Retrieve — hybrid search, pre-filtered to this entity's personal + all global
learnings = manager.retrieve(query="revenue by region", entity_id="acme-corp")
print(manager.format_for_prompt(learnings))
# Relevant learnings from past interactions:
# - When user asks for revenue by region: join orders to regions on region_id
```

`LearningManager` is bound to a single `agent_id` at construction. It is cheap
to build — construct one per request if that suits you — while the expensive
objects (the embedder's model weights, the connection pool) are the ones you
hold onto and share.

---

## Concepts

**agent_id** — which agent a learning belongs to. Every query is filtered by
it; there is no cross-agent read path at all.

**entity_id** — who a *personal* learning belongs to: a user, tenant, customer,
or bot id. The host application decides what an entity is; the library only
ever compares the string.

**scope** — `personal` (visible only to that one entity) or `global` (visible
to every entity of this agent). A `global` learning always has
`entity_id = NULL`; a `personal` learning always has one.

**Learning** — the unit of storage. `context` + `content` are the semantic
payload and the only fields that get embedded and full-text indexed; everything
else travels as metadata used for isolation, filtering, ranking, and audit.

**status** — `active` (retrievable), `superseded` (replaced by a contradiction),
or `rejected` (disapproved or soft-deleted). Only `active` rows are ever
retrieved. Nothing is hard-deleted, so the history stays auditable.

### Isolation is a pre-filter, not a post-filter

Every search applies this in the SQL `WHERE` clause, **before** any similarity
or keyword ranking touches a row:

```sql
agent_id = :agent_id
AND status = 'active'
AND (scope = 'global' OR entity_id = :entity_id)
```

A personal learning of one entity is never a *candidate* for another's query,
so it can never be ranked, never partially leak through a scoring bug, and
never consume a slot in the candidate pool. When no `entity_id` is supplied,
the clause collapses to `scope = 'global'` — an anonymous caller sees globals
only, by construction.

The same rule holds on the write path: the judge chooses a learning's `scope`,
but the **curator** — not the LLM — resolves `entity_id` from it. A `global`
verdict forces `entity_id = None` regardless of the request; a `personal`
verdict requires the caller-supplied `entity_id` and rejects the whole persist
if it is missing, rather than silently writing a global. Isolation stays
structural, never dependent on the model getting it right.

---

## The core operations

| Method                                          | LLM call? | Writes?      | Use for                                                       |
| ----------------------------------------------- | --------- | ------------ | ------------------------------------------------------------- |
| `record(context, content, ...)`                 | No        | Yes          | Direct ingestion when you already know the lesson is worth keeping |
| `retrieve(query, entity_id, limit)`             | No        | Touches hits | Loading context before an agent turn                          |
| `retrieve_for_conversation(messages, ...)`      | No        | Touches hits | Same, from a conversation snapshot instead of a query string  |
| `persist_from_conversation(messages, ...)`      | **Yes**   | Yes          | Curated write: let the judge decide if there's a lesson here   |
| `list_learnings(scope, entity_id, limit, offset)` | No      | No           | Showing a user everything stored about them                   |
| `get_learning(id)`                              | No        | No           | Fetching one learning (isolation-checked)                     |
| `update_learning(id, **fields)`                 | No        | Yes          | Human edits; re-embeds if the text changed                     |
| `approve_learning(id)`                          | No        | Yes          | Review workflow — mark `active`                                |
| `disapprove_learning(id)`                       | No        | Yes          | Review workflow — mark `rejected`                              |
| `delete_learning(id)`                           | No        | Yes          | Soft-delete — mark `rejected`, row retained for audit          |
| `stats(top_n)`                                  | No        | No           | Per-agent learning statistics                                  |
| `token_stats()`                                 | No        | No           | Per-agent model spend                                          |
| `format_for_prompt(learnings)`                  | No        | No           | Rendering retrieved learnings into a system prompt             |

### `record()` — the raw write path

```python
learning = manager.record(
    context="user asks how to format currency",
    content="never use the $ symbol; write USD after the amount",
    entity_id="acme-corp",              # required unless scope=Scope.global_
    scope=Scope.personal,               # default
    outcome=Outcome.positive,
    category="formatting",
    tags=["currency", "usd"],
    reason="user corrected the assistant twice",
)
```

No judging, no duplicate check — exactly what you asked for is embedded and
stored. `record()` raises `ValueError` if `scope=personal` and no `entity_id`
is given, since that would produce a learning nobody can retrieve.

### `retrieve()` — the read path

```python
learnings = manager.retrieve(query="how should I write money amounts?",
                             entity_id="acme-corp", limit=5)

# or straight from a conversation snapshot:
from learnings import Message

learnings = manager.retrieve_for_conversation(
    [Message(role="user", content="how should I write money amounts?")],
    entity_id="acme-corp",
)
```

Retrieval runs semantic and keyword search in parallel over the same
pre-filtered rows, fuses the two rankings, optionally reranks them with a
cross-encoder, and touches (`hits += 1`, `last_used_at = now()`) exactly what
it returns — so the frequency/recency signals only reward learnings that were
actually surfaced. See [The retrieval pipeline](#the-retrieval-pipeline).

`retrieve_for_conversation()` flattens every non-empty message into one query
string, then calls `retrieve()`.

### `persist_from_conversation()` — the curated write path

```python
from learnings import GroqJudge, Message

manager = LearningManager(
    agent_id="insights-bot", backend=backend, embedder=embedder,
    judge=GroqJudge(),                  # curation is opt-in: no judge, no persist
)

result = manager.persist_from_conversation(
    messages=[
        Message(role="user", content="don't use the $ symbol"),
        Message(role="assistant", content="Understood — I'll write USD instead."),
        Message(role="user", content="yes, always write USD after the amount"),
    ],
    entity_id="acme-corp",
)

result.decision       # "persisted" | "rejected"
result.verdict        # new | same | refine | contradict | reject
result.learning_id    # the row that now holds this lesson
result.superseded_id  # set only for verdict=contradict
result.reason         # the judge's explanation, on a reject
```

Only `role == "user"` messages reach the judge, and only the last four of them
by default (`LearningCurator(max_messages=...)`) — assistant turns are the
agent's own output, not evidence about the user. A conversation with no user
messages is rejected without an LLM call at all.

Calling `persist_from_conversation()` on a manager built without a `judge` (or
an explicit `curator`) raises `ValueError`: there is nothing to curate with, and
silently falling back to `record()` would store every conversation verbatim.

### Management and review

```python
manager.get_learning(learning_id)                    # None if another agent owns it
manager.list_learnings(Scope.personal, entity_id="acme-corp", limit=50, offset=0)
manager.list_learnings(Scope.global_)

manager.update_learning(learning_id, content="write USD after the amount", tags=["currency"])
manager.approve_learning(learning_id)                # -> status=active
manager.disapprove_learning(learning_id)             # -> status=rejected
manager.delete_learning(learning_id)                 # soft delete -> status=rejected
```

`update_learning()` accepts only `context`, `content`, `category`, `tags`,
`reason`, and `outcome`. The isolation and lifecycle columns — `id`,
`agent_id`, `entity_id`, `scope`, `created_at`, `hits` — are deliberately not
patchable, so an edit can never move a learning across an isolation boundary or
forge its ranking signals. Editing `context` or `content` re-embeds the row, so
the stored vector never drifts out of sync with the text it claims to
represent; the full-text column is `GENERATED ALWAYS`, so Postgres keeps that
half in sync on its own.

Every one of these resolves the learning through `get_learning()` first, which
returns `None` when the row belongs to a different agent — so a wrong id and
someone else's id are indistinguishable to the caller, and both read as "not
found".

### Statistics and token accounting

```python
stats = manager.stats(top_n=5)
stats.total, stats.by_status, stats.by_scope        # {'active': 12, ...}, {'personal': 9, ...}
stats.total_hits, stats.avg_hits
stats.distinct_entities
stats.last_used_at, stats.last_created_at
stats.most_used                                      # [MostUsedLearning(id, context, content, hits), ...]

tokens = manager.token_stats()
tokens.total_calls, tokens.total_tokens
tokens.by_operation                                  # [OperationTokenTotals(operation="judge", calls=..., ...)]
tokens.by_model                                      # {"openai/gpt-oss-20b": 18422}
```

Token accounting records one row per model call that reports usage — currently
the judge. Local operations (the sentence-transformer embedder, the
cross-encoder reranker) burn no billable tokens and are deliberately not
recorded. Recording is best-effort: a failure to write the usage row is logged
and swallowed, never allowed to sink an otherwise-successful persist, because
accounting is observability and not correctness.

---

## Architecture

```mermaid
flowchart TD
    subgraph ENTRY["Entry points"]
        MGR["LearningManager<br/>(learnings.manager)<br/><br/>record() · retrieve() · persist_from_conversation()<br/>list/get/update/approve/disapprove/delete<br/>stats() · token_stats() · format_for_prompt()"]
        API["FastAPI app<br/>(learnings.api)<br/>optional"]
        CLIENT["LearningClient<br/>(learnings.client)<br/>optional, HTTP"]
        ADAPT["PydanticAI adapter<br/>(learnings.adapters)<br/>optional"]
    end

    subgraph READ["Retrieval — learnings.retriever"]
        VEC["vector_search()<br/>cosine / HNSW"]
        KW["keyword_search()<br/>tsvector / GIN"]
        RRF["reciprocal_rank_fusion()<br/>weighted 1/(k+rank)"]
        RERANK["Reranker (optional)<br/>CrossEncoderReranker<br/>+ threshold gate"]
        TOUCH["touch()<br/>hits++ · last_used_at"]

        VEC --> RRF
        KW --> RRF
        RRF --> RERANK
        RERANK --> TOUCH
    end

    subgraph WRITE["Curation — learnings.curator"]
        PROMPT["build_judge_prompt()<br/>(learnings.prompts)"]
        JUDGE["Judge<br/>GroqJudge · FakeJudge<br/>-> JudgeVerdict"]
        DISPATCH["dispatch on verdict<br/>new · same · refine<br/>contradict · reject"]
        RESOLVE["_resolve_entity_id()<br/>scope -> entity, deterministic"]

        PROMPT --> JUDGE --> DISPATCH --> RESOLVE
    end

    EMB["Embedder<br/>(learnings.embedder)<br/>HuggingFaceEmbedder"]

    subgraph STORE["VectorStoreBackend — learnings.backend"]
        PG["PgVectorBackend<br/>psycopg 3 + ConnectionPool"]
        DB[("Postgres + pgvector<br/><br/>learnings · token_usage<br/>agent_learnings")]
        PG --> DB
    end

    ADAPT --> MGR
    ADAPT --> CLIENT
    CLIENT -->|"HTTP /v1"| API
    API --> MGR

    MGR -->|"retrieve()"| READ
    MGR -->|"persist_from_conversation()"| WRITE
    MGR -->|"record() · update() · stats()"| STORE

    READ -->|"query vector"| EMB
    WRITE -->|"neighbour search"| READ
    WRITE -->|"learning vector"| EMB
    READ --> STORE
    WRITE --> STORE
    EMB -.->|"vectors"| STORE
```

Every layer between `LearningManager` and the database is a `Protocol` with at
least one shipped implementation and one test double. Nothing in the core
imports `psycopg`, `sentence_transformers`, `groq`, or `fastapi` directly —
those live behind `VectorStoreBackend`, `Embedder`, `Judge`, and the optional
`api` package respectively.

### Components

**`LearningManager`** (`learnings.manager`) is the single public entry point
and the only class most callers import. It is bound to one `agent_id`, owns a
`VectorStoreBackend`, an `Embedder`, a `HybridRetriever`, and — when a `Judge`
is supplied — a `LearningCurator`. It holds no state of its own beyond those
references. A manager built without a judge is a fully functional
retrieval-and-management object with zero curation overhead; that is the
default, because retrieval routes should never require an LLM provider to be
configured.

**`Learning`** (`learnings.models`) is the pydantic model at the centre of
everything. Two of its methods matter architecturally:

- `embedding_text()` → `"{context} {content}"`. This is what gets embedded and
  full-text indexed. It is deliberately frozen: stored vectors were computed
  from exactly this string, so changing it would silently invalidate every
  existing embedding in the database without any migration noticing.
- `rerank_text()` → a structured block (`Situation:` / `Lesson:` / `Category:` /
  `Tags:`). This is what a cross-encoder scores against the query. Because it
  is computed from the row at query time rather than stored, enriching it
  applies to every existing learning immediately, with no re-embedding. The
  enrichment is not cosmetic: measured on `ms-marco-MiniLM-L-6-v2`, adding
  category/tag metadata moved a query like "currency formatting" against a
  lesson whose body uses neither word from a raw logit of −7.5 to +2.9.

**`Embedder`** (`learnings.embedder`) is a two-method protocol — `dimension`
and `embed(texts) -> list[list[float]]` — used identically on the write and read
paths, which is what guarantees query and document vectors live in the same
space. `HuggingFaceEmbedder` ships as the default: `all-MiniLM-L6-v2` (384
dims), downloaded once and then fully offline, with `normalize_embeddings=True`
so cosine distance in pgvector is well-behaved. Pass any other
sentence-transformers model name to swap it (or set `EMBEDDER_MODEL` for the
API) — and point it at a fresh database if the dimension changes. Against a
database whose table was built at a different width, `init_schema()` raises
`SchemaDimensionError` instead of silently doing nothing: every statement in
`schema.sql` is `IF NOT EXISTS`, so the mismatch would otherwise go unnoticed
until the first read or write failed.

**`HybridRetriever`** (`learnings.retriever`) owns the whole read pipeline:
embed the query, run both searches, fuse, optionally rerank and threshold,
touch, return. All ranking policy lives here rather than in the individual
components — the `Reranker` protocol, for instance, only *scores*; sorting,
thresholding, and cut-off stay the retriever's job so the policy exists in
exactly one place.

**`Reranker`** (`learnings.reranker`) is the optional precision stage.
`CrossEncoderReranker` scores each `(query, document)` pair *jointly* through a
transformer, which is a materially stronger relevance signal than the cosine
similarity between two *independently* computed embeddings that produced the
candidates. That is the whole point of a retrieve-then-rerank pipeline: a cheap
wide first pass for recall, an expensive precise second pass over a small
candidate set. Default model `mixedbread-ai/mxbai-rerank-base-v1` (Apache 2.0,
~184M params, CPU-tractable, loadable through the same `sentence-transformers`
dependency, so it adds none of its own). Scores are sigmoid-normalised to
[0, 1] by default. `FakeReranker` returns scripted scores with no model load.

**`Judge`** (`learnings.judge`) takes a prompt, returns a `JudgeVerdict` —
symmetric with `Embedder`, and the only place an LLM is ever called.
`GroqJudge` uses schema-enforced structured output (constrained decoding) on
models that support it, falls back to JSON-object mode on those that don't, and
validates the result through pydantic either way with a retry. `FakeJudge`
returns a scripted verdict — it ships in the package rather than in the test
suite so SDK consumers can test their own integrations against it too.

**`LearningCurator`** (`learnings.curator`) is the decision engine behind the
curated write: it assembles the prompt, runs the judge, records the token spend,
and turns the verdict into the correct database write. It reuses the *same*
`HybridRetriever` the read path uses to fetch the neighbours the judge compares
against — never a private query — so novelty is judged against exactly what a
real retrieval would have surfaced.

**`VectorStoreBackend`** (`learnings.backend`) is the storage contract the core
depends on exclusively, which is what makes the database swappable without
touching retrieval, curation, or embedding code:

| Method                                          | Purpose                                                        |
| ----------------------------------------------- | -------------------------------------------------------------- |
| `upsert(learning, embedding)`                   | Insert or replace a learning and its vector                    |
| `vector_search(query_embedding, flt, top_k)`    | Nearest by cosine similarity, `(learning, score)` pairs         |
| `keyword_search(query_text, flt, top_k)`        | Best by full-text match, `(learning, score)` pairs              |
| `list(flt, limit, offset)`                      | Unranked listing, most recently used first                      |
| `get(learning_id)`                              | Fetch one row, or `None`                                        |
| `update(learning_id, **fields)`                 | Patch stored columns (hits, status, timestamps, ...)            |
| `stats(agent_id, top_n)`                        | Aggregate counts + most-used rows for one agent                 |
| `list_agents()`                                 | Derived roster of every agent the store has seen                |
| `record_token_usage(record)`                    | Persist one token-consumption event                             |
| `token_usage_stats(agent_id)`                   | Aggregate spend by operation and model                          |
| `get_agent_has_learnings(agent_id)`             | Fast "is this agent brand new?" check                           |
| `set_agent_has_learnings(agent_id, value)`      | Idempotent flag upsert                                          |

Implementing all twelve against another vector engine is the entire cost of
swapping storage; `LearningManager` needs no changes. `SearchFilter` — a plain
`dict` of `agent_id` / `entity_id` / `scope` / `status` — is what a backend
translates into its own isolation pre-filter, and applying it before ranking is
part of the contract, not an optimisation.

**`PgVectorBackend`** (`learnings.pgvector_backend`) is the shipped
implementation: psycopg 3 over a `ConnectionPool` (autocommit, with the pgvector
adapter registered on every pooled connection, so it is safe under concurrent
API requests). Vector search is `1 - (embedding <=> query)` ordered by the HNSW
index; keyword search is `ts_rank(search_tsv, plainto_tsquery('english', q))`
over the GIN index. Both share the identical `_where()` clause — one function,
so the two search paths cannot drift apart on isolation.

---

## The retrieval pipeline

```mermaid
sequenceDiagram
    autonumber
    participant C as Caller
    participant M as LearningManager
    participant R as HybridRetriever
    participant E as Embedder
    participant B as PgVectorBackend
    participant K as Reranker

    C->>M: retrieve(query, entity_id, limit=5)
    M->>R: retrieve(agent_id, query, entity_id, limit)
    Note over R: candidate_k = max(4 × limit, limit)
    R->>E: embed([query])
    E-->>R: query vector

    par semantic
        R->>B: vector_search(vector, filter, candidate_k)
        B-->>R: [(learning, cosine), ...]
    and keyword
        R->>B: keyword_search(query, filter, candidate_k)
        B-->>R: [(learning, ts_rank), ...]
    end
    Note over B: both queries share the same<br/>agent + scope + status pre-filter

    R->>R: reciprocal_rank_fusion([semantic, keyword])
    Note over R: score = Σ weight / (k + rank), k=60<br/>ties broken by last_used_at, then hits

    alt reranker configured
        R->>K: score(query, candidates)
        K-->>R: one score per candidate
        Note over R: best score < threshold -> return []<br/>else keep individual survivors, capped at limit
    else no reranker (default)
        Note over R: take the top `limit` fused candidates
    end

    R->>B: update(id, hits+1, last_used_at) for each result
    R-->>M: [Learning, ...]
    M-->>C: [Learning, ...]
```

**Why hybrid.** Semantic search finds paraphrases that share no words with the
stored lesson; keyword search reliably nails exact identifiers, error codes, and
proper nouns that an embedding blurs. Neither alone is enough, and RRF fuses
them without needing their scores to be commensurable — it uses only each
item's *rank* in each list, so a cosine similarity of 0.83 and a `ts_rank` of
0.09 combine meaningfully. `k = 60` is the value from the original RRF paper; it
damps how much being #1 in one list dominates. Ties fall back to recency and
then hit count, so a learning that keeps proving useful edges out one that
never has.

**Why `candidate_k = 4 × limit`.** Fusion needs a candidate pool wider than the
final result set to have anything to fuse; pulling exactly `limit` from each
search would mean the two lists mostly agree by construction.

**The rerank gate is two-stage, on purpose.** If the single best-scoring
candidate does not clear `rerank_threshold`, the call returns `[]` — nothing
here is relevant enough, and returning the least-bad option would inject noise
into the agent's prompt. If it does clear, only candidates that *individually*
clear the threshold survive: a strong top match never drags mediocre ones along
with it. Rejected candidates are never touched, so their `hits` do not inflate.

**Threshold calibration.** The default `0.52` is measured against
`mxbai-rerank-base-v1` on its sigmoid scale, not guessed: irrelevant queries
land consistently at ~0.50–0.503, while realistic-but-terse relevant queries can
land as low as ~0.545. A tighter `0.55` was tried first and clipped a genuinely
relevant query at 0.5467. If you plug in a reranker with a different scale, pass
your own threshold. One honest limitation, documented rather than hidden:
maximally abstract paraphrases sharing zero vocabulary with the stored text can
score in the same ~0.50 band as true negatives — no threshold value separates
those two cases.

---

## The curation pipeline

```mermaid
sequenceDiagram
    autonumber
    participant C as Caller
    participant M as LearningManager
    participant CU as LearningCurator
    participant B as Backend
    participant R as HybridRetriever
    participant J as Judge

    C->>M: persist_from_conversation(messages, entity_id)
    M->>CU: persist(agent_id, messages, entity_id)

    CU->>CU: keep role=="user" messages, last max_messages (4)
    alt no user messages
        CU-->>C: rejected — no LLM call made
    end

    CU->>B: get_agent_has_learnings(agent_id)
    alt agent has learnings
        CU->>R: retrieve(agent_id, flattened query, entity_id, top_k=5)
        R-->>CU: neighbours
    else brand-new agent
        Note over CU: skip the neighbour search entirely
    end

    CU->>J: evaluate(build_judge_prompt(messages, neighbours))
    J-->>CU: JudgeVerdict(verdict, related_learning_id?, learning?)
    CU->>B: record_token_usage(...) — best effort

    alt verdict = reject
        CU-->>C: rejected(reason)
    else verdict = same
        CU->>B: update(existing, hits+1, last_used_at)
        CU-->>C: persisted(same, existing.id)
    else verdict = refine
        CU->>CU: existing.model_copy(update=generated fields)
        CU->>B: upsert(merged, new embedding)
        CU-->>C: persisted(refine, existing.id)
    else verdict = contradict
        CU->>B: update(existing, status='superseded')
        CU->>B: upsert(new learning, supersedes=existing.id)
        CU-->>C: persisted(contradict, new.id, superseded_id=existing.id)
    else verdict = new
        CU->>B: upsert(new learning, embedding)
        CU-->>C: persisted(new, new.id)
    end
```

### The five verdicts

| Verdict      | Meaning                                              | Effect on the store                                                     |
| ------------ | ---------------------------------------------------- | ----------------------------------------------------------------------- |
| `reject`     | Trivial, one-off, or unsafe to retain                | Nothing written                                                          |
| `new`        | A durable lesson with no close match                 | New row inserted                                                         |
| `same`       | Restates an existing active learning                 | Nothing new; the existing row is touched (`hits++`)                      |
| `refine`     | Same lesson family, with more detail or a correction | Existing row updated in place and re-embedded — id, `created_at`, and `hits` preserved |
| `contradict` | Conflicts with an existing learning                  | Existing row marked `superseded`; new row inserted with `supersedes` set |

The judge makes two judgements in one call — **novelty** first (does this match
something already stored?), then **worth-keeping** (is this generalisable and
non-trivial?) — and the prompt asks for both in a single structured response, so
one round trip covers the whole decision.

`JudgeVerdict` enforces its own consistency through a pydantic validator, so a
malformed decision fails at parse time rather than corrupting the store: a
`reject` must not carry a generated learning; `same`/`refine`/`contradict` must
name a `related_learning_id`; `new`/`refine`/`contradict` must carry the
generated learning. `PersistResult` is validated the same way — a `rejected`
result may not carry learning ids, a `persisted` one must have a `learning_id`,
and `superseded_id` is only legal for `contradict`.

### Two details worth knowing

**`refine` uses `model_copy`, not a fresh `Learning`.** The upsert's
`ON CONFLICT DO UPDATE` writes exactly the values it is handed, so
re-constructing the learning from scratch would silently reset `hits` to 0 and
`last_used_at` to `NULL` — quietly destroying the ranking signal a learning had
accumulated. Copying the existing row and overriding only the generated fields
preserves `id`, `created_at`, `hits`, `last_used_at`, `agent_id`, and
`supersedes`.

**A verdict naming an unknown learning degrades, it does not crash.** If
`refine` or `contradict` references an id that was not among the retrieved
neighbours, the curator logs a warning and persists it as a `new` learning
instead — the lesson is still captured. Only a `same` verdict pointing at an
unknown id is a hard `CurationError`, because there is no new content to fall
back on: the whole point of `same` is that nothing was generated. That surfaces
to the caller as a clean `rejected` result, not an exception.

**The brand-new-agent fast path.** `agent_learnings.has_learnings` lets the
curator skip the neighbour search entirely for an agent with an empty store —
there is nothing to match against, so both searches would be round trips
returning zero rows. The flag is a deliberately one-way hint: set `TRUE` on
first write, never reset. A false positive costs one wasted empty search; a
false negative — which would make a duplicate look novel — must never happen,
and by construction cannot.

---

## Storage schema

```mermaid
erDiagram
    learnings {
        UUID id PK
        TEXT agent_id "isolation"
        TEXT entity_id "NULL for global"
        TEXT scope "personal | global"
        TEXT status "active | superseded | rejected"
        UUID supersedes "-> learnings.id"
        TEXT context "embedded"
        TEXT content "embedded"
        TEXT outcome "positive | negative | neutral"
        TEXT reason
        TEXT original_output
        TEXT corrected_output
        TEXT category "used by rerank_text()"
        TEXT_ARRAY tags "used by rerank_text()"
        TIMESTAMPTZ created_at
        TIMESTAMPTZ last_used_at "ranking signal"
        INTEGER hits "ranking signal"
        VECTOR embedding "vector(dim), HNSW cosine"
        TSVECTOR search_tsv "GENERATED, GIN"
    }
    token_usage {
        UUID id PK
        TEXT agent_id
        TEXT entity_id "NULL when not entity-scoped"
        TEXT operation "'judge' | ..."
        TEXT model
        INTEGER prompt_tokens
        INTEGER completion_tokens
        INTEGER total_tokens
        TIMESTAMPTZ created_at
    }
    agent_learnings {
        TEXT agent_id PK
        BOOLEAN has_learnings "one-way hint"
        TIMESTAMPTZ created_at
        TIMESTAMPTZ updated_at
    }
    learnings ||--o| learnings : "supersedes"
```

Four indexes carry the whole workload:

| Index                      | Type   | Serves                                                    |
| -------------------------- | ------ | ---------------------------------------------------------- |
| `learnings_filter_idx`     | B-tree | The isolation pre-filter `(agent_id, status, scope, entity_id)` |
| `learnings_embedding_idx`  | HNSW   | `embedding vector_cosine_ops` — semantic search             |
| `learnings_search_idx`     | GIN    | `search_tsv` — keyword search                               |
| `token_usage_agent_idx`    | B-tree | `(agent_id, created_at DESC)` — spend aggregation           |

`search_tsv` is `GENERATED ALWAYS AS (to_tsvector('english', context || ' ' || content)) STORED`
— Postgres maintains it, so the keyword index can never fall out of sync with
the text, which is exactly the failure mode an application-maintained column
would eventually hit. Note the asymmetry that follows: the tsvector updates
itself on any write, while the `embedding` column only changes when the
application re-embeds — which is why `update_learning()` re-embeds explicitly on
a text change.

There is no `agents` table. The `/agents` roster is derived at query time from
every `agent_id` appearing in `learnings` or `token_usage`, so an agent exists
exactly when it has done something.

---

## The HTTP API (optional)

Install the `api` extra and run:

```bash
export DATABASE_URL=postgresql://polynomial:polynomial@localhost:5433/learnings
export GROQ_API_KEY=...          # optional; without it /persist returns 503
export LEARNINGS_API_KEY=...     # optional; without it every /v1 route is open
export EMBEDDER_MODEL=...        # optional; defaults to all-MiniLM-L6-v2 (384 dims)
uvicorn learnings.api.app:app
```

### Authentication

Set `LEARNINGS_API_KEY` and every route under `/v1` requires
`Authorization: Bearer <key>`; anything else gets a `401`. `/health` is never
gated, so liveness probes keep working. Leaving it unset disables the check
entirely — convenient locally, but any real deployment should set it.

Clients pass the key through `LearningClient`'s `headers`:

```python
LearningClient(
    agent_id="insights-bot",
    base_url="https://learnings.internal",
    headers={"Authorization": f"Bearer {os.environ['LEARNINGS_API_KEY']}"},
)
```

At startup the app creates the embedder, runs `init_schema()`, opens the
`PgVectorBackend` pool, and constructs the judge if `GROQ_API_KEY` is set —
each once, stored on `app.state` and shared across requests. A
`LearningManager` is built per request, bound to the `agent_id` in the path.
Handlers are deliberately sync (`def`, not `async def`) so FastAPI runs them in
its threadpool: the embedder and psycopg calls are blocking, and this keeps them
off the event loop.

| Method   | Path                                                    | Purpose                                                     |
| -------- | ------------------------------------------------------- | ------------------------------------------------------------ |
| `GET`    | `/health`                                               | Liveness/readiness probe                                     |
| `GET`    | `/v1/agents`                                            | Roster of every agent the store has seen                     |
| `POST`   | `/v1/agents/{agent_id}/retrieve`                        | Relevant learnings for a conversation snapshot               |
| `POST`   | `/v1/agents/{agent_id}/persist`                         | Curate a snapshot and persist if warranted                   |
| `GET`    | `/v1/agents/{agent_id}/learnings?entity_id=`            | Personal + global in one round trip                          |
| `GET`    | `/v1/agents/{agent_id}/learnings/personal?entity_id=`   | One entity's personal learnings                              |
| `GET`    | `/v1/agents/{agent_id}/learnings/global`                | This agent's global learnings                                |
| `PATCH`  | `/v1/agents/{agent_id}/learnings/{learning_id}`         | Update editable fields (re-embeds on text change)            |
| `POST`   | `/v1/agents/{agent_id}/learnings/{learning_id}/approve` | Mark `active`                                                |
| `POST`   | `/v1/agents/{agent_id}/learnings/{learning_id}/disapprove` | Mark `rejected`                                           |
| `DELETE` | `/v1/agents/{agent_id}/learnings/{learning_id}`         | Soft-delete (mark `rejected`, row retained)                  |
| `GET`    | `/v1/agents/{agent_id}/stats`                           | Aggregate learning statistics                                |
| `GET`    | `/v1/agents/{agent_id}/tokens`                          | Aggregate token consumption                                  |

Responses reuse the core `Learning`, `PersistResult`, `AgentStats`, and
`TokenUsageStats` models directly, so the API and the SDK share exactly one
shape — there is no second definition to drift.

The listing endpoint returns both scopes at once because it is the common case
for an agent loading context before a turn. Unlike `/retrieve` it is **not**
relevance-ranked: a standing preference that no query would ever match
semantically ("always answer me in a table") still comes back.

Two status codes are worth calling out. `404` is returned for a learning that
does not exist *or* belongs to another agent — the two are indistinguishable by
design. `503` on `/persist` means no judge is configured server-side; that is a
deployment state, not a bad request, which is why it is not a `4xx`.

CORS ships wide open (`allow_origins=["*"]`), which is safe only because there
is no auth and no cookies. **Tighten it, and put authentication in front, before
any real deployment.**

---

## Two-tier deployment: the thin client

In the two-tier topology the agent runs inside a thin SDK while the embedder,
judge, and vector store live behind the API on a server you can scale and
load-balance. `LearningClient` is the seam:

```python
from learnings.client import LearningClient

with LearningClient(agent_id="insights-bot", base_url="https://learnings.internal") as client:
    learnings = client.retrieve(messages, entity_id="acme-corp", limit=5)
    result = client.persist(messages, entity_id="acme-corp")
```

It exposes only the two hot-path operations an agent actually needs. The
management endpoints (approve, disapprove, stats, list, patch, delete) are
deliberately absent: those belong to a human review UI, not to an agent's
runtime.

The design rule the module enforces is **one method == one HTTP round trip**.
All multi-step work — neighbour retrieval, judging, the create/refine/supersede
write — happens server-side inside a single endpoint, so the thin client is
never chatty regardless of how much work a call does.

Every failure mode, transport-level and non-2xx alike, is wrapped in
`LearningsAPIError`, so callers catch one exception type and never see raw
`httpx` internals. `status_code` is `None` for transport failures (nothing came
back) and the server's code otherwise, with FastAPI's `detail` string surfaced
in the message.

Pass an existing `httpx.Client` to reuse a connection pool — or to inject a
`MockTransport` in tests. `headers` is merged into every request, which is the
natural place for an `Authorization` bearer token.

---

## PydanticAI adapter

Registers two tools, `store_learning` and `get_learnings`, that call a
`LearningClient` over HTTP, so the agent process carries no embedder, judge,
or database weight. The host app supplies an `entity_id_resolver` that
derives "who this is for" from its own `RunContext`, so the library never
needs to know anything about the host's identity model.

```python
from learnings.adapters.pydantic_ai import register_tools_via_api

register_tools_via_api(agent, client, entity_id_resolver=lambda ctx: ctx.deps.tenant_id)
```

Both tools are message-based, matching the API contract — the agent passes a
few recent conversation turns as `messages` and the server derives the query
or candidate learning from them. The server's judge derives the lesson from
`store_learning`'s turns, deciding between store, refine, supersede, and
reject.

The tools catch `LearningsAPIError` and return a readable string
rather than raising: a memory-store outage should degrade an agent turn, not
crash it.

---

## Bring your own layer

Every seam is a `Protocol`, so implementations are structural — no base class to
inherit, no registration step.

```python
from typing import Sequence
from learnings import Learning, JudgeVerdict

class MyEmbedder:
    @property
    def dimension(self) -> int: ...
    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...

class MyJudge:
    def evaluate(self, prompt: str) -> JudgeVerdict: ...
    # optional: evaluate_with_usage(prompt) -> (JudgeVerdict, TokenUsage)

class MyReranker:
    def score(self, query: str, candidates: Sequence[Learning]) -> list[float]: ...

class MyBackend:
    ...  # the twelve VectorStoreBackend methods listed above
```

Token accounting is duck-typed rather than required: the curator checks for
`evaluate_with_usage` and falls back to `evaluate`, so a judge that cannot
report usage stays a perfectly valid judge.

Wire whichever pieces you replaced:

```python
from learnings import CrossEncoderReranker, HybridRetriever, LearningManager

retriever = HybridRetriever(
    backend=backend,
    embedder=embedder,
    semantic_weight=1.0,        # RRF weight for the vector list
    keyword_weight=1.0,         # RRF weight for the full-text list
    rrf_k=60,
    reranker=CrossEncoderReranker(),
    rerank_threshold=0.52,
)

manager = LearningManager(
    agent_id="insights-bot",
    backend=backend,
    embedder=embedder,
    retriever=retriever,
    judge=my_judge,
)
```

For tests, `FakeJudge` and `FakeReranker` cover the two layers that would
otherwise need a model or a network call:

```python
from learnings import FakeJudge, FakeReranker, JudgeVerdict, Verdict, GeneratedLearning

judge = FakeJudge(JudgeVerdict(
    verdict=Verdict.new,
    learning=GeneratedLearning(context="...", content="...", category="sql", tags=["x"]),
))
reranker = FakeReranker([0.9, 0.4, 0.1])            # or a callable(query, candidates)
```

---

## Design choices worth knowing about

- **Isolation is a pre-filter in SQL, not a filter on results.** Rows outside
  the boundary are never candidates, so they cannot leak through a ranking bug,
  a fusion bug, or a reranker bug.
- **The LLM chooses `scope`; the library resolves `entity_id`.** A `global`
  verdict always forces `entity_id = None`; a `personal` verdict without a
  caller-supplied entity is rejected outright rather than written as a global.
  The isolation guarantee never depends on the model behaving.
- **`embedding_text()` is frozen; `rerank_text()` is free.** Anything computed
  at write time and stored is a migration risk; anything computed at query time
  is not. Rerank-stage enrichment therefore lives entirely in the latter.
- **Nothing is hard-deleted.** Disapprove and delete both mark `rejected`; a
  contradiction marks the old row `superseded` and links the new one via
  `supersedes`. The store keeps a complete, auditable history of what it
  believed and when it changed its mind.
- **Retrieval touches only what it returns.** Candidates dropped by the rerank
  threshold never get their `hits` incremented, so the popularity signal
  reflects genuine use rather than mere candidacy.
- **Curation reuses the real retriever.** The judge's neighbours come from the
  same `HybridRetriever` a user-facing query would use — never a private,
  differently-tuned query — so novelty is judged against exactly what
  retrieval would surface.
- **Every heavyweight dependency is lazy.** `sentence_transformers`, `groq`,
  and `httpx` are imported inside the constructors that need them, so
  `import learnings` stays cheap and the extras stay genuinely optional.
- **Token accounting is best-effort and non-blocking.** A failure to record
  spend is logged and swallowed; observability never fails a write.
- **The library never configures logging handlers.** `learnings` attaches a
  `NullHandler` and nothing else — handler configuration belongs to the
  application, not to a library it imports.

---

## Error handling

```python
from learnings import (
    LearningsError,           # base class for everything below
    JudgeError,               # base class for judge failures
    JudgeUnavailableError,    # the judge could not be reached (network/API)
    JudgeOutputError,         # the judge replied, but never produced a valid JudgeVerdict
    CurationError,            # curator-level failure, e.g. a verdict outside the boundary
)
from learnings.exceptions import LearningsAPIError   # LearningClient HTTP failures
```

`ValueError` is raised directly, rather than as a `learnings` exception, for
programming errors the caller can fix at the call site: a personal `record()`
with no `entity_id`, a personal `list_learnings()` with no `entity_id`,
`update_learning()` with a non-editable field, or
`persist_from_conversation()` on a manager built without a judge.

`CurationError` is caught internally by the curator and converted into a
`PersistResult(decision="rejected")` — a persist that cannot be completed
safely comes back as a clean rejection with a reason, not an exception.

---

## Running the tests

```bash
pip install -e ".[dev]"

docker run -d --name learnings-pg -p 5433:5432 \
  -e POSTGRES_USER=polynomial -e POSTGRES_PASSWORD=polynomial -e POSTGRES_DB=learnings \
  pgvector/pgvector:pg16

export DATABASE_URL=postgresql://polynomial:polynomial@localhost:5433/learnings
pytest
```

The suite runs against a real Postgres and a real `HuggingFaceEmbedder` (the
model downloads once, then runs offline) rather than mocking either — the
isolation pre-filter, the HNSW/GIN index behaviour, and the generated tsvector
column are all things a fake backend would assert nothing about. The judge and
reranker are the two layers that *are* faked, via `FakeJudge` and
`FakeReranker`, since they are the ones that would otherwise cost a network
call or a second model load.

Coverage spans ingestion and retrieval, personal/global isolation, hybrid
fusion, hit tracking, curated persistence and every verdict path, the reranker
threshold gate, token accounting, the API routes, the thin client, and the
exception hierarchy.
