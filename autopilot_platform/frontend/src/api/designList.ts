/** 设计域分页列表通用类型 */

import {
  DEFAULT_PAGE_SIZE,
  PAGE_SIZE_OPTIONS,
  rangeLabel,
  type PagedResult,
} from "../utils/pagination";

export type DesignListPage<T> = PagedResult<T>;

export type DesignListQuery = {
  projectId?: string;
  q?: string;
  page?: number;
  pageSize?: number;
  sortBy?: string;
  order?: "asc" | "desc";
  reviewStatus?: string;
  automationStatus?: string;
};

export { PAGE_SIZE_OPTIONS, DEFAULT_PAGE_SIZE, rangeLabel };

export function buildListQuery(params: DesignListQuery & Record<string, string | number | boolean | undefined | null>): string {
  const q = new URLSearchParams();
  for (const [key, raw] of Object.entries(params)) {
    if (raw === undefined || raw === null || raw === "") continue;
    // camel → snake for known keys
    const map: Record<string, string> = {
      projectId: "project_id",
      documentId: "document_id",
      pageSize: "page_size",
      sortBy: "sort_by",
      sourceDocumentId: "source_document_id",
      fileType: "file_type",
      reviewStatus: "review_status",
      automationStatus: "automation_status",
    };
    const apiKey = map[key] || key;
    q.set(apiKey, String(raw));
  }
  const qs = q.toString();
  return qs ? `?${qs}` : "";
}