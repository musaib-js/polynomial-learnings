import { useState } from "react";
import { useApp } from "../context/AppContext";
import type { LogEntry } from "../api/client";
import { EmptyState } from "../components/ui";
import { IconActivity, IconChevron } from "../components/icons";
import { timeOfDay } from "../lib/format";

function statusHue(entry: LogEntry): string {
  if (entry.status === null) return "var(--danger)";
  if (entry.ok) return "var(--ok)";
  if (entry.status === 503) return "var(--warn)";
  return "var(--danger)";
}

function pretty(v: unknown): string {
  if (v === undefined) return "";
  if (typeof v === "string") return v;
  try {
    return JSON.stringify(v, null, 2);
  } catch {
    return String(v);
  }
}

function Row({ entry }: { entry: LogEntry }) {
  const [open, setOpen] = useState(false);
  const hue = statusHue(entry);
  return (
    <div style={{ borderBottom: "1px solid var(--border)" }}>
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center gap-3 px-4 py-2.5 text-left transition-colors"
        onMouseEnter={(e) => (e.currentTarget.style.background = "var(--hover)")}
        onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
      >
        <span style={{ color: "var(--faint)", transform: open ? "rotate(90deg)" : "none", transition: "transform .12s" }}>
          <IconChevron size={13} />
        </span>
        <span
          className="mono shrink-0 text-center rounded px-1.5 py-0.5 font-semibold"
          style={{ fontSize: 10.5, minWidth: 52, background: "var(--panel-2)", border: "1px solid var(--border)", color: "var(--muted)" }}
        >
          {entry.method}
        </span>
        <span className="mono flex-1 truncate" style={{ fontSize: 12, color: "var(--text)" }}>
          {entry.path}
        </span>
        <span className="tabular-nums text-[11.5px] shrink-0" style={{ color: "var(--faint)" }}>
          {entry.durationMs}ms
        </span>
        <span className="mono tabular-nums shrink-0 font-semibold" style={{ fontSize: 12, color: hue, minWidth: 34, textAlign: "right" }}>
          {entry.status ?? "ERR"}
        </span>
        <span className="tabular-nums text-[11px] shrink-0 hidden sm:inline" style={{ color: "var(--faint)", minWidth: 66, textAlign: "right" }}>
          {timeOfDay(entry.at)}
        </span>
      </button>
      {open && (
        <div className="px-4 pb-3.5 pt-1 grid grid-cols-1 lg:grid-cols-2 gap-3 animate-in">
          <div>
            <div className="eyebrow mb-1">Request{entry.requestBody === undefined ? " — no body" : ""}</div>
            {entry.requestBody !== undefined && (
              <pre className="mono overflow-x-auto rounded-lg px-3 py-2" style={{ fontSize: 11.5, background: "var(--bg)", border: "1px solid var(--border)", color: "var(--muted)", maxHeight: 260 }}>
                {pretty(entry.requestBody)}
              </pre>
            )}
            <div className="mono mt-1.5 break-all" style={{ fontSize: 10.5, color: "var(--faint)" }}>{entry.url}</div>
          </div>
          <div>
            <div className="eyebrow mb-1">Response {entry.error ? "— error" : ""}</div>
            <pre className="mono overflow-x-auto rounded-lg px-3 py-2" style={{ fontSize: 11.5, background: "var(--bg)", border: "1px solid var(--border)", color: entry.error ? "var(--danger)" : "var(--muted)", maxHeight: 260 }}>
              {entry.error ? entry.error : pretty(entry.responseBody) || "(empty)"}
            </pre>
          </div>
        </div>
      )}
    </div>
  );
}

export function Activity() {
  const { log, clearLog } = useApp();

  return (
    <div className="animate-in">
      <div className="flex items-end justify-between gap-4 mb-5">
        <div>
          <div className="eyebrow mb-1">Audit</div>
          <h1 className="text-[24px] font-semibold tracking-tight" style={{ color: "var(--text-strong)" }}>
            Activity log
          </h1>
          <p className="text-[13.5px] mt-1" style={{ color: "var(--muted)" }}>
            Every API call this session made, and exactly what came back. Transparency for
            an audit tool.
          </p>
        </div>
        {log.length > 0 && (
          <button className="btn btn-sm" onClick={clearLog}>Clear log</button>
        )}
      </div>

      {log.length === 0 ? (
        <div className="panel">
          <EmptyState
            icon={<IconActivity size={20} />}
            title="No requests yet"
            hint="Interact with the console — load stats, browse learnings, run the sandbox — and every request will be recorded here."
          />
        </div>
      ) : (
        <div className="panel overflow-hidden">
          <div className="flex items-center justify-between px-4 py-2" style={{ borderBottom: "1px solid var(--border)", color: "var(--faint)" }}>
            <span className="eyebrow">{log.length} request{log.length === 1 ? "" : "s"} (most recent first)</span>
          </div>
          {log.map((e) => <Row key={e.id} entry={e} />)}
        </div>
      )}
    </div>
  );
}
