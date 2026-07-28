import { useCallback, useEffect, useState } from "react";
import { useApp } from "../context/AppContext";
import type { Learning, Scope } from "../api/types";
import { ApiError } from "../api/client";
import {
  CopyId,
  EmptyState,
  RefreshButton,
  Spinner,
  Tag,
} from "../components/ui";
import { OutcomeBadge, StatusBadge } from "../components/Badge";
import { LearningDetail } from "./LearningDetail";
import { num, relativeTime } from "../lib/format";
import {
  IconCheck,
  IconX,
  IconLearnings,
  IconLink,
  IconSearch,
} from "../components/icons";

const PAGE = 50;

export function Learnings() {
  const { api, settings, toast, configured } = useApp();
  const [scope, setScope] = useState<Scope>("global");
  const [entityId, setEntityId] = useState("");
  const [entitySubmitted, setEntitySubmitted] = useState("");
  const [query, setQuery] = useState("");

  const [items, setItems] = useState<Learning[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [selected, setSelected] = useState<Learning | null>(null);
  const [rowBusy, setRowBusy] = useState<string | null>(null);

  const needsEntity = scope === "personal" && entitySubmitted.trim() === "";

  const load = useCallback(
    async (nextOffset = 0) => {
      if (!configured) return;
      if (scope === "personal" && entitySubmitted.trim() === "") {
        setItems([]);
        return;
      }
      setLoading(true);
      setError(null);
      try {
        const data =
          scope === "personal"
            ? await api.listPersonal(entitySubmitted.trim(), PAGE, nextOffset)
            : await api.listGlobal(PAGE, nextOffset);
        setItems(data);
        setOffset(nextOffset);
        setHasMore(data.length === PAGE);
      } catch (err) {
        setError(err instanceof ApiError ? err.message : String(err));
        setItems([]);
      } finally {
        setLoading(false);
      }
    },
    [api, scope, entitySubmitted, configured],
  );

  useEffect(() => {
    load(0);
  }, [load, settings.agentId]);

  const applyEntity = () => {
    setEntitySubmitted(entityId);
    // load() re-runs via effect dependency on entitySubmitted through `load`.
  };

  useEffect(() => {
    if (scope === "personal") load(0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entitySubmitted]);

  const patchRow = (updated: Learning) => {
    setItems((prev) => prev.map((l) => (l.id === updated.id ? updated : l)));
    setSelected((s) => (s && s.id === updated.id ? updated : s));
  };

  const quickAction = async (
    l: Learning,
    kind: "approve" | "disapprove",
    e: React.MouseEvent,
  ) => {
    e.stopPropagation();
    setRowBusy(l.id + kind);
    try {
      const updated =
        kind === "approve" ? await api.approve(l.id) : await api.disapprove(l.id);
      patchRow(updated);
      toast("success", kind === "approve" ? "Marked active" : "Marked rejected");
    } catch (err) {
      toast("error", `${kind} failed`, err instanceof ApiError ? err.message : String(err));
    } finally {
      setRowBusy(null);
    }
  };

  const filtered = query.trim()
    ? items.filter((l) => {
        const q = query.toLowerCase();
        return (
          l.context.toLowerCase().includes(q) ||
          l.content.toLowerCase().includes(q) ||
          (l.category ?? "").toLowerCase().includes(q) ||
          l.tags.some((t) => t.toLowerCase().includes(q))
        );
      })
    : items;

  return (
    <div className="animate-in">
      <div className="mb-5">
        <div className="eyebrow mb-1">Manage</div>
        <h1 className="text-[24px] font-semibold tracking-tight" style={{ color: "var(--text-strong)" }}>
          Learnings
        </h1>
        <p className="text-[13.5px] mt-1" style={{ color: "var(--muted)" }}>
          Inspect, approve, edit, and audit this agent's stored memory.
        </p>
      </div>

      {/* Filter bar */}
      <div className="panel px-3 py-3 mb-4 flex flex-col lg:flex-row lg:items-center gap-3">
        {/* Scope toggle */}
        <div className="inline-flex rounded-lg p-0.5" style={{ background: "var(--panel-2)", border: "1px solid var(--border)" }}>
          {(["global", "personal"] as const).map((s) => (
            <button
              key={s}
              onClick={() => setScope(s)}
              className="px-3 h-[28px] rounded-md text-[12.5px] font-medium capitalize transition-colors"
              style={{
                background: scope === s ? "var(--bg-elevated)" : "transparent",
                color: scope === s ? "var(--text-strong)" : "var(--muted)",
                border: scope === s ? "1px solid var(--border)" : "1px solid transparent",
              }}
            >
              {s}
            </button>
          ))}
        </div>

        {/* Entity input (personal only, required) */}
        {scope === "personal" && (
          <div className="flex items-center gap-2 flex-1 min-w-0">
            <input
              className="input"
              style={{ maxWidth: 320 }}
              placeholder="entity_id (required)"
              value={entityId}
              onChange={(e) => setEntityId(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && applyEntity()}
            />
            <button className="btn" onClick={applyEntity} disabled={!entityId.trim()}>
              Load
            </button>
          </div>
        )}

        {/* Client-side search within loaded page */}
        <div className="flex items-center gap-2 flex-1 min-w-0 lg:justify-end">
          <div className="relative flex-1" style={{ maxWidth: 280 }}>
            <span className="absolute left-2.5 top-1/2 -translate-y-1/2" style={{ color: "var(--faint)" }}>
              <IconSearch size={14} />
            </span>
            <input
              className="input"
              style={{ paddingLeft: 30 }}
              placeholder="Filter loaded rows…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>
          <RefreshButton onClick={() => load(offset)} loading={loading} />
        </div>
      </div>

      {scope === "personal" && (
        <div className="text-[12px] mb-3 flex items-center gap-1.5" style={{ color: "var(--faint)" }}>
          <IconLink size={12} />
          Personal learnings are isolated per entity. Enter the exact <span className="mono">entity_id</span> — it is never inferred, and one entity's memory is never shown under another.
        </div>
      )}

      {/* Body */}
      {!configured ? (
        <div className="panel">
          <EmptyState title="Not configured" hint="Set the API base URL and agent id in Settings first." />
        </div>
      ) : needsEntity ? (
        <div className="panel">
          <EmptyState
            icon={<IconSearch size={20} />}
            title="Enter an entity_id"
            hint="Personal learnings belong to a specific end user. Provide their entity_id above to view their memory."
          />
        </div>
      ) : error ? (
        <div className="panel px-4 py-3 flex items-center justify-between gap-4" style={{ borderColor: "var(--danger-border)", background: "var(--danger-bg)" }}>
          <div className="text-[13px]" style={{ color: "var(--danger)" }}>{error}</div>
          <RefreshButton onClick={() => load(offset)} loading={loading} label="Retry" />
        </div>
      ) : loading && items.length === 0 ? (
        <div className="panel grid place-items-center py-16">
          <Spinner size={22} />
        </div>
      ) : filtered.length === 0 ? (
        <div className="panel">
          <EmptyState
            icon={<IconLearnings size={20} />}
            title={items.length === 0 ? "No learnings here yet" : "No rows match your filter"}
            hint={
              items.length === 0
                ? scope === "personal"
                  ? "This entity has no personal learnings for this agent. That's normal."
                  : "This agent has no global learnings yet. They appear as conversations are curated."
                : "Try a different search term."
            }
          />
        </div>
      ) : (
        <div className="panel overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-[13px] border-collapse" style={{ minWidth: 820 }}>
              <thead>
                <tr style={{ color: "var(--faint)", borderBottom: "1px solid var(--border)" }}>
                  <th className="text-left eyebrow px-4 py-2.5">Context → content</th>
                  <th className="text-left eyebrow px-3 py-2.5 w-28">Status</th>
                  <th className="text-left eyebrow px-3 py-2.5 w-28">Outcome</th>
                  <th className="text-right eyebrow px-3 py-2.5 w-16">Hits</th>
                  <th className="text-right eyebrow px-3 py-2.5 w-28">Last used</th>
                  <th className="text-right eyebrow px-4 py-2.5 w-[132px]">Actions</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((l) => (
                  <tr
                    key={l.id}
                    onClick={() => setSelected(l)}
                    className="cursor-pointer transition-colors"
                    style={{ borderBottom: "1px solid var(--border)" }}
                    onMouseEnter={(e) => (e.currentTarget.style.background = "var(--hover)")}
                    onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
                  >
                    <td className="px-4 py-3 max-w-[420px]">
                      <div className="flex items-center gap-1.5 mb-0.5">
                        <span className="text-[11.5px]" style={{ color: "var(--faint)" }}>{l.context}</span>
                        {l.supersedes && (
                          <span title="Supersedes an earlier learning" style={{ color: "var(--warn)" }}>
                            <IconLink size={11} />
                          </span>
                        )}
                      </div>
                      <div className="line-clamp-2" style={{ color: "var(--text)" }}>{l.content}</div>
                      {l.tags.length > 0 && (
                        <div className="flex flex-wrap gap-1 mt-1.5">
                          {l.tags.slice(0, 4).map((t) => <Tag key={t}>{t}</Tag>)}
                          {l.tags.length > 4 && <Tag>+{l.tags.length - 4}</Tag>}
                        </div>
                      )}
                    </td>
                    <td className="px-3 py-3"><StatusBadge value={l.status} /></td>
                    <td className="px-3 py-3"><OutcomeBadge value={l.outcome} /></td>
                    <td className="px-3 py-3 text-right tabular-nums font-medium" style={{ color: "var(--text-strong)" }}>{num(l.hits)}</td>
                    <td className="px-3 py-3 text-right" style={{ color: "var(--muted)" }}>{relativeTime(l.last_used_at)}</td>
                    <td className="px-4 py-3">
                      <div className="flex items-center justify-end gap-1">
                        <button
                          className="btn btn-sm btn-ghost"
                          title="Approve (mark active)"
                          disabled={rowBusy === l.id + "approve" || l.status === "active"}
                          onClick={(e) => quickAction(l, "approve", e)}
                          style={{ color: "var(--ok)" }}
                        >
                          {rowBusy === l.id + "approve" ? <Spinner size={12} /> : <IconCheck size={14} />}
                        </button>
                        <button
                          className="btn btn-sm btn-ghost"
                          title="Disapprove (mark rejected)"
                          disabled={rowBusy === l.id + "disapprove" || l.status === "rejected"}
                          onClick={(e) => quickAction(l, "disapprove", e)}
                          style={{ color: "var(--danger)" }}
                        >
                          {rowBusy === l.id + "disapprove" ? <Spinner size={12} /> : <IconX size={14} />}
                        </button>
                        <CopyId id={l.id} head={6} />
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          <div className="flex items-center justify-between px-4 py-2.5" style={{ borderTop: "1px solid var(--border)" }}>
            <span className="text-[12px]" style={{ color: "var(--faint)" }}>
              Showing {filtered.length}{query ? ` of ${items.length}` : ""} · page {offset / PAGE + 1}
            </span>
            <div className="flex gap-2">
              <button className="btn btn-sm" disabled={offset === 0 || loading} onClick={() => load(Math.max(0, offset - PAGE))}>
                Previous
              </button>
              <button className="btn btn-sm" disabled={!hasMore || loading} onClick={() => load(offset + PAGE)}>
                Next
              </button>
            </div>
          </div>
        </div>
      )}

      {selected && (
        <LearningDetail
          learning={selected}
          onClose={() => setSelected(null)}
          onChanged={patchRow}
        />
      )}
    </div>
  );
}
