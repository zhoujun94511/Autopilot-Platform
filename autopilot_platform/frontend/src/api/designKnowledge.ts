/** 设计域：知识库 API */

import { api } from "../api";
import { buildListQuery, type DesignListPage, type DesignListQuery } from "./designList";

export type KnowledgeItem = {
  id: string;
  project_id: string;
  title: string;
  content: string;
  category: string;
  source: string;
  confirmed: boolean;
  created_by: string;
  created_at?: string;
};

export type KnowledgeUpdate = {
  title?: string;
  content?: string;
  category?: string;
  source?: string;
  confirmed?: boolean;
};

export type KnowledgeListQuery = DesignListQuery & {
  category?: string;
  confirmed?: boolean | "";
};

export async function listKnowledgePage(
  opts: KnowledgeListQuery = {},
): Promise<DesignListPage<KnowledgeItem>> {
  const qs = buildListQuery({
    projectId: opts.projectId,
    q: opts.q,
    category: opts.category,
    confirmed: opts.confirmed === "" || opts.confirmed === undefined ? undefined : opts.confirmed,
    sortBy: opts.sortBy || "created_at",
    order: opts.order || "desc",
    page: opts.page ?? 1,
    pageSize: opts.pageSize ?? 20,
  });
  const out = await api<DesignListPage<KnowledgeItem> | KnowledgeItem[]>(
    `/api/v1/design/knowledge${qs}`,
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

export async function listKnowledge(projectId?: string): Promise<KnowledgeItem[]> {
  const q = projectId?.trim()
    ? `?project_id=${encodeURIComponent(projectId.trim())}`
    : "";
  return (await api<KnowledgeItem[]>(`/api/v1/design/knowledge${q}`)) || [];
}

export async function createKnowledge(body: {
  project_id: string;
  title: string;
  content: string;
  category?: string;
  confirmed?: boolean;
  source?: string;
}): Promise<KnowledgeItem> {
  return await api<KnowledgeItem>("/api/v1/design/knowledge", {
    method: "POST",
    body: JSON.stringify({
      category: "best_practices",
      confirmed: true,
      source: "manual",
      ...body,
    }),
  });
}

export async function updateKnowledge(
  itemId: string,
  body: KnowledgeUpdate,
): Promise<KnowledgeItem> {
  return await api<KnowledgeItem>(`/api/v1/design/knowledge/${itemId}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export async function deleteKnowledge(itemId: string): Promise<void> {
  await api(`/api/v1/design/knowledge/${itemId}`, { method: "DELETE" });
}

export type KnowledgeSearchHit = {
  id: string;
  title: string;
  content: string;
  score: number;
  category?: string;
  source?: string;
  confirmed?: boolean;
};

export type KnowledgeSearchResult = {
  query: string;
  engine?: string;
  total?: number;
  documents: KnowledgeSearchHit[];
};

export async function searchKnowledge(body: {
  project_id: string;
  query: string;
  top_k?: number;
  score_threshold?: number;
  confirmed_only?: boolean;
}): Promise<KnowledgeSearchResult> {
  return (
    (await api<KnowledgeSearchResult>("/api/v1/design/knowledge/search", {
      method: "POST",
      body: JSON.stringify({
        top_k: 10,
        score_threshold: 0.3,
        confirmed_only: false,
        ...body,
      }),
    })) || { query: body.query, documents: [] }
  );
}

export async function rebuildKnowledgeIndex(body: {
  project_id: string;
  clear_all?: boolean;
}): Promise<{ success?: boolean; message?: string; indexed_count?: number }> {
  return await api("/api/v1/design/knowledge/rebuild", {
    method: "POST",
    body: JSON.stringify({ clear_all: true, ...body }),
  });
}

export async function batchDeleteKnowledge(itemIds: string[]): Promise<{
  success?: boolean;
  message?: string;
  deleted_count?: number;
}> {
  return await api("/api/v1/design/knowledge/batch-delete", {
    method: "POST",
    body: JSON.stringify({ item_ids: itemIds }),
  });
}

export type KnowledgeImportResult = {
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
  items?: KnowledgeItem[];
};

/** 批量导入知识文件（多选；对齐 TestPilot 上传） */
export async function importKnowledgeFiles(payload: {
  projectId: string;
  files: File[];
  category?: string;
  confirmed?: boolean;
  description?: string;
}): Promise<KnowledgeImportResult> {
  const fd = new FormData();
  fd.append("project_id", payload.projectId);
  fd.append("category", payload.category || "other");
  fd.append("confirmed", payload.confirmed === false ? "false" : "true");
  if (payload.description?.trim()) {
    fd.append("description", payload.description.trim());
  }
  for (const f of payload.files) {
    fd.append("files", f);
  }
  return await api<KnowledgeImportResult>("/api/v1/design/knowledge/import", {
    method: "POST",
    body: fd,
  });
}
