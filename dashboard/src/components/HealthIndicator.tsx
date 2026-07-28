import { useCallback, useEffect, useState } from "react";
import { useApp } from "../context/AppContext";

type Health = "checking" | "healthy" | "unreachable";

// Polls GET /health (unversioned). Purely a liveness signal for the header —
// failures here are shown calmly, not as an alarm.
export function HealthIndicator() {
  const { api, settings } = useApp();
  const [state, setState] = useState<Health>("checking");

  const check = useCallback(async () => {
    setState("checking");
    try {
      await api.health();
      setState("healthy");
    } catch {
      setState("unreachable");
    }
  }, [api]);

  useEffect(() => {
    check();
    const t = window.setInterval(check, 30_000);
    return () => window.clearInterval(t);
    // Re-check whenever the base URL changes.
  }, [check, settings.baseUrl]);

  const color =
    state === "healthy"
      ? "var(--ok)"
      : state === "unreachable"
        ? "var(--danger)"
        : "var(--warn)";
  const label =
    state === "healthy"
      ? "healthy"
      : state === "unreachable"
        ? "unreachable"
        : "checking…";

  return (
    <button
      onClick={check}
      className="btn-ghost inline-flex items-center gap-2 rounded-full px-2.5 py-1"
      title="API health — click to re-check"
      style={{ border: "1px solid var(--border)" }}
    >
      <span
        className="rounded-full"
        style={{
          width: 7,
          height: 7,
          background: color,
          boxShadow: `0 0 0 3px color-mix(in srgb, ${color} 20%, transparent)`,
        }}
      />
      <span className="text-[12px]" style={{ color: "var(--muted)" }}>
        {label}
      </span>
    </button>
  );
}
