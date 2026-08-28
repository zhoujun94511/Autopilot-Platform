/** 设计域仪表盘统计 */
import { api } from "../api";
import { downloadDesignBlob } from "./designDownload";

export type DesignDomainStats = {
  project_id: string;
  requirements: number;
  documents: number;
  knowledge: number;
  logical_cases: number;
  by_automation_status: Record<string, number>;
  by_review_status: Record<string, number>;
  ai_degraded?: {
    degraded_cases?: number;
    scanned?: number;
    logical_cases?: number;
    ratio?: number;
    note?: string;
  };
  usage?: {
    action_counts?: Record<string, number>;
    period_note?: string;
  };
  tokens?: {
    day?: string;
    prompt_tokens?: number | null;
    completion_tokens?: number | null;
    total_tokens?: number | null;
    cached_tokens?: number | null;
    cache_miss_tokens?: number | null;
    cache_write_tokens?: number | null;
    cache_hit_rate?: number | null;
    calls?: number | null;
    daily_budget?: number | null;
    budget_remaining?: number | null;
    project_daily_budget?: number | null;
    project_total_tokens?: number | null;
    project_budget_remaining?: number | null;
    top_projects?: Array<{ project_id: string; total_tokens: number; calls: number }>;
    enforce?: boolean;
    note?: string;
    design_audit_events?: number;
    top_actions?: Array<[string, number]>;
    jsonl?: string;
  };
};

export async function fetchDesignStats(projectId?: string): Promise<DesignDomainStats> {
  const q = projectId ? `?project_id=${encodeURIComponent(projectId)}` : "";
  return await api<DesignDomainStats>(`/api/v1/design/stats${q}`);
}

export async function exportDesignStatsCsv(projectId?: string): Promise<void> {
  const q = projectId ? `?project_id=${encodeURIComponent(projectId)}` : "";
  await downloadDesignBlob(`/api/v1/design/stats/export${q}`);
}

export async function exportDesignBatchZip(opts: {
  projectId?: string;
  exportCases?: boolean;
  exportRequirements?: boolean;
  exportKnowledge?: boolean;
  exportDocuments?: boolean;
}): Promise<void> {
  await downloadDesignBlob("/api/v1/design/export/batch", {
    method: "POST",
    body: {
      project_id: opts.projectId || "",
      config: {
        export_cases: opts.exportCases !== false,
        export_requirements: opts.exportRequirements !== false,
        export_knowledge: opts.exportKnowledge !== false,
        export_documents: Boolean(opts.exportDocuments),
      },
    },
  });
}
