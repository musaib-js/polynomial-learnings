// TypeScript mirrors of the polynomial-learnings API models (learnings/models.py).
// Kept deliberately close to the server shapes so the client needs no mapping.

export type Scope = "personal" | "global";
export type Outcome = "positive" | "negative" | "neutral";
export type Status = "active" | "superseded" | "rejected" | "pending_approval";
export type Verdict = "new" | "same" | "refine" | "contradict" | "reject";
export type Decision = "persisted" | "rejected";

export interface Learning {
  id: string;
  agent_id: string;
  entity_id: string | null;
  scope: Scope;
  status: Status;
  supersedes: string | null;
  context: string;
  content: string;
  outcome: Outcome;
  reason: string | null;
  original_output: string | null;
  corrected_output: string | null;
  category: string | null;
  tags: string[];
  created_at: string;
  last_used_at: string | null;
  hits: number;
}

export interface AgentSummary {
  agent_id: string;
  total_learnings: number;
  active: number;
  distinct_entities: number;
  last_activity: string | null;
}

export interface MostUsedLearning {
  id: string;
  context: string;
  content: string;
  hits: number;
}

export interface AgentStats {
  agent_id: string;
  total: number;
  by_status: Record<string, number>;
  by_scope: Record<string, number>;
  total_hits: number;
  avg_hits: number;
  distinct_entities: number;
  last_used_at: string | null;
  last_created_at: string | null;
  most_used: MostUsedLearning[];
}

export interface OperationTokenTotals {
  operation: string;
  calls: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
}

export interface TokenUsageStats {
  agent_id: string;
  total_calls: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  by_operation: OperationTokenTotals[];
  by_model: Record<string, number>;
}

export interface PersistResult {
  decision: Decision;
  verdict: Verdict;
  learning_id: string | null;
  superseded_id: string | null;
  reason: string | null;
}

export interface Message {
  role: string;
  content: string;
}

// Fields the operator is allowed to edit (PATCH /learnings/{id}).
export interface LearningPatch {
  context?: string;
  content?: string;
  category?: string | null;
  tags?: string[];
  reason?: string | null;
  outcome?: Outcome;
}

// -- SaaS auth / tenancy (learnings/auth/, /v1/auth/*, /v1/dashboard/*) -----

export type UserRole = "member" | "admin";

export interface User {
  id: string;
  email: string;
  name: string | null;
  role: UserRole;
  email_verified: boolean;
  created_at: string;
  last_login_at: string | null;
}

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export interface AgentRecord {
  agent_id: string;
  display_name: string;
  require_approval: boolean;
  created_at: string;
  updated_at: string;
}

export interface ApiKeyCreated {
  id: string;
  name: string;
  key_prefix: string;
  raw_key: string;
  created_at: string;
}

export interface ApiKeySummary {
  id: string;
  name: string;
  key_prefix: string;
  created_at: string;
  last_used_at: string | null;
  expires_at: string | null;
  revoked_at: string | null;
}

// -- analytics (learnings/analytics.py, /v1/dashboard/agents/{id}/analytics/*) --

export interface LearningsGrowthPoint {
  bucket: string;
  created: number;
}

export interface LearningsGrowth {
  total: number;
  personal: number;
  global: number;
  approved: number;
  pending: number;
  rejected: number;
  series: LearningsGrowthPoint[];
}

export interface UsageTrendPoint {
  bucket: string;
  retrievals: number;
}

export interface MostUsedEvent {
  learning_id: string;
  retrievals: number;
}

export interface RecentlyRetrieved {
  learning_id: string;
  occurred_at: string;
}

export interface UsageTrends {
  series: UsageTrendPoint[];
  most_used: MostUsedEvent[];
  recently_retrieved: RecentlyRetrieved[];
}
