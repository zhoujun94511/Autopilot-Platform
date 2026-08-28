/** 设计域：需求文档 / 需求 API */

import { api } from "../api";
import { downloadDesignBlob } from "./designDownload";
import { buildListQuery, type DesignListPage, type DesignListQuery } from "./designList";

export type DesignDocument = {
  id: string;
  project_id: string;
  filename: string;
  file_type: string;
  size_bytes: number;
  content_preview: string;
  created_at?: string;
};

export type Requirement = {
  id: string;
  title: string;
  req_key: string;
  priority: string;
  content?: string;
  status?: string;
  source_document_id?: string | null;
};

export {
  listRequirements,
  listRequirementsPage,
  updateRequirement,
  deleteRequirement,
  batchDeleteRequirements,
} from "./designRequirements";

export type DocumentImportResult = {
  success?: boolean;
  message?: string;
  degraded?: boolean;
  summary?: {
    total?: number;
    success_count?: number;
    failed_count?: number;
    analyzed_count?: number;
    degraded?: boolean;
  };
  results?: Array<{
    filename?: string;
    success?: boolean;
    message?: string;
    analyzed_count?: number;
    degraded?: boolean;
    mode?: string;
  }>;
};

export type RequirementImportResult = {
  success?: boolean;
  message?: string;
  summary?: {
    total?: number;
    success_count?: number;
    failed_count?: number;
    item_count?: number;
  };
  results?: Array<{
    filename?: string;
    success?: boolean;
    message?: string;
    created_count?: number;
  }>;
};

export async function listDocumentsPage(
  opts: DesignListQuery & { fileType?: string } = {},
): Promise<DesignListPage<DesignDocument>> {
  const qs = buildListQuery({
    projectId: opts.projectId,
    q: opts.q,
    fileType: opts.fileType,
    sortBy: opts.sortBy || "created_at",
    order: opts.order || "desc",
    page: opts.page ?? 1,
    pageSize: opts.pageSize ?? 20,
  });
  const out = await api<DesignListPage<DesignDocument> | DesignDocument[]>(
    `/api/v1/design/documents${qs}`,
  );
  if (Array.isArray(out)) {
    return { items: out, total: out.length, page: 1, page_size: out.length || 20 };
  }
  return (
    out || {
      items: [],
      total: 0,
      page: opts.page ?? 1,
      page_size: opts.pageSize ?? 20,
    }
  );
}

export async function listDocuments(projectId?: string): Promise<DesignDocument[]> {
  const q = projectId?.trim()
    ? `?project_id=${encodeURIComponent(projectId.trim())}`
    : "";
  return (await api<DesignDocument[]>(`/api/v1/design/documents${q}`)) || [];
}

export async function batchDeleteDocuments(itemIds: string[]): Promise<{
  success?: boolean;
  message?: string;
  deleted_count?: number;
}> {
  return await api("/api/v1/design/documents/batch-delete", {
    method: "POST",
    body: JSON.stringify({ item_ids: itemIds }),
  });
}

export async function uploadDocument(projectId: string, file: File): Promise<void> {
  const fd = new FormData();
  fd.append("file", file);
  await api(`/api/v1/design/documents?project_id=${encodeURIComponent(projectId)}`, {
    method: "POST",
    body: fd,
  });
}

/** 多文件文档导入（可选自动分析） */
export async function importDocuments(payload: {
  projectId: string;
  files: File[];
  autoAnalyze?: boolean;
  useLlm?: boolean;
  analysisType?: string;
  maxRequirements?: number;
}): Promise<DocumentImportResult> {
  const fd = new FormData();
  fd.append("project_id", payload.projectId);
  fd.append("auto_analyze", payload.autoAnalyze === false ? "false" : "true");
  fd.append("use_llm", payload.useLlm === false ? "false" : "true");
  fd.append("analysis_type", payload.analysisType || "requirements");
  fd.append("max_requirements", String(payload.maxRequirements ?? 20));
  for (const f of payload.files) {
    fd.append("files", f);
  }
  return await api<DocumentImportResult>("/api/v1/design/documents/import", {
    method: "POST",
    body: fd,
  });
}

/** 结构化需求批量导入 */
export async function importRequirementFiles(payload: {
  projectId: string;
  files: File[];
}): Promise<RequirementImportResult> {
  const fd = new FormData();
  fd.append("project_id", payload.projectId);
  for (const f of payload.files) {
    fd.append("files", f);
  }
  return await api<RequirementImportResult>("/api/v1/design/requirements/import", {
    method: "POST",
    body: fd,
  });
}

