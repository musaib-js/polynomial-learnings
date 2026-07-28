import { useState } from "react";
import { useApp } from "../context/AppContext";
import type { Learning, Message, PersistResult } from "../api/types";
import { ApiError } from "../api/client";
import { CopyId, EmptyState, Spinner, Tag } from "../components/ui";
import {
  OutcomeBadge,
  ScopeBadge,
  StatusBadge,
  VerdictBadge,
  verdictHue,
} from "../components/Badge";
import { num } from "../lib/format";
import {
  IconAdd,
  IconBolt,
  IconLink,
  IconSearch,
  IconX,
} from "../components/icons";

interface Turn {
  id: string;
  role: string;
  content: string;
}

const ROLES = ["user", "assistant", "system"];

function newTurn(role = "user", content = ""): Turn {
  return { id: Math.random().toString(36).slice(2), role, content };
}

const SAMPLE: Turn[] = [
  newTurn("user", "I'm vegetarian, please never suggest recipes with meat or fish."),
  newTurn("assistant", "Understood — I'll keep all suggestions vegetarian from now on."),
];

const VERDICT_COPY: Record<PersistResult["verdict"], string> = {
  new: "A new, durable lesson — no close match among existing learnings.",
  same: "Restates an existing active learning. Nothing new stored; the existing one was touched.",
  refine: "Same lesson family as an existing learning — merged into it.",
  contradict: "Conflicts with an existing learning, which was superseded.",
  reject: "Not worth persisting (trivial, unsafe, or one-off).",
};

