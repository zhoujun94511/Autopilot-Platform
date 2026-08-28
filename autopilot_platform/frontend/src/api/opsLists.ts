/** 运维域列表 API（面板分页 vs 下拉全量）。 */

import {
  api,
  type AppBuild,
  type Artifact,
  type AuditLog,
  type Job,
  type Report,
  type Runner,
} from "../api";
import {
  DEFAULT_PAGE_SIZE,
  normalizePagedResult,
  type PagedResult,
} from "../utils/pagination";

export type Schedule = {
  id: string;
  name: string;
  enabled: boolean;
  runs_done: number;
  next_run_at?: string | null;
  last_job_id?: string | null;
  interval_sec: number;
  repeat: number;
  delay_sec?: number;
  stop_on_fail?: boolean;
  artifact_id?: string | null;
  app_build_id?: string | null;
  app_build_name?: string;
  app_version_name?: string;
  app_version_code?: number;
  app_package_id?: string;
  project_dir?: string;
  project_id?: string;
  platform?: string;
  backend_mode?: string;
  web_engine?: string;
  wda_bundle?: string;
  device_udids?: string[];
  preferred_runner_id?: string | null;
  webhook_url?: string;
  parallel?: boolean;
  parallel_workers?: number;
  entry_paths?: string[];
};

export type PlatformUser = {
  id: string;
  username: string;
  role: string;
  disabled?: boolean;
};

const PAGE_SIZE = DEFAULT_PAGE_SIZE;
const MAX_PAGES = 20;

function qs(params: Record<string, string | number | undefined | null | false>): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === false || v === "") continue;
    q.set(k, String(v));
  }
  const s = q.toString();
  return s ? `?${s}` : "";
}

async function fetchPage<T>(
  path: string,
  page: number,
  pageSize: number,
): Promise<PagedResult<T>> {
  const raw = await api<PagedResult<T>>(`${path}${qs({ page, page_size: pageSize })}`);
  return normalizePagedResult(raw, page, pageSize);
}

async function fetchAllPages<T>(
  path: string,
  extra?: Record<string, string | number | undefined>,
): Promise<T[]> {
  const all: T[] = [];
  for (let page = 1; page <= MAX_PAGES; page += 1) {
    const raw = await api<PagedResult<T>>(
      `${path}${qs({ ...extra, page, page_size: PAGE_SIZE })}`,
    );
    const res = normalizePagedResult(raw, page, PAGE_SIZE);
    all.push(...res.items);
    if (res.items.length < res.page_size || all.length >= res.total) break;
  }
  return all;
}

export type JobsListFilters = {
  page?: number;
  pageSize?: number;
  projectId?: string;
  q?: string;
  status?: string;
};

export async function listJobsPage(opts?: JobsListFilters): Promise<PagedResult<Job>> {
  const page = opts?.page ?? 1;
  const pageSize = opts?.pageSize ?? PAGE_SIZE;
  const raw = await api<PagedResult<Job>>(
    `/api/v1/jobs${qs({
      page,
      page_size: pageSize,
      project_id: opts?.projectId?.trim(),
      q: opts?.q?.trim(),
      status: opts?.status?.trim(),
    })}`,
  );
  return normalizePagedResult(raw, page, pageSize);
}

export async function fetchAllJobs(projectId?: string): Promise<Job[]> {
  return fetchAllPages<Job>("/api/v1/jobs", { project_id: projectId?.trim() });
}

export type ReportsListFilters = {
  page?: number;
  pageSize?: number;
  projectId?: string;
  artifactId?: string;
  appBuildId?: string;
  platform?: string;
};

export async function listReportsPage(opts?: ReportsListFilters): Promise<PagedResult<Report>> {
  const page = opts?.page ?? 1;
  const pageSize = opts?.pageSize ?? PAGE_SIZE;
  const raw = await api<PagedResult<Report>>(
    `/api/v1/reports${qs({
      page,
      page_size: pageSize,
      project_id: opts?.projectId?.trim(),
      artifact_id: opts?.artifactId?.trim(),
      app_build_id: opts?.appBuildId?.trim(),
      platform: opts?.platform?.trim(),
    })}`,
  );
  return normalizePagedResult(raw, page, pageSize);
}

