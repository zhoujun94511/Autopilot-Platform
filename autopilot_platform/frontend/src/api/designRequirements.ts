/** 设计域：需求条目 API */

import { api } from "../api";
import { buildListQuery, type DesignListPage, type DesignListQuery } from "./designList";

export type Requirement = {
  id: string;
  project_id?: string;
  title: string;
  content?: string;
  req_key: string;
  req_type?: string;
  priority: string;
  status?: string;
  source_document_id?: string | null;
};

export type RequirementUpdate = {
  title?: string;
  content?: string;
  req_key?: string;
  req_type?: string;
  priority?: string;
  status?: string;
};

export type RequirementListQuery = DesignListQuery & {
  sourceDocumentId?: string;
  priority?: string;
};

/** 带 page 时返回分页；不带 page 时返回数组（兼容）。 */
export async function listRequirementsPage(
  opts: RequirementListQuery = {},
): Promise<DesignListPage<Requirement>> {
  const qs = buildListQuery({
    projectId: opts.projectId,
    sourceDocumentId: opts.sourceDocumentId,
    q: opts.q,
    priority: opts.priority,
    sortBy: opts.sortBy || "created_at",
    order: opts.order || "desc",
    page: opts.page ?? 1,
    pageSize: opts.pageSize ?? 20,
  });
  const out = await api<DesignListPage<Requirement> | Requirement[]>(
    `/api/v1/design/requirements${qs}`,
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

export async function listRequirements(
  projectId?: string,
  sourceDocumentId?: string,
): Promise<Requirement[]> {
  const q = new URLSearchParams();
  if (projectId?.trim()) q.set("project_id", projectId.trim());
  if (sourceDocumentId?.trim()) q.set("source_document_id", sourceDocumentId.trim());
  const qs = q.toString() ? `?${q.toString()}` : "";
  return (await api<Requirement[]>(`/api/v1/design/requirements${qs}`)) || [];
}

export async function updateRequirement(
  reqId: string,
  body: RequirementUpdate,
): Promise<Requirement> {
  return await api<Requirement>(`/api/v1/design/requirements/${reqId}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export async function deleteRequirement(reqId: string): Promise<void> {
  await api(`/api/v1/design/requirements/${reqId}`, { method: "DELETE" });
}

export async function batchDeleteRequirements(itemIds: string[]): Promise<{
  success?: boolean;
  message?: string;
  deleted_count?: number;
}> {
  return await api("/api/v1/design/requirements/batch-delete", {
    method: "POST",
    body: JSON.stringify({ item_ids: itemIds }),
  });
}
