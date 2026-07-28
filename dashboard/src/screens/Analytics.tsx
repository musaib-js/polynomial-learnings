import { useCallback, useEffect, useState } from "react";
import { useApp } from "../context/AppContext";
import { useAuth } from "../context/AuthContext";
import { authApi, AuthError } from "../api/auth";
import type { LearningsGrowth, UsageTrends } from "../api/types";
import { EmptyState, RefreshButton, SectionTitle, Spinner, Stat } from "../components/ui";
import { IconActivity, IconBolt, IconChart, IconLearnings } from "../components/icons";
import { absoluteTime, num, relativeTime } from "../lib/format";

type Bucket = "day" | "week" | "month";

// Dependency-free bar chart — flex divs with proportional heights, matching
// the app's existing "no chart library, style with CSS vars" approach (see
// Overview.tsx's BreakdownRow).
function BarChart<T extends object>({
  points,
  labelKey,
  valueKey,
}: {
  points: T[];
  labelKey: keyof T;
  valueKey: keyof T;
}) {
  if (points.length === 0) {
    return (
      <div className="text-[13px] py-8 text-center" style={{ color: "var(--faint)" }}>
        No data for this range yet.
      </div>
    );
  }
  const max = Math.max(1, ...points.map((p) => Number(p[valueKey]) || 0));
  return (
    <div className="flex items-end gap-1.5" style={{ height: 140 }}>
      {points.map((p, i) => {
        const value = Number(p[valueKey]) || 0;
        const pct = Math.max(2, Math.round((value / max) * 100));
        const label = String(p[labelKey]);
        return (
          <div
            key={i}
            className="flex-1 min-w-[6px] rounded-t-sm transition-opacity"
            style={{ height: `${pct}%`, background: "var(--accent)", opacity: 0.85 }}
            title={`${new Date(label).toLocaleDateString()}: ${value}`}
          />
        );
      })}
    </div>
  );
}

export function Analytics() {
  const { settings, configured } = useApp();
  const { accessToken } = useAuth();
  const baseUrl = settings.baseUrl;
  const agentId = settings.agentId;

  const [bucket, setBucket] = useState<Bucket>("day");
  const [growth, setGrowth] = useState<LearningsGrowth | null>(null);
  const [usage, setUsage] = useState<UsageTrends | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!accessToken || !agentId.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const [g, u] = await Promise.all([
        authApi.analyticsLearnings(baseUrl, accessToken, agentId, bucket),
        authApi.analyticsUsage(baseUrl, accessToken, agentId, bucket),
      ]);
      setGrowth(g);
      setUsage(u);
    } catch (err) {
      setError(err instanceof AuthError ? err.message : String(err));
      setGrowth(null);
      setUsage(null);
    } finally {
      setLoading(false);
    }
  }, [baseUrl, accessToken, agentId, bucket]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="animate-in">
      <div className="flex flex-col lg:flex-row lg:items-end justify-between gap-4 mb-5">
        <div>
          <div className="eyebrow mb-1">Insights</div>
          <h1 className="text-[24px] font-semibold tracking-tight" style={{ color: "var(--text-strong)" }}>
            Analytics
          </h1>
          <p className="text-[13.5px] mt-1" style={{ color: "var(--muted)" }}>
            Growth and retrieval trends for <span className="mono">{agentId || "no agent"}</span>.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="inline-flex rounded-lg p-0.5" style={{ background: "var(--panel-2)", border: "1px solid var(--border)" }}>
            {(["day", "week", "month"] as const).map((b) => (
              <button
                key={b}
                onClick={() => setBucket(b)}
                className="px-3 h-[28px] rounded-md text-[12.5px] font-medium capitalize transition-colors"
                style={{
                  background: bucket === b ? "var(--bg-elevated)" : "transparent",
                  color: bucket === b ? "var(--text-strong)" : "var(--muted)",
                  border: bucket === b ? "1px solid var(--border)" : "1px solid transparent",
                }}
              >
                {b}
              </button>
            ))}
          </div>
          <RefreshButton onClick={load} loading={loading} />
        </div>
      </div>

      {!configured ? (
        <div className="panel">
          <EmptyState title="Not configured" hint="Set the API base URL and agent id in Settings first." />
        </div>
      ) : error ? (
        <div className="panel px-4 py-3 flex items-center justify-between gap-4" style={{ borderColor: "var(--danger-border)", background: "var(--danger-bg)" }}>
          <div className="text-[13px]" style={{ color: "var(--danger)" }}>{error}</div>
          <RefreshButton onClick={load} loading={loading} label="Retry" />
        </div>
      ) : loading && !growth ? (
        <div className="panel grid place-items-center py-16">
          <Spinner size={22} />
        </div>
      ) : (
        <>
          {/* Learnings growth */}
          <div className="grid grid-cols-2 lg:grid-cols-6 gap-3 mb-3">
            <Stat label="Total" value={num(growth?.total)} icon={<IconLearnings size={14} />} />
            <Stat label="Personal" value={num(growth?.personal)} />
            <Stat label="Global" value={num(growth?.global)} />
            <Stat label="Approved" value={num(growth?.approved)} />
            <Stat label="Pending" value={num(growth?.pending)} />
            <Stat label="Rejected" value={num(growth?.rejected)} />
          </div>

          <div className="panel px-4 py-4 mb-3">
            <SectionTitle eyebrow="Growth" title="Learnings created over time" />
            <BarChart points={growth?.series ?? []} labelKey="bucket" valueKey="created" />
          </div>

          <div className="panel px-4 py-4 mb-6">
            <SectionTitle eyebrow="Usage" title="Retrievals over time" right={<IconChart size={15} />} />
            <BarChart points={usage?.series ?? []} labelKey="bucket" valueKey="retrievals" />
          </div>

          {/* Most used / recently retrieved */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
            <div className="panel">
              <div className="px-4 pt-4 pb-2">
                <SectionTitle title="Most retrieved" right={<IconBolt size={15} />} />
              </div>
              {!usage || usage.most_used.length === 0 ? (
                <div className="px-4 pb-4 text-[13px]" style={{ color: "var(--faint)" }}>
                  Nothing retrieved yet.
                </div>
              ) : (
                <table className="w-full text-[13px]">
                  <tbody>
                    {usage.most_used.map((m) => (
                      <tr key={m.learning_id} style={{ borderTop: "1px solid var(--border)" }}>
                        <td className="px-4 py-2.5 mono" style={{ color: "var(--muted)" }}>
                          {m.learning_id.slice(0, 8)}…
                        </td>
                        <td className="px-4 py-2.5 text-right tabular-nums font-semibold" style={{ color: "var(--text-strong)" }}>
                          {num(m.retrievals)} retrievals
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>

            <div className="panel">
              <div className="px-4 pt-4 pb-2">
                <SectionTitle title="Recently retrieved" right={<IconActivity size={15} />} />
              </div>
              {!usage || usage.recently_retrieved.length === 0 ? (
                <div className="px-4 pb-4 text-[13px]" style={{ color: "var(--faint)" }}>
                  No retrieval activity yet.
                </div>
              ) : (
                <table className="w-full text-[13px]">
                  <tbody>
                    {usage.recently_retrieved.map((r, i) => (
                      <tr key={r.learning_id + i} style={{ borderTop: "1px solid var(--border)" }}>
                        <td className="px-4 py-2.5 mono" style={{ color: "var(--muted)" }}>
                          {r.learning_id.slice(0, 8)}…
                        </td>
                        <td className="px-4 py-2.5 text-right" style={{ color: "var(--muted)" }} title={absoluteTime(r.occurred_at)}>
                          {relativeTime(r.occurred_at)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
