import { api } from "../api";
import {
  DEFAULT_PAGE_SIZE,
  normalizePagedResult,
  type PagedResult,
} from "../utils/pagination";

export type ResourcePool = {
  id: string;
  org_id: string;
  name: string;
  description: string;
  is_default: boolean;
  enabled: boolean;
  runner_ids: string[];
  device_ids: string[];
  project_ids: string[];
  can_manage: boolean;
  created_at?: string | null;
  updated_at?: string | null;
};

export type ResourcePoolCandidates = {
  runners: { runner_id: string; hostname: string; online: boolean }[];
  devices: {
    id: string;
    udid: string;
    name: string;
    platform: string;
    runner_id: string;
    busy: boolean;
  }[];
  projects: { id: string; name: string }[];
};

const enc = encodeURIComponent;

export async function listResourcePoolsPage(
  orgId: string,
  projectId = "",
  opts?: { page?: number; pageSize?: number },
): Promise<PagedResult<ResourcePool>> {
  const page = opts?.page ?? 1;
  const pageSize = opts?.pageSize ?? DEFAULT_PAGE_SIZE;
  const q = new URLSearchParams();
  if (projectId.trim()) q.set("project_id", projectId.trim());
  q.set("page", String(page));
  q.set("page_size", String(pageSize));
  const qs = q.toString() ? `?${q.toString()}` : "";
  const raw = await api<PagedResult<ResourcePool>>(
    `/api/v1/orgs/${enc(orgId)}/resource-pools${qs}`,
  );
  return normalizePagedResult(raw, page, pageSize);
}

/** @deprecated 请用 listResourcePoolsPage */
export async function listResourcePools(
  orgId: string,
  projectId = "",
  opts?: { limit?: number; offset?: number },
): Promise<ResourcePool[]> {
  const pageSize = opts?.limit ?? DEFAULT_PAGE_SIZE;
  const page = opts?.offset != null ? Math.floor(opts.offset / pageSize) + 1 : 1;
  return (await listResourcePoolsPage(orgId, projectId, { page, pageSize })).items;
}

export async function listResourcePoolCandidates(
  orgId: string,
): Promise<ResourcePoolCandidates> {
  return await api<ResourcePoolCandidates>(
    `/api/v1/orgs/${enc(orgId)}/resource-pools/candidates`,
  );
}

export async function createResourcePool(
  orgId: string,
  body: {
    name: string;
    description?: string;
    is_default?: boolean;
    enabled?: boolean;
  },
): Promise<ResourcePool> {
  return await api<ResourcePool>(`/api/v1/orgs/${enc(orgId)}/resource-pools`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function updateResourcePool(
  poolId: string,
  body: Partial<
    Pick<ResourcePool, "name" | "description" | "is_default" | "enabled">
  >,
): Promise<ResourcePool> {
  return await api<ResourcePool>(`/api/v1/resource-pools/${enc(poolId)}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export async function deleteResourcePool(poolId: string): Promise<void> {
  await api(`/api/v1/resource-pools/${enc(poolId)}`, { method: "DELETE" });
}

export async function setResourcePoolMember(
  poolId: string,
  kind: "runners" | "devices",
  resourceId: string,
  selected: boolean,
): Promise<ResourcePool> {
  const base = `/api/v1/resource-pools/${enc(poolId)}/${kind}`;
  return selected
    ? await api<ResourcePool>(base, {
        method: "POST",
        body: JSON.stringify({ resource_id: resourceId }),
      })
    : await api<ResourcePool>(`${base}/${enc(resourceId)}`, { method: "DELETE" });
}

export async function setResourcePoolProject(
  poolId: string,
  projectId: string,
  selected: boolean,
): Promise<ResourcePool> {
  const base = `/api/v1/resource-pools/${enc(poolId)}/projects`;
  return selected
    ? await api<ResourcePool>(base, {
        method: "POST",
        body: JSON.stringify({ project_id: projectId }),
      })
    : await api<ResourcePool>(`${base}/${enc(projectId)}`, { method: "DELETE" });
}

