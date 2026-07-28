// Persisted JWT session (access + refresh tokens). Separate key from
// pl-console:settings (lib/settings.ts), which holds the agent_id + API key
// used for the existing agent-runtime calls — two different auth schemes,
// two different storage slots.

export interface AuthTokens {
  accessToken: string;
  refreshToken: string;
}

const KEY = "pl-console:auth";

export function loadTokens(): AuthTokens | null {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<AuthTokens>;
    if (!parsed.accessToken || !parsed.refreshToken) return null;
    return parsed as AuthTokens;
  } catch {
    return null;
  }
}

export function saveTokens(tokens: AuthTokens | null): void {
  try {
    if (tokens) localStorage.setItem(KEY, JSON.stringify(tokens));
    else localStorage.removeItem(KEY);
  } catch {
    /* storage unavailable — session simply won't persist */
  }
}