export function Sandbox() {
  const { api, settings, updateSettings, configured, toast } = useApp();
  const [turns, setTurns] = useState<Turn[]>(SAMPLE);
  const [agentId, setAgentId] = useState(settings.agentId);
  const [entityId, setEntityId] = useState("");
  const [limit, setLimit] = useState(5);

  const [retrieving, setRetrieving] = useState(false);
  const [persisting, setPersisting] = useState(false);
  const [results, setResults] = useState<Learning[] | null>(null);
  const [persistResult, setPersistResult] = useState<PersistResult | null>(null);
  const [persistUnavailable, setPersistUnavailable] = useState<string | null>(null);
  const [retrieveError, setRetrieveError] = useState<string | null>(null);

  const messages = (): Message[] =>
    turns
      .filter((t) => t.content.trim() !== "")
      .map((t) => ({ role: t.role, content: t.content }));

  const hasUserTurn = turns.some((t) => t.role === "user" && t.content.trim() !== "");
  const anyContent = messages().length > 0;
  const target = agentId.trim();

  // Make the typed agent the active one everywhere. Persisting under a new id
  // is also how a brand-new agent gets added to the store's roster.
  const useAgent = () => {
    if (target && target !== settings.agentId) updateSettings({ agentId: target });
  };

  const updateTurn = (id: string, patch: Partial<Turn>) =>
    setTurns((prev) => prev.map((t) => (t.id === id ? { ...t, ...patch } : t)));
  const removeTurn = (id: string) =>
    setTurns((prev) => (prev.length > 1 ? prev.filter((t) => t.id !== id) : prev));

  const doRetrieve = async () => {
    setRetrieving(true);
    setRetrieveError(null);
    useAgent();
    try {
      const data = await api.retrieve(messages(), entityId.trim() || null, limit, target);
      setResults(data);
    } catch (err) {
      setRetrieveError(err instanceof ApiError ? err.message : String(err));
      setResults(null);
    } finally {
      setRetrieving(false);
    }
  };

  const doPersist = async () => {
    setPersisting(true);
    setPersistUnavailable(null);
    setPersistResult(null);
    useAgent();
    try {
      const res = await api.persist(messages(), entityId.trim() || null, target);
      setPersistResult(res);
      toast(
        res.decision === "persisted" ? "success" : "info",
        `Judge verdict: ${res.verdict}`,
        res.decision === "persisted" ? "Learning persisted" : "Nothing persisted",
      );
    } catch (err) {
      if (err instanceof ApiError && err.status === 503) {
        setPersistUnavailable(
          "Curation is unavailable — the Judge isn't configured on the server (no model key). This is a server setting, not an error in your input.",
        );
      } else {
        toast("error", "Persist failed", err instanceof ApiError ? err.message : String(err));
      }
    } finally {
      setPersisting(false);
    }
  };

  return (
    <div className="animate-in">
      <div className="mb-5">
        <div className="eyebrow mb-1">Curation sandbox</div>
        <h1 className="text-[24px] font-semibold tracking-tight" style={{ color: "var(--text-strong)" }}>
          Sandbox
        </h1>
        <p className="text-[13.5px] mt-1" style={{ color: "var(--muted)" }}>
          Paste a short conversation snapshot and see what the agent would retrieve — or
          run the Judge to curate it.
        </p>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] gap-4">
        {/* Composer */}
        <div className="panel px-4 py-4">
          <div className="mb-4 pb-4" style={{ borderBottom: "1px solid var(--border)" }}>
            <label className="label">
              Agent id <span style={{ color: "var(--faint)" }}>— target, or a new one to add</span>
            </label>
            <input
              className="input mono"
              placeholder="e.g. demo-agent"
              value={agentId}
              onChange={(e) => setAgentId(e.target.value)}
              spellCheck={false}
            />
            <p className="text-[11.5px] mt-1.5" style={{ color: "var(--faint)" }}>
              Retrieve / Persist run against this agent. Persisting a learning under a new
              id registers that agent — it then shows up on the Agents overview.
            </p>
          </div>

          <div className="flex items-center justify-between mb-3">
            <h2 className="text-[14px] font-semibold" style={{ color: "var(--text-strong)" }}>
              Conversation snapshot
            </h2>
            <button className="btn btn-sm" onClick={() => setTurns((p) => [...p, newTurn()])}>
              <IconAdd size={13} /> Add turn
            </button>
          </div>

          <div className="flex flex-col gap-2.5">
            {turns.map((t) => (
              <div key={t.id} className="flex gap-2 items-start">
                <select
                  className="select"
                  style={{ width: 110, flexShrink: 0 }}
                  value={t.role}
                  onChange={(e) => updateTurn(t.id, { role: e.target.value })}
                >
                  {ROLES.map((r) => (
                    <option key={r} value={r}>{r}</option>
                  ))}
                </select>
                <textarea
                  className="textarea"
                  style={{ minHeight: 44 }}
                  rows={2}
                  placeholder="Message content…"
                  value={t.content}
                  onChange={(e) => updateTurn(t.id, { content: e.target.value })}
                />
                <button
                  className="btn btn-sm btn-ghost"
                  style={{ color: "var(--faint)", flexShrink: 0 }}
                  onClick={() => removeTurn(t.id)}
                  disabled={turns.length <= 1}
                  aria-label="Remove turn"
                >
                  <IconX size={14} />
                </button>
              </div>
            ))}
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mt-4 pt-4" style={{ borderTop: "1px solid var(--border)" }}>
            <div>
              <label className="label">
                entity_id <span style={{ color: "var(--faint)" }}>(optional)</span>
              </label>
              <input
                className="input"
                placeholder="unlock a user's personal memory"
                value={entityId}
                onChange={(e) => setEntityId(e.target.value)}
              />
            </div>
            <div>
              <label className="label">Retrieve limit</label>
              <input
                className="input"
                type="number"
                min={1}
                max={50}
                value={limit}
                onChange={(e) => setLimit(Math.min(50, Math.max(1, Number(e.target.value) || 1)))}
              />
            </div>
          </div>

          {!hasUserTurn && anyContent && (
            <p className="text-[12px] mt-3" style={{ color: "var(--warn)" }}>
              Note: only <span className="mono">user</span>-role turns feed the Judge. Add a
              user turn for Persist to have anything to consider.
            </p>
          )}

          <div className="flex gap-2 mt-4">
            <button
              className="btn flex-1"
              onClick={doRetrieve}
              disabled={!configured || !target || !anyContent || retrieving}
              title="Read-only. No LLM call."
            >
              {retrieving ? <Spinner size={13} /> : <IconSearch size={14} />}
              Retrieve
            </button>
            <button
              className="btn btn-primary flex-1"
              onClick={doPersist}
              disabled={!configured || !target || !anyContent || persisting}
              title="Runs the LLM Judge — costs tokens."
            >
              {persisting ? <Spinner size={13} /> : <IconBolt size={14} />}
              Persist
            </button>
          </div>
          <div className="flex items-center justify-between mt-2 text-[11.5px]" style={{ color: "var(--faint)" }}>
            <span className="inline-flex items-center gap-1"><IconSearch size={11} /> Retrieve is free &amp; read-only</span>
            <span className="inline-flex items-center gap-1"><IconBolt size={11} /> Persist runs the Judge (token cost)</span>
          </div>
        </div>

        {/* Results */}
        <div className="flex flex-col gap-4">
          {/* Persist verdict */}
          {(persistResult || persistUnavailable || persisting) && (
            <div className="panel px-4 py-4">
              <h2 className="text-[14px] font-semibold mb-3" style={{ color: "var(--text-strong)" }}>
                Judge verdict
              </h2>
              {persisting ? (
                <div className="flex items-center gap-2 text-[13px]" style={{ color: "var(--muted)" }}>
                  <Spinner size={14} /> Running the Judge…
                </div>
              ) : persistUnavailable ? (
                <div className="panel px-3 py-3" style={{ background: "var(--warn-bg)", borderColor: "var(--warn-border)" }}>
                  <div className="text-[13px] font-medium mb-1" style={{ color: "var(--warn)" }}>
                    Curation unavailable
                  </div>
                  <div className="text-[12.5px]" style={{ color: "var(--muted)" }}>{persistUnavailable}</div>
                </div>
              ) : persistResult ? (
                <VerdictCard result={persistResult} />
              ) : null}
            </div>
          )}

          {/* Retrieve results */}
          <div className="panel px-4 py-4 flex-1">
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-[14px] font-semibold" style={{ color: "var(--text-strong)" }}>
                Retrieved learnings
              </h2>
              {results && (
                <span className="eyebrow">{results.length} result{results.length === 1 ? "" : "s"}</span>
              )}
            </div>

            {retrieveError ? (
              <div className="text-[13px]" style={{ color: "var(--danger)" }}>{retrieveError}</div>
            ) : retrieving ? (
              <div className="grid place-items-center py-10"><Spinner size={20} /></div>
            ) : results === null ? (
              <EmptyState
                icon={<IconSearch size={18} />}
                title="No retrieval run yet"
                hint="Retrieve shows the ranked learnings the agent would surface for this conversation — instantly, with no model call."
              />
            ) : results.length === 0 ? (
              <EmptyState
                title="Nothing retrieved"
                hint="No stored learning is relevant to this snapshot for the given scope/entity."
              />
            ) : (
              <ol className="flex flex-col gap-2">
                {results.map((l, i) => (
                  <li key={l.id} className="panel px-3 py-2.5" style={{ background: "var(--panel-2)" }}>
                    <div className="flex items-center gap-2 mb-1">
                      <span
                        className="grid place-items-center rounded-md tabular-nums font-semibold shrink-0"
                        style={{ width: 20, height: 20, fontSize: 11, background: "var(--bg)", border: "1px solid var(--border)", color: "var(--muted)" }}
                      >
                        {i + 1}
                      </span>
                      <StatusBadge value={l.status} />
                      <ScopeBadge value={l.scope} />
                      <OutcomeBadge value={l.outcome} />
                      <span className="ml-auto text-[11px] tabular-nums" style={{ color: "var(--faint)" }}>
                        {num(l.hits)} hits
                      </span>
                    </div>
                    <div className="text-[11.5px] mb-0.5" style={{ color: "var(--faint)" }}>{l.context}</div>
                    <div className="text-[13px]" style={{ color: "var(--text)" }}>{l.content}</div>
                    {l.tags.length > 0 && (
                      <div className="flex flex-wrap gap-1 mt-1.5">
                        {l.tags.map((t) => <Tag key={t}>{t}</Tag>)}
                      </div>
                    )}
                  </li>
                ))}
              </ol>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function VerdictCard({ result }: { result: PersistResult }) {
  const hue = verdictHue(result.verdict);
  return (
    <div>
      <div
        className="panel px-4 py-4 mb-3"
        style={{
          background: `var(--${hue}-bg)`,
          borderColor: `var(--${hue}-border)`,
        }}
      >
        <div className="flex items-center gap-3">
          <VerdictBadge value={result.verdict} />
          <span
            className="badge"
            style={{
              color: result.decision === "persisted" ? "var(--ok)" : "var(--neutral)",
              background: result.decision === "persisted" ? "var(--ok-bg)" : "var(--neutral-bg)",
              borderColor: result.decision === "persisted" ? "var(--ok-border)" : "var(--neutral-border)",
            }}
          >
            <span className="dot" />
            {result.decision}
          </span>
        </div>
        <p className="text-[13px] mt-2.5" style={{ color: "var(--text)" }}>
          {VERDICT_COPY[result.verdict]}
        </p>
      </div>

      <div className="text-[13px]">
        {result.learning_id && (
          <div className="flex items-center justify-between py-2 border-t" style={{ borderColor: "var(--border)" }}>
            <span style={{ color: "var(--muted)" }}>Affected learning</span>
            <CopyId id={result.learning_id} label="learning id" head={28} />
          </div>
        )}
        {result.superseded_id && (
          <div className="flex items-center justify-between py-2 border-t" style={{ borderColor: "var(--border)" }}>
            <span style={{ color: "var(--muted)" }} className="inline-flex items-center gap-1.5">
              <IconLink size={13} /> Superseded
            </span>
            <CopyId id={result.superseded_id} label="superseded id" head={28} />
          </div>
        )}
        {result.reason && (
          <div className="py-2 border-t" style={{ borderColor: "var(--border)" }}>
            <div className="eyebrow mb-1">Reason</div>
            <div style={{ color: "var(--text)" }}>{result.reason}</div>
          </div>
        )}
      </div>
    </div>
  );
}
