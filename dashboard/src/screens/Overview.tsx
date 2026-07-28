import { useCallback, useEffect, useState } from "react";
import { useApp } from "../context/AppContext";
import type { AgentStats, AgentSummary, TokenUsageStats } from "../api/types";
import { ApiError } from "../api/client";
import {
  CopyId,
  EmptyState,
  RefreshButton,
  SectionTitle,
  Spinner,
  Stat,
} from "../components/ui";
import { Badge } from "../components/Badge";
import { absoluteTime, compact, num, relativeTime } from "../lib/format";
import {
  IconLearnings,
  IconActivity,
  IconBolt,
  IconSearch,
  IconAdd,
  IconChevron,
} from "../components/icons";
import type { Route } from "../components/Sidebar";

type Hue = "ok" | "warn" | "danger" | "info" | "violet" | "neutral" | "accent";

const STATUS_HUE: Record<string, Hue> = {
  active: "ok",
  superseded: "warn",
  rejected: "danger",
};
const SCOPE_HUE: Record<string, Hue> = { global: "accent", personal: "violet" };

function BreakdownRow({
  label,
  value,
  total,
  hue,
}: {
  label: string;
  value: number;
  total: number;
  hue: Hue;
}) {
  const pct = total > 0 ? Math.round((value / total) * 100) : 0;
  return (
    <div className="flex items-center gap-3 py-1.5">
      <Badge hue={hue}>{label}</Badge>
      <div
        className="flex-1 h-1.5 rounded-full overflow-hidden"
        style={{ background: "var(--panel-2)" }}
      >
        <div
          className="h-full rounded-full"
          style={{ width: `${pct}%`, background: `var(--${hue === "accent" ? "accent" : hue})` }}
        />
      </div>
      <span
        className="tabular-nums text-[13px] font-medium w-8 text-right"
        style={{ color: "var(--text-strong)" }}
      >
        {value}
      </span>
    </div>
  );
}

export function Overview({ onNavigate }: { onNavigate: (r: Route) => void }) {
  // Two views: the agent roster (list), and one agent's detailed overview.
  const { settings, updateSettings } = useApp();
  const [selected, setSelected] = useState<string | null>(null);

  const open = useCallback(
    (agentId: string) => {
      // Selecting an agent makes it the active agent everywhere (Learnings,
      // Sandbox), then drills into its overview.
      if (agentId !== settings.agentId) updateSettings({ agentId });
      setSelected(agentId);
    },
    [settings.agentId, updateSettings],
  );

  if (selected !== null) {
    return <AgentDetail onNavigate={onNavigate} onBack={() => setSelected(null)} />;
  }
  return <AgentRoster onNavigate={onNavigate} onOpen={open} />;
}

