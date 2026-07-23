import type { ApiConfig } from "../api/client";

// Persisted operator settings. The token is stored in localStorage like the
// rest — this is an internal admin tool run on a trusted machine, and the
// alternative (retyping the bearer every load) is worse for the operator.
// No infra secrets (DB URLs, provider keys) ever live here.

export interface Settings extends ApiConfig {
  topN: number; // stats "most used" size
}

const KEY = "pl-console:settings";

const DEFAULTS: Settings = {
  baseUrl: "http://localhost:8000",
  agentId: "demo-agent",
  token: "",
  topN: 5,
};

export function loadSettings(): Settings {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return { ...DEFAULTS };
    const parsed = JSON.parse(raw) as Partial<Settings>;
    return { ...DEFAULTS, ...parsed };
  } catch {
    return { ...DEFAULTS };
  }
}

export function saveSettings(s: Settings): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(s));
  } catch {
    /* storage unavailable — settings simply won't persist */
  }
}

export function loadTheme(): "dark" | "light" {
  const t = localStorage.getItem("pl-console:theme");
  return t === "light" ? "light" : "dark";
}

export function saveTheme(t: "dark" | "light"): void {
  try {
    localStorage.setItem("pl-console:theme", t);
  } catch {
    /* ignore */
  }
}
