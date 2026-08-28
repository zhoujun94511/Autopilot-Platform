import { api } from "../api";

export type AgentOpsTrace = {
  reports_scanned: number;
  intent_steps: number;
  binding_hit: Record<string, number>;
  cache_hit_rate: number;
  heal_rate: number;
  vision_rate: number;
  heal_count: number;
  vision_steps: number;
  vision_tokens_sum: number;
  avg_latency_ms: number;
  fail_reason: Record<string, number>;
  resolve_strategy: Record<string, number>;
  verification_status: Record<string, number>;
  evidence_steps: number;
  note?: string;
};

export type AgentOpsSnapshot = {
  project_id?: string | null;
  trace: AgentOpsTrace;
  tokens: Record<string, unknown>;
};

export function fetchAgentOps(projectId?: string, limit = 80): Promise<AgentOpsSnapshot> {
  const q = new URLSearchParams();
  if (projectId?.trim()) q.set("project_id", projectId.trim());
  q.set("limit", String(limit));
  const suffix = q.toString() ? `?${q}` : "";
  return api<AgentOpsSnapshot>(`/api/v1/ops/agentops${suffix}`);
}