// ── Agent roster ─────────────────────────────────────────────────────────
function AgentRoster({
  onNavigate,
  onOpen,
}: {
  onNavigate: (r: Route) => void;
  onOpen: (agentId: string) => void;
}) {
  const { api, settings } = useApp();
  const hasBase = settings.baseUrl.trim() !== "";
  const [agents, setAgents] = useState<AgentSummary[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [forbidden, setForbidden] = useState(false);

  const load = useCallback(async () => {
    if (!hasBase) return;
    setLoading(true);
    setError(null);
    setForbidden(false);
    try {
      setAgents(await api.listAgents());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
      setForbidden(err instanceof ApiError && (err.status === 401 || err.status === 403));
      setAgents(null);
    } finally {
      setLoading(false);
    }
  }, [api, hasBase]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="animate-in">
      <div className="flex flex-col lg:flex-row lg:items-end justify-between gap-4 mb-6">
        <div>
          <div className="eyebrow mb-1">Agents</div>
          <h1 className="text-[26px] font-semibold tracking-tight" style={{ color: "var(--text-strong)" }}>
            {agents ? (
              <>
                {agents.length} agent{agents.length === 1 ? "" : "s"}
              </>
            ) : (
              "Agents"
            )}
          </h1>
          <p className="text-[13.5px] mt-1" style={{ color: "var(--muted)" }}>
            Every agent this store has seen. Select one to inspect its memory.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button className="btn" onClick={() => onNavigate("sandbox")}>
            <IconAdd size={14} /> Add agent
          </button>
          <RefreshButton onClick={load} loading={loading} />
        </div>
      </div>

      {!hasBase ? (
        <div className="panel">
          <EmptyState
            icon={<IconSearch size={20} />}
            title="Configure the API to begin"
            hint="Set a base URL in Settings, then this roster will list the agents in that store."
            action={
              <button className="btn" onClick={() => onNavigate("settings")}>
                Open settings
              </button>
            }
          />
        </div>
      ) : error ? (
        forbidden ? (
          // Listing every agent across every tenant is a platform-staff-only
          // endpoint (see GET /v1/agents in learnings/api/routes.py) — an
          // ordinary signed-in customer isn't meant to see it. Fall back to
          // the one agent already configured (auto-provisioned at signup)
          // instead of showing this as an error.
          <div className="panel">
            <EmptyState
              icon={<IconLearnings size={20} />}
              title="Your agent"
              hint={
                settings.agentId
                  ? `Cross-tenant roster is admin-only — jump straight into ${settings.agentId}.`
                  : "No agent configured yet. Open Settings to set one up."
              }
              action={
                settings.agentId ? (
                  <button className="btn btn-primary" onClick={() => onOpen(settings.agentId)}>
                    Open {settings.agentId}
                  </button>
                ) : (
                  <button className="btn" onClick={() => onNavigate("settings")}>
                    Open settings
                  </button>
                )
              }
            />
          </div>
        ) : (
          <div
            className="panel px-4 py-3 flex items-center justify-between gap-4"
            style={{ borderColor: "var(--danger-border)", background: "var(--danger-bg)" }}
          >
            <div className="text-[13px]" style={{ color: "var(--danger)" }}>{error}</div>
            <RefreshButton onClick={load} loading={loading} label="Retry" />
          </div>
        )
      ) : loading && !agents ? (
        <div className="grid place-items-center py-20"><Spinner size={22} /></div>
      ) : agents && agents.length === 0 ? (
        <div className="panel">
          <EmptyState
            icon={<IconLearnings size={20} />}
            title="No agents yet"
            hint="This store has no agents. Open the Sandbox, enter an agent id, and persist a learning — the agent will appear here."
            action={
              <button className="btn" onClick={() => onNavigate("sandbox")}>
                Open sandbox
              </button>
            }
          />
        </div>
      ) : agents ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-3">
          {agents.map((a) => (
            <AgentCard
              key={a.agent_id}
              agent={a}
              active={a.agent_id === settings.agentId}
              onOpen={() => onOpen(a.agent_id)}
            />
          ))}
        </div>
      ) : null}
    </div>
  );
}

function AgentCard({
  agent,
  active,
  onOpen,
}: {
  agent: AgentSummary;
  active: boolean;
  onOpen: () => void;
}) {
  return (
    <button
      onClick={onOpen}
      className="panel px-4 py-4 text-left transition-colors"
      style={{ borderColor: active ? "var(--accent)" : "var(--border)" }}
      onMouseEnter={(e) => (e.currentTarget.style.background = "var(--hover)")}
      onMouseLeave={(e) => (e.currentTarget.style.background = "var(--panel)")}
    >
      <div className="flex items-start justify-between gap-2 mb-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span
              className="inline-block w-2 h-2 rounded-full shrink-0"
              style={{ background: agent.total_learnings > 0 ? "var(--ok)" : "var(--faint)" }}
            />
            <span className="font-semibold text-[15px] truncate" style={{ color: "var(--text-strong)" }}>
              {agent.agent_id}
            </span>
          </div>
          <div className="text-[11.5px] mt-1" style={{ color: "var(--faint)" }}>
            {agent.last_activity ? `active ${relativeTime(agent.last_activity)}` : "no activity yet"}
          </div>
        </div>
        {active && <Badge hue="accent">active</Badge>}
      </div>
      <div className="grid grid-cols-3 gap-2">
        <MiniStat label="Learnings" value={num(agent.total_learnings)} />
        <MiniStat label="Active" value={num(agent.active)} />
        <MiniStat label="Entities" value={num(agent.distinct_entities)} />
      </div>
      <div className="flex items-center gap-1 mt-3 text-[12px] font-medium" style={{ color: "var(--accent)" }}>
        View overview <IconChevron size={13} />
      </div>
    </button>
  );
}

