/**
 * Tab 刷新与轮询。
 * 业务 refresh* 直接调各域 Actions；会话相关经 bindPollingDeps 注入。
 */
import type { Router } from "vue-router";
import { watch, type Ref } from "vue";
import { ApiHttpError, apiErrorMessage, ensureFreshSession, hasRefreshSession } from "../api";
import {
  hasActiveJobs,
  pollIntervalForTab,
  scopesForTab,
  type RefreshScope,
} from "./mcRefreshScopes";
import * as ExecActions from "./mcExecActions";
import * as AdminActions from "./mcAdminActions";
import * as OpsActions from "./mcOpsActions";
import * as SessionActions from "./mcSessionActions";
import { jobs as execJobs } from "./mcExecState";

export type PollingDeps = {
  loggedIn: { readonly value: boolean };
  pageVisible: Ref<boolean>;
  activeTab: Ref<string>;
  error: Ref<string>;
  isPlatformAdmin: { readonly value: boolean };
  getRouter: () => Router | null;
  onUnauthorized: () => void;
  refreshHealth: () => Promise<void>;
  refreshOrgs: () => Promise<void>;
  refreshProjects: () => Promise<void>;
};

let d: PollingDeps;
let timer: number | undefined;
let refreshSeq = 0;
let overlayBusy = false;

export function bindPollingDeps(deps: PollingDeps): void {
  d = deps;
}

function requireDeps(): PollingDeps {
  if (!d) throw new Error("bindPollingDeps() must be called before polling");
  return d;
}

export function getRefreshSeq(): number {
  return refreshSeq;
}

function normalizeTabIdSafe(tab: string): string {
  const t = (tab || "").trim();
  if (t === "design-chat") return "dashboard";
  if (t === "design-config") return "ops";
  return t || "dashboard";
}

/** 按范围拉取数据；仅请求当前 Tab / 变更影响到的 API。 */
export async function refreshScopes(scopes: Iterable<RefreshScope>) {
  const deps = requireDeps();
  if (!deps.loggedIn.value && !hasRefreshSession()) return;
  const ready = await ensureFreshSession();
  if (!ready) {
    stopPolling();
    return;
  }
  if (!deps.loggedIn.value) return;
  const uniq = [...new Set(scopes)];
  if (!uniq.length) return;
  await SessionActions.ensurePlatformBootFresh(refreshScopes);
  const seq = ++refreshSeq;
  deps.error.value = "";
  try {
    const tasks: Promise<unknown>[] = [];
    for (const scope of uniq) {
      switch (scope) {
        case "health":
          tasks.push(deps.refreshHealth());
          break;
        case "runners":
          tasks.push(ExecActions.refreshRunners());
          break;
        case "managed-runner":
          tasks.push(ExecActions.refreshManagedRunner());
          break;
        case "devices":
          tasks.push(ExecActions.refreshDevicesData());
          break;
        case "jobs":
          tasks.push(ExecActions.refreshJobsList(seq));
          break;
        case "reports":
          tasks.push(ExecActions.refreshReportsList(seq));
          break;
        case "artifacts":
          tasks.push(ExecActions.refreshArtifactsList(seq));
          break;
        case "app-builds":
          tasks.push(ExecActions.refreshAppBuildsList(seq));
          break;
        case "projects":
          tasks.push(deps.refreshOrgs());
          tasks.push(deps.refreshProjects());
          break;
        case "schedules":
          tasks.push(ExecActions.refreshSchedules());
          break;
        case "audit":
          tasks.push(AdminActions.refreshAudits());
          break;
        case "ops-summary":
          tasks.push(OpsActions.refreshOps());
          break;
        case "ops-config":
          tasks.push(OpsActions.refreshOpsConfig());
          break;
        case "users":
          tasks.push(AdminActions.refreshUsers());
          break;
        default:
          break;
      }
    }
    await Promise.all(tasks);
    if (seq !== refreshSeq) return;
  } catch (e) {
    if (seq !== refreshSeq) return;
    deps.error.value = apiErrorMessage(e);
    if (e instanceof ApiHttpError && e.status === 401) {
      deps.onUnauthorized();
    }
  }
}

