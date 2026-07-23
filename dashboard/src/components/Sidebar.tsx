import type { ReactNode } from "react";
import {
  IconActivity,
  IconLearnings,
  IconOverview,
  IconSandbox,
  IconSettings,
} from "./icons";
import { useApp } from "../context/AppContext";

export type Route = "overview" | "learnings" | "sandbox" | "activity" | "settings";

const NAV: { key: Route; label: string; icon: (p: { size?: number }) => ReactNode }[] =
  [
    { key: "overview", label: "Overview", icon: IconOverview },
    { key: "learnings", label: "Learnings", icon: IconLearnings },
    { key: "sandbox", label: "Sandbox", icon: IconSandbox },
    { key: "activity", label: "Activity", icon: IconActivity },
    { key: "settings", label: "Settings", icon: IconSettings },
  ];

export function Sidebar({
  route,
  onNavigate,
}: {
  route: Route;
  onNavigate: (r: Route) => void;
}) {
  const { settings, log } = useApp();
  const activityCount = log.length;

  return (
    <aside
      className="flex flex-col shrink-0"
      style={{
        width: 232,
        background: "var(--sidebar)",
        borderRight: "1px solid var(--border)",
      }}
    >
      <div className="px-4 py-4 border-b" style={{ borderColor: "var(--border)" }}>
        <div className="flex items-center gap-2.5">
          <span
            className="grid place-items-center rounded-lg font-bold"
            style={{
              width: 28,
              height: 28,
              background: "var(--accent)",
              color: "var(--accent-fg)",
              fontSize: 15,
            }}
          >
            p
          </span>
          <div className="leading-tight">
            <div
              className="text-[14px] font-semibold"
              style={{ color: "var(--text-strong)" }}
            >
              polynomial
            </div>
            <div className="eyebrow" style={{ fontSize: 9.5 }}>
              learnings · console
            </div>
          </div>
        </div>
      </div>

      <nav className="flex-1 px-2.5 py-3 flex flex-col gap-0.5">
        {NAV.map(({ key, label, icon: Icon }) => {
          const active = route === key;
          return (
            <button
              key={key}
              onClick={() => onNavigate(key)}
              className="group flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-[13.5px] font-medium transition-colors"
              style={{
                color: active ? "var(--text-strong)" : "var(--muted)",
                background: active ? "var(--hover)" : "transparent",
                border: active
                  ? "1px solid var(--border)"
                  : "1px solid transparent",
              }}
              onMouseEnter={(e) => {
                if (!active) e.currentTarget.style.background = "var(--hover)";
              }}
              onMouseLeave={(e) => {
                if (!active) e.currentTarget.style.background = "transparent";
              }}
            >
              <span
                style={{ color: active ? "var(--accent)" : "var(--faint)" }}
                className="shrink-0"
              >
                <Icon size={17} />
              </span>
              <span className="flex-1 text-left">{label}</span>
              {key === "activity" && activityCount > 0 && (
                <span
                  className="mono rounded-full px-1.5 tabular-nums"
                  style={{
                    fontSize: 10.5,
                    background: "var(--panel-2)",
                    border: "1px solid var(--border)",
                    color: "var(--faint)",
                  }}
                >
                  {activityCount > 99 ? "99+" : activityCount}
                </span>
              )}
            </button>
          );
        })}
      </nav>

      <div className="px-4 py-3.5 border-t" style={{ borderColor: "var(--border)" }}>
        <div className="eyebrow mb-1">Active agent</div>
        <div
          className="mono truncate"
          style={{ color: "var(--text)", fontSize: 12.5 }}
          title={settings.agentId}
        >
          {settings.agentId || "—"}
        </div>
      </div>
    </aside>
  );
}
