/**
 * 管理域动作：用户 CRUD / 审计 version bump。
 */
import { api, apiErrorMessage, type AuthUser } from "../api";
import { confirmDialog, notify, promptDialog, showCopyDialog } from "./useNotify";
import * as A from "./mcAdminState";

export type AdminDeps = {
  canManageUsers: { readonly value: boolean };
  currentUser: { readonly value: AuthUser | null };
};

let d: AdminDeps;

export function bindAdminDeps(deps: AdminDeps): void {
  d = deps;
}

function requireDeps(): AdminDeps {
  if (!d) throw new Error("bindAdminDeps() must be called before admin actions");
  return d;
}

export async function refreshAudits() {
  requireDeps();
  // 列表由 AuditPanel 自拉；此处 bump version 触发重载
  A.auditsListVersion.value += 1;
}

export async function refreshUsers() {
  requireDeps();
  if (!d.canManageUsers.value) return;
  A.usersListVersion.value += 1;
}

export async function onCreateUser(
  ev: Event,
  assign?: { orgId?: string; projectId?: string },
) {
  requireDeps();
  ev.preventDefault();
  A.userMsgOk.value = true;
  const username = A.userForm.username.trim();
  const duty = A.userForm.duty || "user";
  const projectId = (assign?.projectId || "").trim();
  const body: Record<string, string> = {
    username,
    password: A.userForm.password,
    duty,
  };
  if (
    projectId &&
    (duty === "project_member" || duty === "project_owner" || duty === "project_viewer")
  ) {
    body.project_id = projectId;
  }
  try {
    await api("/api/v1/auth/users", {
      method: "POST",
      body: JSON.stringify(body),
    });
    A.userMsg.value = `已创建用户 ${username}`;
    A.userForm.username = "";
    A.userForm.password = "";
    await refreshUsers();
  } catch (e) {
    A.userMsgOk.value = false;
    A.userMsg.value = apiErrorMessage(e);
  }
}

export async function onToggleUserDisabled(u: {
  id: string;
  username: string;
  disabled?: boolean;
}) {
  requireDeps();
  const next = !u.disabled;
  if (!(await confirmDialog(next ? `禁用用户 ${u.username}？` : `启用用户 ${u.username}？`))) {
    return;
  }
  try {
    await api(`/api/v1/auth/users/${encodeURIComponent(u.id)}`, {
      method: "PATCH",
      body: JSON.stringify({ disabled: next }),
    });
    notify(next ? `已禁用 ${u.username}` : `已启用 ${u.username}`, "success");
    await refreshUsers();
  } catch (e) {
    notify(apiErrorMessage(e), "error");
  }
}

export async function onResetUserPassword(u: { id: string; username: string }) {
  requireDeps();
  const pwd = await promptDialog(`为用户 ${u.username} 设置新密码（至少 4 位）`, {
    title: "重置密码",
    password: true,
  });
  if (pwd == null) return;
  if (pwd.trim().length < 4) {
    notify("密码至少 4 位", "error");
    return;
  }
  try {
    await api(`/api/v1/auth/users/${encodeURIComponent(u.id)}`, {
      method: "PATCH",
      body: JSON.stringify({ password: pwd.trim() }),
    });
    notify(`已重置 ${u.username} 的密码`, "success");
  } catch (e) {
    notify(apiErrorMessage(e), "error");
  }
}

export async function onDeleteUser(u: { id: string; username: string }) {
  requireDeps();
  if (u.id === d.currentUser.value?.id) {
    notify("不能删除当前登录账号", "error");
    return;
  }
  if (!(await confirmDialog(`彻底删除用户 ${u.username}？此操作不可恢复`))) return;
  try {
    await api(`/api/v1/auth/users/${encodeURIComponent(u.id)}`, { method: "DELETE" });
    notify(`已删除 ${u.username}`, "success");
    await refreshUsers();
  } catch (e) {
    notify(apiErrorMessage(e), "error");
  }
}

export function copyText(text: string, label = "已复制") {
  const t = (text || "").trim();
  if (!t) return;
  void navigator.clipboard.writeText(t).then(
    () => {
      notify(label, "success");
    },
    () => {
      void showCopyDialog(t, { title: "手动复制", text: `${label}失败，请手动复制：` });
    },
  );
}
