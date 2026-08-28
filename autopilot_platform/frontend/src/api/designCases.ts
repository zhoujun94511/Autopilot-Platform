/** 设计域逻辑用例 API / 类型（独立于巨型 api.ts）。 */

import { api } from "../api";
import { buildListQuery, DEFAULT_PAGE_SIZE, type DesignListPage } from "./designList";
import { downloadDesignBlob } from "./designDownload";

export type AutomationStatus =
  | "LOGICAL_ONLY"
  | "INTENT_READY"
  | "PENDING_VERIFY"
  | "BINDING_PARTIAL"
  | "DRAFT_AUTOMATION"
  | "MAPPING_REQUIRED"
  | "DEBUGGING"
  | "EXECUTABLE"
  | "PUBLISHED"
  | "DEPRECATED";

export const AUTOMATION_STATUS_OPTIONS: { value: AutomationStatus; label: string }[] = [
  { value: "LOGICAL_ONLY", label: "仅逻辑" },
  { value: "INTENT_READY", label: "意图可跑" },
  { value: "PENDING_VERIFY", label: "待首跑验证" },
  { value: "BINDING_PARTIAL", label: "部分绑定" },
  { value: "DRAFT_AUTOMATION", label: "自动化草稿" },
  { value: "MAPPING_REQUIRED", label: "待映射(遗留)" },
  { value: "DEBUGGING", label: "调试中/失败待审" },
  { value: "EXECUTABLE", label: "可执行" },
  { value: "PUBLISHED", label: "已发布" },
  { value: "DEPRECATED", label: "已废弃" },
];

export const REVIEW_STATUS_OPTIONS = [
  { value: "", label: "全部评审状态" },
  { value: "AI_DRAFT", label: "待审草稿" },
  { value: "HUMAN_REVIEWED", label: "已人工审" },
  { value: "APPROVED", label: "已通过" },
  { value: "REJECTED", label: "已驳回" },
];

export type IntentStep = {
  id: string;
  action: string;
  target?: string;
  value?: string;
  platform_hint?: string;
  text: string;
};

export type LogicalCase = {
  schema_version?: string;
  logical_case_id: string;
  case_key: string;
  project_id: string;
  title: string;
  review_status: string;
  automatability: string;
  automation_status: AutomationStatus | string;
  priority: string;
  logical_steps: string[];
  intent_steps?: IntentStep[];
  expected_results: string[];
  generation_metadata?: {
    generator?: string;
    degraded?: boolean;
    quality?: { risk?: string; score?: number; issues?: string[] };
    rag?: { hit_count?: number; engine?: string };
    use_rag?: boolean;
  };
};

export async function listLogicalCases(
  projectId?: string,
  reviewStatus?: string,
): Promise<LogicalCase[]> {
  const q = new URLSearchParams();
  if (projectId?.trim()) q.set("project_id", projectId.trim());
  if (reviewStatus?.trim()) q.set("review_status", reviewStatus.trim());
  const qs = q.toString() ? `?${q.toString()}` : "";
  return (await api<LogicalCase[]>(`/api/v1/design/logical-cases${qs}`)) || [];
}

export type LogicalCaseListQuery = {
  projectId?: string;
  reviewStatus?: string;
  automationStatus?: string;
  q?: string;
  page?: number;
  pageSize?: number;
  sortBy?: string;
  order?: "asc" | "desc";
};

export async function queryLogicalCasesPage(
  params: LogicalCaseListQuery,
): Promise<DesignListPage<LogicalCase>> {
  const qs = buildListQuery({
    projectId: params.projectId,
    reviewStatus: params.reviewStatus,
    automationStatus: params.automationStatus,
    q: params.q,
    page: params.page ?? 1,
    pageSize: params.pageSize ?? DEFAULT_PAGE_SIZE,
    sortBy: params.sortBy ?? "updated_at",
    order: params.order ?? "desc",
  });
  return await api<DesignListPage<LogicalCase>>(`/api/v1/design/logical-cases${qs}`);
}

export async function generateLogicalCases(body: {
  project_id: string;
  requirement_text: string;
  requirement_ids?: string[];
  max_cases?: number;
  module?: string;
  use_rag?: boolean;
  auto_approve?: boolean;
  auto_approve_min_quality?: number;
}): Promise<LogicalCase[]> {
  return (
    (await api<LogicalCase[]>("/api/v1/design/logical-cases/generate", {
      method: "POST",
      body: JSON.stringify({
        max_cases: 5,
        module: "",
        use_rag: true,
        auto_approve: false,
        ...body,
      }),
    })) || []
  );
}