export async function analyzeDocument(
  docId: string,
  opts?: { maxRequirements?: number; useLlm?: boolean; analysisType?: string },
): Promise<DocumentAnalysisResult> {
  const q = new URLSearchParams();
  q.set("max_requirements", String(opts?.maxRequirements ?? 20));
  q.set("use_llm", opts?.useLlm === false ? "false" : "true");
  if (opts?.analysisType) q.set("analysis_type", opts.analysisType);
  return await api<DocumentAnalysisResult>(
    `/api/v1/design/documents/${docId}/analyze?${q.toString()}`,
    { method: "POST" },
  );
}

export async function deleteDocument(docId: string): Promise<void> {
  await api(`/api/v1/design/documents/${docId}`, { method: "DELETE" });
}

export type DocumentPreview = {
  id: string;
  project_id: string;
  filename: string;
  file_type: string;
  size_bytes: number;
  content: string;
  content_type?: string;
  is_truncated?: boolean;
};

export type AnalysisHistoryItem = {
  id: string;
  project_id: string;
  document_id: string;
  analysis_type: string;
  requirement_count: number;
  mode: string;
  created_by: string;
  created_at: string;
  detail?: Record<string, unknown>;
};

export type DocumentAnalysisResult = {
  success?: boolean;
  message?: string;
  analysis_type?: string;
  mode?: string;
  /** AI 不可用或回退启发式时为 true */
  degraded?: boolean;
  generator?: string;
  requirements?: Requirement[];
  test_points?: Array<Record<string, unknown>>;
  business_rules?: Array<Record<string, unknown>>;
  summary?: {
    requirements_count?: number;
    test_points_count?: number;
    business_rules_count?: number;
    total_count?: number;
  };
};

/** 文档分析结果的用户可见摘要（强制暴露 degraded） */
export function formatAnalysisNotice(out: DocumentAnalysisResult, fallback: string): string {
  const base = (out.message || fallback || "").trim();
  const degraded =
    Boolean(out.degraded) ||
    String(out.generator || "").toLowerCase().startsWith("heuristic") ||
    String(out.mode || "").includes("heuristic");
  if (!degraded) return base;
  const mode = out.mode ? ` mode=${out.mode}` : "";
  return `${base} ⚠ AI 已降级为启发式（degraded=true${mode}）——请人工重点审阅解析质量`;
}

export async function previewDocument(docId: string): Promise<DocumentPreview> {
  return await api<DocumentPreview>(`/api/v1/design/documents/${docId}/preview`);
}

export async function reanalyzeDocument(
  docId: string,
  opts?: { maxRequirements?: number; useLlm?: boolean; analysisType?: string },
): Promise<DocumentAnalysisResult> {
  const q = new URLSearchParams();
  q.set("max_requirements", String(opts?.maxRequirements ?? 20));
  q.set("use_llm", opts?.useLlm === false ? "false" : "true");
  if (opts?.analysisType) q.set("analysis_type", opts.analysisType);
  return await api<DocumentAnalysisResult>(
    `/api/v1/design/documents/${docId}/reanalyze?${q.toString()}`,
    { method: "POST" },
  );
}

export async function listAnalysisHistoryPage(opts?: {
  projectId?: string;
  documentId?: string;
  page?: number;
  pageSize?: number;
}): Promise<DesignListPage<AnalysisHistoryItem>> {
  const qs = buildListQuery({
    projectId: opts?.projectId,
    documentId: opts?.documentId,
    page: opts?.page,
    pageSize: opts?.pageSize,
  });
  return (
    (await api<DesignListPage<AnalysisHistoryItem>>(
      `/api/v1/design/documents/analysis-history${qs}`,
    )) || { items: [], total: 0, page: opts?.page ?? 1, page_size: opts?.pageSize ?? 50 }
  );
}

export async function exportRequirementsExcel(opts: {
  projectId?: string;
  sourceDocumentId?: string;
  reqIds?: string[];
  format?: "excel" | "csv";
}): Promise<void> {
  const q = new URLSearchParams();
  if (opts.projectId?.trim()) q.set("project_id", opts.projectId.trim());
  if (opts.sourceDocumentId?.trim()) {
    q.set("source_document_id", opts.sourceDocumentId.trim());
  }
  if (opts.reqIds?.length) q.set("req_ids", opts.reqIds.join(","));
  q.set("format", opts.format || "excel");
  await downloadDesignBlob(`/api/v1/design/requirements/export?${q.toString()}`);
}
