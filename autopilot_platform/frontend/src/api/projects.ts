/** 项目列表 API（下拉选项 vs 面板分页共用）。 */

import { api } from "../api";
import {
  DEFAULT_PAGE_SIZE,
  normalizePagedResult,
  type PagedResult,
} from "../utils/pagination";

export type Project = {
  id: string;
  name: string;
  description?: string;
  org_id?: string;
  my_role?: string;
  created_at?: string | null;
};

const PAGE_SIZE = DEFAULT_PAGE_SIZE;
const MAX_PAGES = 20;

export async function listProjectsPage(
  orgId?: string,
  opts?: { page?: number; pageSize?: number; q?: string },
): Promise<PagedResult<Project>> {
  const q = new URLSearchParams();
  if (orgId?.trim()) q.set("org_id", orgId.trim());
  if (opts?.page != null) q.set("page", String(opts.page));
  if (opts?.pageSize != null) q.set("page_size", String(opts.pageSize));
  if (opts?.q?.trim()) q.set("q", opts.q.trim());
  const qs = q.toString() ? `?${q.toString()}` : "";
  const raw = await api<PagedResult<Project>>(`/api/v1/projects${qs}`);
  return normalizePagedResult(raw, opts?.page ?? 1, opts?.pageSize ?? PAGE_SIZE);
}

/** 下拉 / 全局过滤器：自动翻页拉全量（上限 MAX_PAGES 页）。 */
export async function fetchAllProjects(orgId?: string): Promise<Project[]> {
  const all: Project[] = [];
  for (let page = 1; page <= MAX_PAGES; page += 1) {
    const res = await listProjectsPage(orgId, { page, pageSize: PAGE_SIZE });
    all.push(...res.items);
    if (res.items.length < res.page_size || all.length >= res.total) break;
  }
  return all;
}

export const PROJECT_LIST_PAGE_SIZE = PAGE_SIZE;

export type ProjectMember = {
  user_id: string;
  username: string;
  role: string;
  project_id: string;
};

export async function listProjectMembersPage(
  projectId: string,
  opts?: { page?: number; pageSize?: number },
): Promise<PagedResult<ProjectMember>> {
  const q = new URLSearchParams();
  if (opts?.page != null) q.set("page", String(opts.page));
  if (opts?.pageSize != null) q.set("page_size", String(opts.pageSize));
  const qs = q.toString() ? `?${q.toString()}` : "";
  const raw = await api<PagedResult<ProjectMember>>(
    `/api/v1/projects/${encodeURIComponent(projectId)}/members${qs}`,
  );
  return normalizePagedResult(raw, opts?.page ?? 1, opts?.pageSize ?? PAGE_SIZE);
}

export const PROJECT_MEMBER_PAGE_SIZE = PAGE_SIZE;

export async function addProjectMember(
  projectId: string,
  body: { username: string; role?: string },
): Promise<ProjectMember> {
  return await api<ProjectMember>(
    `/api/v1/projects/${encodeURIComponent(projectId)}/members`,
    { method: "POST", body: JSON.stringify(body) },
  );
}