export async function batchGenerateLogicalCases(body: {
  project_id: string;
  requirements: string[];
  case_count_per_req?: number;
  process_mode?: "sequential" | "parallel";
  use_rag?: boolean;
  module?: string;
  auto_approve?: boolean;
  auto_approve_min_quality?: number;
}): Promise<{
  success?: boolean;
  total_cases?: number;
  message?: string;
  degraded?: boolean;
  generator?: string;
  results?: unknown[];
  summary?: {
    process_mode?: string;
    executed_mode?: string;
    max_workers?: number;
    parallel_enabled?: boolean;
    note?: string;
  };
}> {
  return await api("/api/v1/design/logical-cases/batch-generate", {
    method: "POST",
    body: JSON.stringify({
      case_count_per_req: 3,
      process_mode: "sequential",
      use_rag: true,
      auto_approve: false,
      ...body,
    }),
  });
}

export async function patchLogicalCase(
  caseId: string,
  body: {
    title?: string;
    priority?: string;
    review_status?: string;
    automation_status?: AutomationStatus | string;
    intent_steps?: IntentStep[];
    logical_steps?: string[];
  },
): Promise<LogicalCase> {
  return await api<LogicalCase>(`/api/v1/design/logical-cases/${caseId}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export async function deleteLogicalCase(caseId: string): Promise<void> {
  await api(`/api/v1/design/logical-cases/${caseId}`, { method: "DELETE" });
}

export async function batchDeleteLogicalCases(caseIds: string[]): Promise<{
  success?: boolean;
  deleted_count?: number;
  failed_count?: number;
}> {
  return await api("/api/v1/design/logical-cases/batch-delete", {
    method: "POST",
    body: JSON.stringify({ case_ids: caseIds }),
  });
}

export async function regenerateLogicalCase(
  caseId: string,
  opts?: { max_cases?: number; use_rag?: boolean },
): Promise<LogicalCase[]> {
  return (
    (await api<LogicalCase[]>(`/api/v1/design/logical-cases/${caseId}/regenerate`, {
      method: "POST",
      body: JSON.stringify(opts || {}),
    })) || []
  );
}

export async function exportLogicalCasesFile(opts: {
  projectId?: string;
  reviewStatus?: string;
  format?: "excel" | "csv" | "json";
  caseIds?: string[];
}): Promise<void> {
  await downloadDesignBlob("/api/v1/design/logical-cases/export", {
    method: "POST",
    body: {
      project_id: opts.projectId || "",
      review_status: opts.reviewStatus || "",
      format: opts.format || "excel",
      case_ids: opts.caseIds || [],
    },
  });
}

export async function downloadCasesTemplate(format: "excel" | "csv" = "excel"): Promise<void> {
  await downloadDesignBlob(`/api/v1/design/logical-cases/template?format=${format}`);
}

export async function downloadApprovedBundle(projectId: string): Promise<void> {
  await downloadDesignBlob(
    `/api/v1/design/projects/${encodeURIComponent(projectId)}/logical-cases/export`,
    { filename: `approved_cases_${projectId}.json` },
  );
}

export type EnqueueApprovedJobBody = {
  project_id: string;
  artifact_id: string;
  logical_case_ids?: string[];
  name?: string;
  app_build_id?: string;
  platform?: string;
  web_engine?: string;
  device_udids?: string[];
  preferred_runner_id?: string | null;
  webhook_url?: string;
  backend_mode?: string;
  wda_bundle?: string;
  parallel?: boolean;
  parallel_workers?: number;
};

export type EnqueueApprovedJobOut = {
  id: string;
  name?: string;
  status?: string;
  warnings?: string[];
  [key: string]: unknown;
};

/** APPROVED 逻辑用例 → 批跑 Job；响应可能含 Binding 软警告。 */
export async function enqueueApprovedJob(
  body: EnqueueApprovedJobBody,
): Promise<EnqueueApprovedJobOut> {
  return await api<EnqueueApprovedJobOut>("/api/v1/design/logical-cases/enqueue-job", {
    method: "POST",
    body: JSON.stringify(body),
  });
}
