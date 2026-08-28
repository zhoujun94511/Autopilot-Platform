/** 项目邀请 API */
import { api } from "../api";
import {
  DEFAULT_PAGE_SIZE,
  normalizePagedResult,
  type PagedResult,
} from "../utils/pagination";

export type ProjectInvite = {
  id: string;
  project_id: string;
  token: string;
  role: string;
  label: string;
  created_by: string;
  created_at?: string;
  expires_at?: string | null;
  max_uses: number;
  use_count: number;
  revoked: boolean;
  invite_path: string;
};

export type ProjectInvitePreview = {
  token: string;
  project_id: string;
  project_name: string;
  role: string;
  label: string;
  expires_at?: string | null;
  valid: boolean;
  detail: string;
};

export type InviteRegisterResult = {
  access_token: string;
  refresh_token?: string;
  expires_in?: number;
  user: { id: string; username: string; role: string };
};

export async function createProjectInvite(
  projectId: string,
  body: {
    role?: string;
    label?: string;
    expires_hours?: number;
    max_uses?: number;
  },
): Promise<ProjectInvite> {
  return await api<ProjectInvite>(
    `/api/v1/projects/${encodeURIComponent(projectId)}/invites`,
    { method: "POST", body: JSON.stringify(body) },
  );
}

export async function listProjectInvitesPage(
  projectId: string,
  opts?: { page?: number; pageSize?: number },
): Promise<PagedResult<ProjectInvite>> {
  const q = new URLSearchParams();
  if (opts?.page != null) q.set("page", String(opts.page));
  if (opts?.pageSize != null) q.set("page_size", String(opts.pageSize));
  const qs = q.toString() ? `?${q.toString()}` : "";
  const raw = await api<PagedResult<ProjectInvite>>(
    `/api/v1/projects/${encodeURIComponent(projectId)}/invites${qs}`,
  );
  return normalizePagedResult(raw, opts?.page ?? 1, opts?.pageSize ?? DEFAULT_PAGE_SIZE);
}

export const PROJECT_INVITE_PAGE_SIZE = DEFAULT_PAGE_SIZE;

export async function revokeProjectInvite(projectId: string, inviteId: string): Promise<void> {
  await api(`/api/v1/projects/${encodeURIComponent(projectId)}/invites/${encodeURIComponent(inviteId)}`, {
    method: "DELETE",
  });
}

export async function previewInvite(token: string): Promise<ProjectInvitePreview> {
  return await api<ProjectInvitePreview>(`/api/v1/invites/${encodeURIComponent(token)}`, {
    bearer: "",
    token: "",
  });
}

export async function acceptInvite(token: string): Promise<{
  user_id: string;
  username: string;
  role: string;
  project_id: string;
}> {
  return await api(`/api/v1/invites/${encodeURIComponent(token)}/accept`, {
    method: "POST",
  });
}

export async function registerViaInvite(
  token: string,
  username: string,
  password: string,
): Promise<InviteRegisterResult> {
  return await api<InviteRegisterResult>(`/api/v1/invites/${encodeURIComponent(token)}/register`, {
    method: "POST",
    bearer: "",
    token: "",
    body: JSON.stringify({ username, password }),
  });
}
