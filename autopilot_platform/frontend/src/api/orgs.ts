/** 组织 API */
import { api } from "../api";
import {
  DEFAULT_PAGE_SIZE,
  normalizePagedResult,
  type PagedResult,
} from "../utils/pagination";

export type OrganizationPolicies = {
  members_can_create_projects: boolean;
  members_can_invite: boolean;
};

export type Organization = {
  id: string;
  name: string;
  description: string;
  created_by: string;
  created_at?: string;
  my_role: string;
  policies?: OrganizationPolicies;
};

export function orgPoliciesOf(
  org?: Pick<Organization, "policies"> | null,
): OrganizationPolicies {
  return {
    members_can_create_projects: Boolean(org?.policies?.members_can_create_projects),
    members_can_invite: Boolean(org?.policies?.members_can_invite),
  };
}

export type OrganizationMember = {
  user_id: string;
  username: string;
  role: string;
  org_id: string;
};

const PAGE_SIZE = DEFAULT_PAGE_SIZE;
const MAX_PAGES = 20;

export async function listOrgsPage(
  opts?: { page?: number; pageSize?: number },
): Promise<PagedResult<Organization>> {
  const q = new URLSearchParams();
  if (opts?.page != null) q.set("page", String(opts.page));
  if (opts?.pageSize != null) q.set("page_size", String(opts.pageSize));
  const qs = q.toString() ? `?${q.toString()}` : "";
  const raw = await api<PagedResult<Organization>>(`/api/v1/orgs${qs}`);
  return normalizePagedResult(raw, opts?.page ?? 1, opts?.pageSize ?? PAGE_SIZE);
}

/** 下拉 / 顶栏组织过滤：自动翻页拉全量。 */
export async function fetchAllOrgs(): Promise<Organization[]> {
  const all: Organization[] = [];
  for (let page = 1; page <= MAX_PAGES; page += 1) {
    const res = await listOrgsPage({ page, pageSize: PAGE_SIZE });
    all.push(...res.items);
    if (res.items.length < res.page_size || all.length >= res.total) break;
  }
  return all;
}

/** @deprecated 使用 fetchAllOrgs */
export async function listOrgs(): Promise<Organization[]> {
  return fetchAllOrgs();
}

export async function createOrg(body: {
  id: string;
  name?: string;
  description?: string;
}): Promise<Organization> {
  return await api<Organization>("/api/v1/orgs", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function listOrgMembersPage(
  orgId: string,
  opts?: { page?: number; pageSize?: number },
): Promise<PagedResult<OrganizationMember>> {
  const q = new URLSearchParams();
  if (opts?.page != null) q.set("page", String(opts.page));
  if (opts?.pageSize != null) q.set("page_size", String(opts.pageSize));
  const qs = q.toString() ? `?${q.toString()}` : "";
  const raw = await api<PagedResult<OrganizationMember>>(
    `/api/v1/orgs/${encodeURIComponent(orgId)}/members${qs}`,
  );
  return normalizePagedResult(raw, opts?.page ?? 1, opts?.pageSize ?? DEFAULT_PAGE_SIZE);
}

export const ORG_MEMBER_PAGE_SIZE = DEFAULT_PAGE_SIZE;

export async function addOrgMember(
  orgId: string,
  body: { username: string; role?: string },
): Promise<OrganizationMember> {
  return await api<OrganizationMember>(
    `/api/v1/orgs/${encodeURIComponent(orgId)}/members`,
    { method: "POST", body: JSON.stringify(body) },
  );
}

export async function removeOrgMember(orgId: string, userId: string): Promise<void> {
  await api(`/api/v1/orgs/${encodeURIComponent(orgId)}/members/${encodeURIComponent(userId)}`, {
    method: "DELETE",
  });
}

export async function patchOrgPolicies(
  orgId: string,
  body: Partial<OrganizationPolicies>,
): Promise<Organization> {
  return await api<Organization>(
    `/api/v1/orgs/${encodeURIComponent(orgId)}/policies`,
    { method: "PATCH", body: JSON.stringify(body) },
  );
}
