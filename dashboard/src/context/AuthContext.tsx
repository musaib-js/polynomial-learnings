import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { authApi, AuthError } from "../api/auth";
import { loadTokens, saveTokens, type AuthTokens } from "../lib/authStorage";
import type { User } from "../api/types";
import { useApp } from "./AppContext";

type Status = "checking" | "anon" | "authed";

interface AuthContextValue {
  status: Status;
  user: User | null;
  accessToken: string | null;
  signup: (email: string, password: string, name?: string) => Promise<void>;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
}

const Ctx = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const { settings, updateSettings, toast } = useApp();
  const [status, setStatus] = useState<Status>("checking");
  const [user, setUser] = useState<User | null>(null);
  const [tokens, setTokens] = useState<AuthTokens | null>(() => loadTokens());

  const baseUrl = settings.baseUrl;

  // Ensures the account has at least one agent + API key so the pre-existing
  // agent-runtime screens (Overview/Learnings/Sandbox/Activity) keep working
  // unmodified — they authenticate with settings.token (an API key), not the
  // JWT this context manages. Only runs once: skipped if Settings already
  // has an agent/token configured (e.g. a returning session on this browser).
  const ensureAgentProvisioned = useCallback(
    async (accessToken: string) => {
      if (settings.agentId.trim() && settings.token.trim()) return;
      try {
        let agents = await authApi.listMyAgents(baseUrl, accessToken);
        let agent = agents[0];
        if (!agent) {
          agent = await authApi.createAgent(baseUrl, accessToken, "My Agent");
        }
        const key = await authApi.createApiKey(baseUrl, accessToken, "console");
        updateSettings({ agentId: agent.agent_id, token: key.raw_key });
      } catch {
        // Non-fatal: the user can still finish signing in and configure
        // Settings manually if auto-provisioning fails for any reason.
        toast(
          "info",
          "Signed in, but couldn't auto-configure an agent",
          "Set an agent id and API key in Settings to use the console.",
        );
      }
    },
    [baseUrl, settings.agentId, settings.token, updateSettings, toast],
  );

  useEffect(() => {
    let cancelled = false;
    async function check() {
      if (!tokens) {
        setStatus("anon");
        return;
      }
      try {
        const me = await authApi.me(baseUrl, tokens.accessToken);
        if (cancelled) return;
        setUser(me);
        setStatus("authed");
      } catch {
        try {
          const refreshed = await authApi.refresh(baseUrl, tokens.refreshToken);
          if (cancelled) return;
          const next = {
            accessToken: refreshed.access_token,
            refreshToken: refreshed.refresh_token,
          };
          saveTokens(next);
          setTokens(next);
          const me = await authApi.me(baseUrl, next.accessToken);
          if (cancelled) return;
          setUser(me);
          setStatus("authed");
        } catch {
          if (cancelled) return;
          saveTokens(null);
          setTokens(null);
          setUser(null);
          setStatus("anon");
        }
      }
    }
    check();
    return () => {
      cancelled = true;
    };
    // Runs once on mount (and whenever baseUrl changes) — login/signup below
    // handle the post-auth state transition directly rather than re-running this.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [baseUrl]);

  const afterAuth = useCallback(
    async (pair: { access_token: string; refresh_token: string }) => {
      const next = { accessToken: pair.access_token, refreshToken: pair.refresh_token };
      saveTokens(next);
      setTokens(next);
      const me = await authApi.me(baseUrl, next.accessToken);
      setUser(me);
      setStatus("authed");
      await ensureAgentProvisioned(next.accessToken);
    },
    [baseUrl, ensureAgentProvisioned],
  );

  const signup = useCallback(
    async (email: string, password: string, name?: string) => {
      const pair = await authApi.signup(baseUrl, email, password, name);
      await afterAuth(pair);
    },
    [baseUrl, afterAuth],
  );

  const login = useCallback(
    async (email: string, password: string) => {
      const pair = await authApi.login(baseUrl, email, password);
      await afterAuth(pair);
    },
    [baseUrl, afterAuth],
  );

  const logout = useCallback(() => {
    if (tokens) authApi.logout(baseUrl, tokens.refreshToken).catch(() => {});
    saveTokens(null);
    setTokens(null);
    setUser(null);
    setStatus("anon");
  }, [baseUrl, tokens]);

  const value = useMemo<AuthContextValue>(
    () => ({ status, user, accessToken: tokens?.accessToken ?? null, signup, login, logout }),
    [status, user, tokens, signup, login, logout],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthContextValue {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAuth must be used within AuthProvider");
  return v;
}

export { AuthError };
