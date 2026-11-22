/**
 * 组织 / 项目动作。
 */
import { api, apiErrorMessage, saveOrgId, type AuthUser } from "../api";
import { fetchAllOrgs } from "../api/orgs";
import { fetchAllProjects } from "../api/projects";
import { confirmDialog, notify } from "./useNotify";
import * as P from "./mcProjectsState";
import { form as jobForm, scheduleForm } from "./mcExecState";
import { watch, type Ref } from "vue";

export type ProjectsDeps = {
  user: Ref<AuthUser | null>;
  activeTab: Ref<string>;
  refreshForTab: (tab?: string) => Promise<void>;
};

let d: ProjectsDeps;
let orgRequestId = 0;
let projectRequestId = 0;

export function bindProjectsDeps(deps: ProjectsDeps): void {
  d = deps;
}

function requireDeps(): ProjectsDeps {
  if (!d) throw new Error("bindProjectsDeps() must be called before project actions");
  return d;
}

export async function refreshOrgs() {
  const deps = requireDeps();
  const userId = deps.user.value?.id;
  const requestId = ++orgRequestId;
  try {
    const orgs = await fetchAllOrgs();
    if (requestId !== orgRequestId || userId !== deps.user.value?.id) return;
    P.orgs.value = orgs;
  } catch {
    return;
  }
  const oid = P.filterOrgId.value.trim();
  if (!oid) return;
  if (requireDeps().user.value?.role === "admin") return;
  if (!P.orgs.value.some((o) => o.id === oid)) {
    clearProjectSelection();
    P.projects.value = [];
    P.filterOrgId.value = "";
    saveOrgId("");
    void refreshProjects();
  }
}

export async function refreshProjects(): Promise<{ clearedProject: boolean }> {
  const deps = requireDeps();
  const oid = P.filterOrgId.value.trim();
  const userId = deps.user.value?.id;
  const requestId = ++projectRequestId;
  try {
    const projects = await fetchAllProjects(oid || undefined);
    if (requestId !== projectRequestId || oid !== P.filterOrgId.value.trim() ||
        userId !== deps.user.value?.id) return { clearedProject: false };
    P.projects.value = projects;
  } catch {
    return { clearedProject: false };
  }
  const pid = P.filterProjectId.value.trim();
  if (!pid) return { clearedProject: false };
  const hit = P.projects.value.find((p) => p.id === pid);
  const poid = hit?.org_id?.trim();
  // 不在可见列表，或与当前组织不一致 → 清空（防串租户）
  const invalid =
    !hit || (Boolean(oid) && Boolean(poid) && poid !== oid);
  if (!invalid) return { clearedProject: false };
  clearProjectSelection();
  return { clearedProject: true };
}

function clearProjectSelection() {
  const pid = P.filterProjectId.value.trim();
  P.filterProjectId.value = "";
  P.persistProjectId("");
  if (P.memberForm.project_id === pid) P.memberForm.project_id = "";
  if (jobForm.project_id === pid) jobForm.project_id = "";
  if (scheduleForm.project_id === pid) scheduleForm.project_id = "";
}

export function selectOrg(id: string) {
  const deps = requireDeps();
  const oid = (id || "").trim();
  const prev = P.filterOrgId.value.trim();
  if (oid === prev) {
    void refreshProjects();
    void deps.refreshForTab(deps.activeTab.value);
    return;
  }
  if (oid) {
    const pid = P.filterProjectId.value.trim();
    const project = P.projects.value.find((row) => row.id === pid);
    if (pid && project?.org_id?.trim() !== oid) {
      clearProjectSelection();
      notify("已切换组织，已清空原项目选择。", "warn");
    }
    P.projects.value = P.projects.value.filter((row) => row.org_id?.trim() === oid);
  }
  P.filterOrgId.value = oid;
  saveOrgId(oid);
  void refreshProjects();
}

export function selectProject(id: string) {
  const pid = (id || "").trim();
  P.filterProjectId.value = pid;
  P.persistProjectId(pid);
  jobForm.project_id = pid;
  P.memberForm.project_id = pid;
  scheduleForm.project_id = pid;
}

export async function onCreateProject(ev: Event) {
  ev.preventDefault();
  const oid = P.filterOrgId.value.trim();
  if (!oid) {
    P.projectMsg.value = "请先在顶栏选择组织 / 事业部，再创建项目";
    return;
  }
  const id = P.projectForm.id.trim();
  const name = P.projectForm.name.trim() || id;
  try {
    await api("/api/v1/projects", {
      method: "POST",
      body: JSON.stringify({
        id,
        name,
        org_id: oid,
      }),
    });
    if (oid !== P.filterOrgId.value.trim()) return;
    P.projectMsg.value = "已创建项目";
    selectProject(id);
    await refreshProjects();
  } catch (e) {
    P.projectMsg.value = apiErrorMessage(e);
  }
}

export async function onAddMember(ev: Event) {
  ev.preventDefault();
  const pid = P.memberForm.project_id.trim();
  if (!pid) {
    P.memberMsg.value = "请先填写或选用项目";
    return;
  }
  try {
    await api(`/api/v1/projects/${encodeURIComponent(pid)}/members`, {
      method: "POST",
      body: JSON.stringify({
        username: P.memberForm.username.trim(),
        role: P.memberForm.role,
      }),
    });
    P.memberMsg.value = `已添加成员 ${P.memberForm.username.trim()}`;
    P.memberForm.username = "";
  } catch (e) {
    P.memberMsg.value = apiErrorMessage(e);
  }
}

export async function onRemoveMember(userId: string) {
  const pid = P.memberForm.project_id.trim() || P.filterProjectId.value.trim();
  if (!pid) return;
  if (!(await confirmDialog("确认移除该项目成员？"))) return;
  try {
    await api(
      `/api/v1/projects/${encodeURIComponent(pid)}/members/${encodeURIComponent(userId)}`,
      { method: "DELETE" },
    );
    P.memberMsg.value = "已移除成员";
  } catch (e) {
    P.memberMsg.value = apiErrorMessage(e);
  }
}

let projectFilterWatchInstalled = false;

/** 顶栏项目过滤变更：持久化并防抖刷新当前 Tab（幂等）。 */
export function installProjectFilterWatcher(opts: {
  loggedIn: { readonly value: boolean };
}): void {
  if (projectFilterWatchInstalled) return;
  projectFilterWatchInstalled = true;
  let filterDebounce: number | undefined;
  watch([P.filterOrgId, P.filterProjectId, () => opts.loggedIn.value], ([, projectId, loggedIn], [, previousProjectId, wasLoggedIn]) => {
    if (projectId !== previousProjectId) P.persistProjectId(projectId);
    if (filterDebounce) window.clearTimeout(filterDebounce);
    if (!loggedIn || !wasLoggedIn) return;
    filterDebounce = window.setTimeout(() => {
      const deps = requireDeps();
      void deps.refreshForTab(deps.activeTab.value);
    }, 400);
  });
}