export async function listSchedulesPage(opts?: {
  page?: number;
  pageSize?: number;
  projectId?: string;
}): Promise<PagedResult<Schedule>> {
  const page = opts?.page ?? 1;
  const pageSize = opts?.pageSize ?? PAGE_SIZE;
  const raw = await api<PagedResult<Schedule>>(
    `/api/v1/schedules${qs({
      page,
      page_size: pageSize,
      project_id: opts?.projectId?.trim(),
    })}`,
  );
  return normalizePagedResult(raw, page, pageSize);
}

export async function listRunnersPage(opts?: {
  page?: number;
  pageSize?: number;
  projectId?: string;
}): Promise<PagedResult<Runner>> {
  const page = opts?.page ?? 1;
  const pageSize = opts?.pageSize ?? PAGE_SIZE;
  const raw = await api<PagedResult<Runner>>(
    `/api/v1/runners${qs({
      page,
      page_size: pageSize,
      project_id: opts?.projectId?.trim(),
    })}`,
  );
  return normalizePagedResult(raw, page, pageSize);
}

export async function fetchAllRunners(projectId?: string): Promise<Runner[]> {
  return fetchAllPages<Runner>("/api/v1/runners", { project_id: projectId?.trim() });
}

export async function listUsersPage(opts?: {
  page?: number;
  pageSize?: number;
}): Promise<PagedResult<PlatformUser>> {
  const page = opts?.page ?? 1;
  const pageSize = opts?.pageSize ?? PAGE_SIZE;
  return fetchPage<PlatformUser>("/api/v1/auth/users", page, pageSize);
}

export async function listArtifactsPage(opts?: {
  page?: number;
  pageSize?: number;
  projectId?: string;
}): Promise<PagedResult<Artifact>> {
  const page = opts?.page ?? 1;
  const pageSize = opts?.pageSize ?? PAGE_SIZE;
  const raw = await api<PagedResult<Artifact>>(
    `/api/v1/artifacts${qs({
      page,
      page_size: pageSize,
      project_id: opts?.projectId?.trim(),
    })}`,
  );
  return normalizePagedResult(raw, page, pageSize);
}

export async function fetchAllArtifacts(projectId?: string): Promise<Artifact[]> {
  return fetchAllPages<Artifact>("/api/v1/artifacts", { project_id: projectId?.trim() });
}

export async function listAppBuildsPage(opts?: {
  page?: number;
  pageSize?: number;
  projectId?: string;
  platform?: string;
}): Promise<PagedResult<AppBuild>> {
  const page = opts?.page ?? 1;
  const pageSize = opts?.pageSize ?? PAGE_SIZE;
  const raw = await api<PagedResult<AppBuild>>(
    `/api/v1/app-builds${qs({
      page,
      page_size: pageSize,
      project_id: opts?.projectId?.trim(),
      platform: opts?.platform?.trim(),
    })}`,
  );
  return normalizePagedResult(raw, page, pageSize);
}

export async function fetchAllAppBuilds(projectId?: string): Promise<AppBuild[]> {
  return fetchAllPages<AppBuild>("/api/v1/app-builds", { project_id: projectId?.trim() });
}

export async function listAuditsPage(opts?: {
  page?: number;
  pageSize?: number;
  action?: string;
  actor?: string;
  offset?: number;
  limit?: number;
}): Promise<PagedResult<AuditLog>> {
  const page = opts?.page ?? 1;
  const pageSize = opts?.pageSize ?? PAGE_SIZE;
  const raw = await api<PagedResult<AuditLog>>(
    `/api/v1/audit${qs({
      page,
      page_size: pageSize,
      limit: opts?.limit,
      offset: opts?.offset,
      action: opts?.action?.trim(),
      actor: opts?.actor?.trim(),
    })}`,
  );
  return normalizePagedResult(raw, page, pageSize);
}

export type AclGrant = {
  id: string;
  resource_type: string;
  resource_id: string;
  username: string;
  permission: string;
};

/** 分享面板展示单个资源的全部授权，按页拉全量。 */
export async function fetchAllAclGrants(
  resourceType: string,
  resourceId: string,
): Promise<AclGrant[]> {
  return fetchAllPages<AclGrant>("/api/v1/acl", {
    resource_type: resourceType.trim(),
    resource_id: resourceId.trim(),
  });
}

export const OPS_LIST_PAGE_SIZE = PAGE_SIZE;