function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg px-2.5 py-2" style={{ background: "var(--panel-2)", border: "1px solid var(--border)" }}>
      <div className="tabular-nums font-semibold text-[16px]" style={{ color: "var(--text-strong)" }}>{value}</div>
      <div className="eyebrow mt-0.5">{label}</div>
    </div>
  );
}

// ── Single-agent detail ──────────────────────────────────────────────────
function AgentDetail({
  onNavigate,
  onBack,
}: {
  onNavigate: (r: Route) => void;
  onBack: () => void;
}) {
  const { api, settings, configured } = useApp();
  const [stats, setStats] = useState<AgentStats | null>(null);
  const [tokens, setTokens] = useState<TokenUsageStats | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!configured) return;
    setLoading(true);
    setError(null);
    try {
      const [s, t] = await Promise.all([api.stats(settings.topN), api.tokens()]);
      setStats(s);
      setTokens(t);
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : String(err);
      setError(msg);
      setStats(null);
      setTokens(null);
    } finally {
      setLoading(false);
    }
  }, [api, settings.topN, configured]);

  useEffect(() => {
    load();
  }, [load, settings.agentId]);

  const statusTotal = stats
    ? Object.values(stats.by_status).reduce((a, b) => a + b, 0)
    : 0;
  const scopeTotal = stats
    ? Object.values(stats.by_scope).reduce((a, b) => a + b, 0)
    : 0;
  const isEmpty = stats && stats.total === 0;

  return (
    <div className="animate-in">
      {/* Header + back */}
      <div className="flex flex-col lg:flex-row lg:items-end justify-between gap-4 mb-6">
        <div>
          <button
            onClick={onBack}
            className="inline-flex items-center gap-1 mb-2 text-[12.5px] font-medium transition-colors"
            style={{ color: "var(--muted)" }}
            onMouseEnter={(e) => (e.currentTarget.style.color = "var(--text)")}
            onMouseLeave={(e) => (e.currentTarget.style.color = "var(--muted)")}
          >
            <span style={{ transform: "rotate(180deg)", display: "inline-flex" }}>
              <IconChevron size={13} />
            </span>
            All agents
          </button>
          <div className="eyebrow mb-1">Agent overview</div>
          <div className="flex items-center gap-2.5">
            <h1 className="text-[26px] font-semibold tracking-tight" style={{ color: "var(--text-strong)" }}>
              {settings.agentId}
            </h1>
            <RefreshButton onClick={load} loading={loading} />
          </div>
          <p className="text-[13.5px] mt-1" style={{ color: "var(--muted)" }}>
            Snapshot of what this agent has learned, how often it is used, and what it
            is costing.
          </p>
        </div>
      </div>

      {configured && error && (
        <div
          className="panel px-4 py-3 mb-5 flex items-center justify-between gap-4"
          style={{ borderColor: "var(--danger-border)", background: "var(--danger-bg)" }}
        >
          <div className="text-[13px]" style={{ color: "var(--danger)" }}>
            {error}
          </div>
          <RefreshButton onClick={load} loading={loading} label="Retry" />
        </div>
      )}

      {configured && !error && (
        <>
          {/* Primary stat tiles */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-3">
            <Stat
              label="Total learnings"
              value={loading && !stats ? <Spinner /> : num(stats?.total)}
              sub={stats ? `avg ${stats.avg_hits.toFixed(1)} hits` : undefined}
              icon={<IconLearnings size={15} />}
            />
            <Stat
              label="Total hits"
              value={loading && !stats ? <Spinner /> : num(stats?.total_hits)}
              sub="retrievals served"
              icon={<IconActivity size={15} />}
            />
            <Stat
              label="Distinct entities"
              value={loading && !stats ? <Spinner /> : num(stats?.distinct_entities)}
              sub="users with memory"
            />
            <Stat
              label="Last used"
              value={
                loading && !stats ? (
                  <Spinner />
                ) : (
                  <span className="text-[18px]">{relativeTime(stats?.last_used_at)}</span>
                )
              }
              sub={stats?.last_used_at ? absoluteTime(stats.last_used_at) : "no activity yet"}
            />
          </div>

          {isEmpty ? (
            <div className="panel mb-6">
              <EmptyState
                icon={<IconLearnings size={20} />}
                title="This agent has no learnings yet"
                hint="That's expected for a brand-new agent. Learnings appear here as conversations are curated. Try the Sandbox to persist one."
                action={
                  <button className="btn" onClick={() => onNavigate("sandbox")}>
                    Open sandbox
                  </button>
                }
              />
            </div>
          ) : (
            <>
              {/* Breakdowns */}
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-3 mb-6">
                <div className="panel px-4 py-4">
                  <SectionTitle title="Status breakdown" />
                  {stats && statusTotal > 0 ? (
                    (["active", "superseded", "rejected"] as const).map((k) => (
                      <BreakdownRow
                        key={k}
                        label={k}
                        value={stats.by_status[k] ?? 0}
                        total={statusTotal}
                        hue={STATUS_HUE[k]}
                      />
                    ))
                  ) : (
                    <div className="text-[13px]" style={{ color: "var(--faint)" }}>
                      No data
                    </div>
                  )}
                </div>
                <div className="panel px-4 py-4">
                  <SectionTitle title="Scope breakdown" />
                  {stats && scopeTotal > 0 ? (
                    (["personal", "global"] as const).map((k) => (
                      <BreakdownRow
                        key={k}
                        label={k}
                        value={stats.by_scope[k] ?? 0}
                        total={scopeTotal}
                        hue={SCOPE_HUE[k]}
                      />
                    ))
                  ) : (
                    <div className="text-[13px]" style={{ color: "var(--faint)" }}>
                      No data
                    </div>
                  )}
                </div>
                <div className="panel px-4 py-4">
                  <SectionTitle title="Activity" />
                  <div className="flex items-center justify-between py-2 border-b" style={{ borderColor: "var(--border)" }}>
                    <span className="text-[13px]" style={{ color: "var(--muted)" }}>
                      Last created
                    </span>
                    <span className="text-[13px] font-medium" style={{ color: "var(--text-strong)" }} title={absoluteTime(stats?.last_created_at)}>
                      {relativeTime(stats?.last_created_at)}
                    </span>
                  </div>
                  <div className="flex items-center justify-between py-2">
                    <span className="text-[13px]" style={{ color: "var(--muted)" }}>
                      Last used
                    </span>
                    <span className="text-[13px] font-medium" style={{ color: "var(--text-strong)" }} title={absoluteTime(stats?.last_used_at)}>
                      {relativeTime(stats?.last_used_at)}
                    </span>
                  </div>
                </div>
              </div>

              {/* Most used */}
              <div className="panel mb-6">
                <div className="flex items-center justify-between px-4 pt-4 pb-2">
                  <SectionTitle title="Most-used learnings" />
                  <span className="eyebrow">top {stats?.most_used.length ?? 0}</span>
                </div>
                <MostUsedTable stats={stats} />
              </div>
            </>
          )}

          {/* Token consumption */}
          <TokenPanel tokens={tokens} loading={loading && !tokens} />
        </>
      )}
    </div>
  );
}

