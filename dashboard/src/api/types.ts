// TypeScript mirrors of the polynomial-learnings API models (learnings/models.py).
// Kept deliberately close to the server shapes so the client needs no mapping.

export type Scope = "personal" | "global";
export type Outcome = "positive" | "negative" | "neutral";
export type Status = "active" | "superseded" | "rejected";
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
