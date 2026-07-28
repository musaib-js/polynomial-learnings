// Thin client for /v1/auth/* and the /v1/dashboard/* provisioning calls used
// right after login/signup. Deliberately separate from ApiClient (client.ts):
// that class is bound to one agent_id + API key (the pip-package-shaped
// runtime auth), while these calls are JWT-bearer, human-account auth.

import type {
  AgentRecord,
  ApiKeyCreated,
  ApiKeySummary,
  LearningsGrowth,
  TokenPair,
  UsageTrends,
  User,
} from "./types";

export class AuthError extends Error {
  status: number | null;
  constructor(message: string, status: number | null) {
    super(message);
    this.name = "AuthError";
    this.status = status;
  }
}

function trimBase(base: string): string {
  return base.replace(/\/+$/, "");
}

async function call<T>(
  baseUrl: string,
  method: string,
  path: string,
  opts: { body?: unknown; token?: string } = {},
): Promise<T> {
  const url = `${trimBase(baseUrl)}${path}`;
  const headers: Record<string, string> = { Accept: "application/json" };
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  if (opts.token) headers["Authorization"] = `Bearer ${opts.token}`;

  let res: Response;
  try {
    res = await fetch(url, {
      method,
      headers,
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
    });
  } catch (err) {
    const msg = err instanceof Error ? err.message : "network request failed";
    throw new AuthError(`Could not reach the API at ${baseUrl}. ${msg}`, null);
  }

  const text = await res.text();
  let parsed: unknown = undefined;
  if (text) {
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = text;
    }
  }

  if (!res.ok) {
    const detail =
      parsed && typeof parsed === "object" && "detail" in parsed
        ? String((parsed as { detail: unknown }).detail)
        : res.statusText || `HTTP ${res.status}`;
    throw new AuthError(detail, res.status);
  }
  return parsed as T;
}

export const authApi = {
  signup(baseUrl: string, email: string, password: string, name?: string) {
    return call<TokenPair>(baseUrl, "POST", "/v1/auth/signup", {
      body: { email, password, name: name || undefined },
    });
  },

  login(baseUrl: string, email: string, password: string) {
    return call<TokenPair>(baseUrl, "POST", "/v1/auth/login", {
      body: { email, password },
    });
  },

  refresh(baseUrl: string, refreshToken: string) {
    return call<TokenPair>(baseUrl, "POST", "/v1/auth/refresh", {
      body: { refresh_token: refreshToken },
    });
  },

  logout(baseUrl: string, refreshToken: string) {
    return call<void>(baseUrl, "POST", "/v1/auth/logout", {
      body: { refresh_token: refreshToken },
    });
  },

  me(baseUrl: string, accessToken: string) {
    return call<User>(baseUrl, "GET", "/v1/auth/me", { token: accessToken });
  },

  forgotPassword(baseUrl: string, email: string) {
    return call<void>(baseUrl, "POST", "/v1/auth/forgot-password", {
      body: { email },
    });
  },

  resetPassword(baseUrl: string, token: string, newPassword: string) {
    return call<void>(baseUrl, "POST", "/v1/auth/reset-password", {
      body: { token, new_password: newPassword },
    });
  },

  // -- post-login provisioning ---------------------------------------------
  // The pre-existing dashboard screens (Overview/Learnings/Sandbox/etc.) all
  // call /v1/agents/{agent_id}/... with an API key (see api/client.ts), not a
  // JWT. Right after auth we make sure the account has at least one agent +
  // one API key so those screens keep working without the user hand-typing
  // anything into Settings.
  listMyAgents(baseUrl: string, accessToken: string) {
    return call<AgentRecord[]>(baseUrl, "GET", "/v1/dashboard/agents", {
      token: accessToken,
    });
  },

  createAgent(baseUrl: string, accessToken: string, displayName: string) {
    return call<AgentRecord>(baseUrl, "POST", "/v1/dashboard/agents", {
      token: accessToken,
      body: { display_name: displayName },
    });
  },

  createApiKey(baseUrl: string, accessToken: string, name: string) {
    return call<ApiKeyCreated>(baseUrl, "POST", "/v1/dashboard/api-keys", {
      token: accessToken,
      body: { name },
    });
  },

  // -- API key management (ApiKeys screen) ---------------------------------
  listApiKeys(baseUrl: string, accessToken: string) {
    return call<ApiKeySummary[]>(baseUrl, "GET", "/v1/dashboard/api-keys", {
      token: accessToken,
    });
  },

  revokeApiKey(baseUrl: string, accessToken: string, keyId: string) {
    return call<ApiKeySummary>(
      baseUrl,
      "POST",
      `/v1/dashboard/api-keys/${encodeURIComponent(keyId)}/revoke`,
      { token: accessToken },
    );
  },

  regenerateApiKey(baseUrl: string, accessToken: string, keyId: string) {
    return call<ApiKeyCreated>(
      baseUrl,
      "POST",
      `/v1/dashboard/api-keys/${encodeURIComponent(keyId)}/regenerate`,
      { token: accessToken },
    );
  },

  // -- analytics (Analytics screen) ----------------------------------------
  analyticsLearnings(
    baseUrl: string,
    accessToken: string,
    agentId: string,
    bucket: "day" | "week" | "month",
  ) {
    return call<LearningsGrowth>(
      baseUrl,
      "GET",
      `/v1/dashboard/agents/${encodeURIComponent(agentId)}/analytics/learnings?bucket=${bucket}`,
      { token: accessToken },
    );
  },

  analyticsUsage(
    baseUrl: string,
    accessToken: string,
    agentId: string,
    bucket: "day" | "week" | "month",
  ) {
    return call<UsageTrends>(
      baseUrl,
      "GET",
      `/v1/dashboard/agents/${encodeURIComponent(agentId)}/analytics/usage?bucket=${bucket}`,
      { token: accessToken },
    );
  },
};