/** 刷新当前 Tab 所需数据（手动刷新 / 切 Tab / 轮询均走此入口）。 */
export async function refreshForTab(tab?: string) {
  const deps = requireDeps();
  const tabId = tab ?? deps.activeTab.value;
  let scopes = scopesForTab(tabId, { isPlatformAdmin: deps.isPlatformAdmin.value });
  const router = deps.getRouter();
  if (router) {
    const meta = router.currentRoute.value.meta;
    const metaTab = typeof meta.tab === "string" ? meta.tab : "";
    const metaScopes = meta.scopes;
    if (
      metaTab &&
      normalizeTabIdSafe(metaTab) === normalizeTabIdSafe(tabId) &&
      Array.isArray(metaScopes)
    ) {
      scopes = [...(metaScopes as RefreshScope[])];
      if (tabId === "dashboard" && deps.isPlatformAdmin.value) {
        for (const s of ["devices", "ops-summary"] as RefreshScope[]) {
          if (!scopes.includes(s)) scopes.push(s);
        }
      }
    }
  }
  await refreshScopes(scopes);
}

export async function refreshAll() {
  await refreshForTab(requireDeps().activeTab.value);
}

function pollOpts() {
  const deps = requireDeps();
  return {
    hasActiveJobs: hasActiveJobs(execJobs.value),
    pageVisible: deps.pageVisible.value,
    overlayBusy,
  };
}

export function startPolling() {
  const deps = requireDeps();
  stopPolling();
  if (!deps.loggedIn.value || !deps.pageVisible.value || overlayBusy) return;
  const ms = pollIntervalForTab(deps.activeTab.value, pollOpts());
  if (ms == null) return;
  timer = window.setInterval(() => {
    if (!deps.pageVisible.value || overlayBusy) {
      stopPolling();
      return;
    }
    void refreshForTab(deps.activeTab.value);
    const next = pollIntervalForTab(deps.activeTab.value, pollOpts());
    if (next !== ms) startPolling();
  }, ms);
}

export function stopPolling() {
  if (timer) {
    window.clearInterval(timer);
    timer = undefined;
  }
}

export function setPageVisible(visible: boolean) {
  const deps = requireDeps();
  const was = deps.pageVisible.value;
  deps.pageVisible.value = visible;
  if (!deps.loggedIn.value) return;
  if (visible && !was) {
    if (!overlayBusy) void refreshForTab(deps.activeTab.value);
    startPolling();
  } else if (!visible && was) {
    stopPolling();
  }
}

/** 远控等全屏遮罩：停掉管理台后台轮询；关闭后恢复。手动刷新按钮仍可用。 */
export function setOverlayBusy(busy: boolean): void {
  if (overlayBusy === busy) return;
  overlayBusy = busy;
  const deps = requireDeps();
  if (!deps.loggedIn.value) return;
  if (busy) {
    stopPolling();
    return;
  }
  startPolling();
}

/** 切 Tab 时刷新 + 重算轮询间隔（幂等 watch，由 platformRuntime 安装）。 */
export function onActiveTabChanged(tab: string, prev: string) {
  const deps = requireDeps();
  if (!deps.loggedIn.value) return;
  if (tab === prev) return;
  if (!overlayBusy) void refreshForTab(tab);
  startPolling();
}

let activeTabWatchInstalled = false;

export function installActiveTabWatcher(): void {
  if (activeTabWatchInstalled) return;
  activeTabWatchInstalled = true;
  const deps = requireDeps();
  watch(deps.activeTab, (tab, prev) => {
    onActiveTabChanged(String(tab || ""), String(prev || ""));
  });
}
