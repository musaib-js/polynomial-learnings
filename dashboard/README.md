# polynomial-learnings — management console

Operator-facing web console for **polynomial-learnings**: the human-review path
for inspecting, approving, editing, and auditing an agent's durable curated
memory. It is **not** the agent runtime and is not shown to end users.

Single-page app (React + TypeScript + Vite + Tailwind). No backend of its own —
it talks directly to the polynomial-learnings API at a base URL you configure in
**Settings**. Nothing in this folder changes the API or the rest of the repo.

## Run

```bash
cd dashboard
npm install
npm run dev      # http://localhost:5174
```

Build a static bundle (outputs to `dist/`, deployable to any static host):

```bash
npm run build
npm run preview
```

## Configure

Open **Settings** (or the loader on Overview) and set:

- **API base URL** — e.g. `http://localhost:8000`. Requests go to
  `{base}/v1/agents/{agent_id}/…`; health uses the unversioned `/health`.
- **Agent id** — everything is scoped to one `agent_id`.
- **Authorization bearer token** — optional; attached to every request when set.
  This is the API's own auth token, not any infra secret.

Settings persist in `localStorage`. The CORS policy on the API is open, so the
dev server can call it cross-origin; for production, serve this bundle from a
host the API allows.

## Screens

- **Overview** — an **agent roster** first (count + a card per agent, each with
  learnings / active / entities / last-activity), backed by `GET /v1/agents`.
  Click an agent to drill into its full overview: health, stats (totals,
  status/scope breakdowns, hits, distinct entities, last activity, most-used)
  and a token-consumption / cost panel.
- **Learnings** — filterable table. Scope toggle (global / personal); personal
  requires an explicit `entity_id` (never inferred). Per-row approve /
  disapprove / edit / soft-delete, with supersede links surfaced.
- **Sandbox** — pick (or type a **new**) agent id, paste a conversation snapshot
  and **Retrieve** (read-only, no
  LLM) or **Persist** (runs the Judge, costs tokens; handles a `503` when the
  judge isn't configured as "curation unavailable"). The five verdicts —
  `new` / `same` / `refine` / `contradict` / `reject` — render distinctly.
- **Activity** — a request/response log of every call this session made.
- **Settings** — API connection + display options.

## Notes on the security model (reflected in the UI)

- `entity_id` is always entered explicitly; one entity's personal learnings are
  never shown while browsing another.
- Deletes are **soft** — rows are marked `rejected` and retained for audit, never
  hard-deleted.
- No infra secrets (DB URLs, provider keys) are entered or displayed anywhere.
- Learning UUIDs are secondary, copyable metadata — never headline content.

## Editable fields

Only `context`, `content`, `category`, `tags`, `reason`, and `outcome` are
editable (`PATCH /learnings/{id}`). Everything else is read-only, managed by the
system.
