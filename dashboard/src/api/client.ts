import type {
  AgentStats,
  AgentSummary,
  Learning,
  LearningPatch,
  Message,
  PersistResult,
  TokenUsageStats,
} from "./types";

export interface ApiConfig {
  baseUrl: string;
  agentId: string;
  token: string; // optional bearer; empty string = none
}

// One row in the operator-facing activity/request log.
export interface LogEntry {
  id: string;
  at: number;
  method: string;
  path: string; // path only (no base) for compact display
  url: string;
  status: number | null; // null = network error / never reached
  ok: boolean;
  durationMs: number;
  requestBody?: unknown;
  responseBody?: unknown;
  error?: string;
}

export class ApiError extends Error {
  status: number | null;
  body: unknown;
  constructor(message: string, status: number | null, body?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

type Listener = (entry: LogEntry) => void;

function uid(): string {
  return Math.random().toString(36).slice(2, 10) + Date.now().toString(36);
}

function trimBase(base: string): string {
  return base.replace(/\/+$/, "");
}

export class ApiClient {
  private config: ApiConfig;
  private listeners = new Set<Listener>();

  constructor(config: ApiConfig) {
    this.config = config;
  }

  setConfig(config: ApiConfig) {
    this.config = config;
  }

  onLog(fn: Listener): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  private emit(entry: LogEntry) {
    for (const fn of this.listeners) fn(entry);
  }

  private headers(hasBody: boolean): HeadersInit {
    const h: Record<string, string> = { Accept: "application/json" };
    if (hasBody) h["Content-Type"] = "application/json";
    const token = this.config.token.trim();
    if (token) h["Authorization"] = `Bearer ${token}`;
    return h;
  }

  // Core request. `path` is appended to baseUrl verbatim (already includes /v1…).
  private async request<T>(
    method: string,
    path: string,
    body?: unknown,
  ): Promise<T> {
    const base = trimBase(this.config.baseUrl);
    const url = `${base}${path}`;
    const started = performance.now();
    const hasBody = body !== undefined;

    const entry: LogEntry = {
      id: uid(),
      at: Date.now(),
      method,
      path,
      url,
      status: null,
      ok: false,
      durationMs: 0,
      requestBody: hasBody ? body : undefined,
    };

    try {
      const res = await fetch(url, {
        method,
        headers: this.headers(hasBody),
        body: hasBody ? JSON.stringify(body) : undefined,
      });
      entry.status = res.status;
      entry.durationMs = Math.round(performance.now() - started);

      const text = await res.text();
      let parsed: unknown = undefined;
      if (text) {
        try {
          parsed = JSON.parse(text);
        } catch {
          parsed = text;
        }
      }
      entry.responseBody = parsed;
      entry.ok = res.ok;

      if (!res.ok) {
        const detail =
          parsed && typeof parsed === "object" && "detail" in parsed
            ? String((parsed as { detail: unknown }).detail)
            : res.statusText || `HTTP ${res.status}`;
        entry.error = detail;
        this.emit(entry);
        throw new ApiError(detail, res.status, parsed);
      }

      this.emit(entry);
      return parsed as T;
    } catch (err) {
      if (err instanceof ApiError) throw err;
      // Network / CORS / DNS failure — never reached the server.
      entry.durationMs = Math.round(performance.now() - started);
      const msg =
        err instanceof Error ? err.message : "network request failed";
      entry.error = msg;
      this.emit(entry);
      throw new ApiError(
        `Could not reach the API at ${base}. ${msg}`,
        null,
        undefined,
      );
    }
  }

  // `agentId` overrides the active agent for one call (used by the Sandbox,
  // which can target any agent by name).
  private agentPath(suffix: string, agentId?: string): string {
    const id = encodeURIComponent(agentId ?? this.config.agentId);
    return `/v1/agents/${id}${suffix}`;
  }

  // -- health (unversioned) ------------------------------------------------
  health(): Promise<{ status: string }> {
    return this.request("GET", "/health");
  }

  // -- agent roster (cross-agent, agent-less) ------------------------------
  listAgents(): Promise<AgentSummary[]> {
    return this.request("GET", "/v1/agents");
  }

  // -- retrieval / curation ------------------------------------------------
  retrieve(
    messages: Message[],
    entityId: string | null,
    limit: number,
    agentId?: string,
  ): Promise<Learning[]> {
    return this.request("POST", this.agentPath("/retrieve", agentId), {
      messages,
      entity_id: entityId,
      limit,
    });
  }

  persist(
    messages: Message[],
    entityId: string | null,
    agentId?: string,
  ): Promise<PersistResult> {
    return this.request("POST", this.agentPath("/persist", agentId), {
      messages,
      entity_id: entityId,
    });
  }

  // -- listing -------------------------------------------------------------
  listPersonal(
    entityId: string,
    limit: number,
    offset: number,
  ): Promise<Learning[]> {
    const q = new URLSearchParams({
      entity_id: entityId,
      limit: String(limit),
      offset: String(offset),
    });
    return this.request("GET", this.agentPath(`/learnings/personal?${q}`));
  }

  listGlobal(limit: number, offset: number): Promise<Learning[]> {
    const q = new URLSearchParams({
      limit: String(limit),
      offset: String(offset),
    });
    return this.request("GET", this.agentPath(`/learnings/global?${q}`));
  }

  // -- single-learning management -----------------------------------------
  approve(id: string): Promise<Learning> {
    return this.request(
      "POST",
      this.agentPath(`/learnings/${encodeURIComponent(id)}/approve`),
    );
  }

  disapprove(id: string): Promise<Learning> {
    return this.request(
      "POST",
      this.agentPath(`/learnings/${encodeURIComponent(id)}/disapprove`),
    );
  }

  update(id: string, patch: LearningPatch): Promise<Learning> {
    return this.request(
      "PATCH",
      this.agentPath(`/learnings/${encodeURIComponent(id)}`),
      patch,
    );
  }

  softDelete(id: string): Promise<Learning> {
    return this.request(
      "DELETE",
      this.agentPath(`/learnings/${encodeURIComponent(id)}`),
    );
  }

  // -- stats / tokens ------------------------------------------------------
  stats(topN: number): Promise<AgentStats> {
    return this.request("GET", this.agentPath(`/stats?top_n=${topN}`));
  }

  tokens(): Promise<TokenUsageStats> {
    return this.request("GET", this.agentPath("/tokens"));
  }
}
