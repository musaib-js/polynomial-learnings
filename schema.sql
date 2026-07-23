-- polynomial-learnings storage schema.
-- {dim} is filled in by init_schema() with the embedder's vector dimension.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS learnings (
    id               UUID PRIMARY KEY,
    agent_id         TEXT        NOT NULL,
    entity_id        TEXT,                       -- NULL for global learnings
    scope            TEXT        NOT NULL,       -- 'personal' | 'global'
    status           TEXT        NOT NULL DEFAULT 'active',  -- 'active' | 'superseded' | 'rejected'
    supersedes       UUID,

    context          TEXT        NOT NULL,
    content          TEXT        NOT NULL,
    outcome          TEXT        NOT NULL DEFAULT 'neutral', -- 'positive' | 'negative' | 'neutral'
    reason           TEXT,
    original_output  TEXT,
    corrected_output TEXT,
    category         TEXT,
    tags             TEXT[]      NOT NULL DEFAULT '{}',

    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_used_at     TIMESTAMPTZ,
    hits             INTEGER     NOT NULL DEFAULT 0,

    embedding        vector({dim}) NOT NULL,

    -- Only the semantic content is searchable; kept in sync automatically.
    search_tsv       tsvector GENERATED ALWAYS AS (
                         to_tsvector('english', context || ' ' || content)
                     ) STORED
);

-- Isolation pre-filter: agent + scope/entity + status are matched before ranking.
CREATE INDEX IF NOT EXISTS learnings_filter_idx
    ON learnings (agent_id, status, scope, entity_id);

-- Semantic (cosine) similarity.
CREATE INDEX IF NOT EXISTS learnings_embedding_idx
    ON learnings USING hnsw (embedding vector_cosine_ops);

-- Keyword full-text search.
CREATE INDEX IF NOT EXISTS learnings_search_idx
    ON learnings USING gin (search_tsv);


-- Token accounting: one row per model call (judge, etc.), for cost tracking.
CREATE TABLE IF NOT EXISTS token_usage (
    id                UUID PRIMARY KEY,
    agent_id          TEXT        NOT NULL,
    entity_id         TEXT,                          -- NULL when not entity-scoped
    operation         TEXT        NOT NULL,          -- 'judge' | ... (what consumed the tokens)
    model             TEXT,                          -- model identifier, if known
    prompt_tokens     INTEGER     NOT NULL DEFAULT 0,
    completion_tokens INTEGER     NOT NULL DEFAULT 0,
    total_tokens      INTEGER     NOT NULL DEFAULT 0,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Aggregate token stats are keyed by agent, most-recent first.
CREATE INDEX IF NOT EXISTS token_usage_agent_idx
    ON token_usage (agent_id, created_at DESC);


-- Fast "does this agent have any learnings?" flag, so the store path can skip
-- the neighbour search entirely for a brand-new agent (empty DB). This is a
-- one-way hint: set TRUE on first write, never reset. A false positive only
-- costs a wasted (empty) search; a false negative must never happen.
CREATE TABLE IF NOT EXISTS agent_learnings (
    agent_id      TEXT        PRIMARY KEY,
    has_learnings BOOLEAN     NOT NULL DEFAULT FALSE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