function MostUsedTable({ stats }: { stats: AgentStats | null }) {
  if (!stats) return null;
  if (stats.most_used.length === 0) {
    return (
      <div className="px-4 pb-4 text-[13px]" style={{ color: "var(--faint)" }}>
        Nothing retrieved yet.
      </div>
    );
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[13px] border-collapse">
        <thead>
          <tr style={{ color: "var(--faint)" }}>
            <th className="text-left font-medium eyebrow px-4 py-2">Context → content</th>
            <th className="text-right font-medium eyebrow px-4 py-2 w-24">Hits</th>
            <th className="text-right font-medium eyebrow px-4 py-2 w-40">Id</th>
          </tr>
        </thead>
        <tbody>
          {stats.most_used.map((m) => (
            <tr key={m.id} style={{ borderTop: "1px solid var(--border)" }}>
              <td className="px-4 py-3">
                <div className="text-[12px] mb-0.5" style={{ color: "var(--faint)" }}>
                  {m.context}
                </div>
                <div style={{ color: "var(--text)" }} className="line-clamp-2">
                  {m.content}
                </div>
              </td>
              <td className="px-4 py-3 text-right tabular-nums font-semibold" style={{ color: "var(--text-strong)" }}>
                {num(m.hits)}
              </td>
              <td className="px-4 py-3 text-right">
                <CopyId id={m.id} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function TokenPanel({
  tokens,
  loading,
}: {
  tokens: TokenUsageStats | null;
  loading: boolean;
}) {
  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <SectionTitle
          eyebrow="Observability"
          title="Token consumption"
          right={undefined}
        />
        <IconBolt size={15} />
      </div>
      <p className="text-[12.5px] -mt-2 mb-3" style={{ color: "var(--faint)" }}>
        Cost signal for model calls (the Judge). Informational — not an alert.
      </p>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-3">
        <Stat label="Total calls" value={loading ? <Spinner /> : num(tokens?.total_calls)} />
        <Stat label="Prompt tokens" value={loading ? <Spinner /> : compact(tokens?.prompt_tokens)} sub={tokens ? num(tokens.prompt_tokens) : undefined} />
        <Stat label="Completion tokens" value={loading ? <Spinner /> : compact(tokens?.completion_tokens)} sub={tokens ? num(tokens.completion_tokens) : undefined} />
        <Stat label="Total tokens" value={loading ? <Spinner /> : compact(tokens?.total_tokens)} sub={tokens ? num(tokens.total_tokens) : undefined} />
      </div>

      {tokens && (tokens.by_operation.length > 0 || Object.keys(tokens.by_model).length > 0) && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
          <div className="panel px-4 py-4">
            <SectionTitle title="By operation" />
            {tokens.by_operation.length === 0 ? (
              <div className="text-[13px]" style={{ color: "var(--faint)" }}>No calls recorded.</div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-[13px]">
                  <thead>
                    <tr style={{ color: "var(--faint)" }}>
                      <th className="text-left eyebrow py-1.5">Operation</th>
                      <th className="text-right eyebrow py-1.5">Calls</th>
                      <th className="text-right eyebrow py-1.5">Prompt</th>
                      <th className="text-right eyebrow py-1.5">Compl.</th>
                      <th className="text-right eyebrow py-1.5">Total</th>
                    </tr>
                  </thead>
                  <tbody>
                    {tokens.by_operation.map((op) => (
                      <tr key={op.operation} style={{ borderTop: "1px solid var(--border)" }}>
                        <td className="py-2 mono" style={{ color: "var(--text)" }}>{op.operation}</td>
                        <td className="py-2 text-right tabular-nums">{num(op.calls)}</td>
                        <td className="py-2 text-right tabular-nums" style={{ color: "var(--muted)" }}>{num(op.prompt_tokens)}</td>
                        <td className="py-2 text-right tabular-nums" style={{ color: "var(--muted)" }}>{num(op.completion_tokens)}</td>
                        <td className="py-2 text-right tabular-nums font-semibold" style={{ color: "var(--text-strong)" }}>{num(op.total_tokens)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
          <div className="panel px-4 py-4">
            <SectionTitle title="By model" />
            {Object.keys(tokens.by_model).length === 0 ? (
              <div className="text-[13px]" style={{ color: "var(--faint)" }}>No model usage recorded.</div>
            ) : (
              Object.entries(tokens.by_model).map(([model, total]) => (
                <div key={model} className="flex items-center justify-between py-2" style={{ borderTop: "1px solid var(--border)" }}>
                  <span className="mono text-[12.5px]" style={{ color: "var(--text)" }}>{model}</span>
                  <span className="tabular-nums font-semibold text-[13px]" style={{ color: "var(--text-strong)" }}>{num(total)}</span>
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}
