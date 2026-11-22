/**
 * Tab 刷新与轮询。
 * 业务 refresh* 直接调各域 Actions；会话相关经 bindPollingDeps 注入。
 */
import type { Router } from "vue-router";
import { onScopeDispose, watch, type Ref } from "vue";
import { ApiHttpError, apiErrorMessage, ensureFreshSession, getAuthSessionVersion, hasRefreshSession } from "../api";
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
import { workspaceScopeVersion } from "./mcProjectsState";

export type PollingDeps = {
  loggedIn: { readonly value: boolean };
  sessionHydrating: { readonly value: boolean };
  pageVisible: Ref<boolean>;
  activeTab: Ref<string>;
  error: Ref<string>;
  isPlatformAdmin: { readonly value: boolean };
  getRouter: () => Router | null;
  onUnauthorized: () => void;
  refreshOrgs: () => Promise<void>;
  refreshProjects: () => Promise<void>;
};

let d: PollingDeps;
let timer: number | undefined;
let refreshSeq = 0;
let overlayBusy = false;
let lastJobsContextRefreshAt = -Infinity;
let jobsPage: {
  refresh: () => Promise<void>;
  hasActiveJobs: () => boolean;
  isCreateOpen: () => boolean;
} | undefined;

export function registerJobsPage(page: NonNullable<typeof jobsPage>) {
  jobsPage = page;
  watch(page.hasActiveJobs, () => {
    if (jobsPage === page && d?.activeTab.value === "jobs") startPolling();
  });
  onScopeDispose(() => {
    if (jobsPage === page) jobsPage = undefined;
  });
}

export function bindPollingDeps(deps: PollingDeps): void {
  d = deps;
}

function requireDeps(): PollingDeps {
  if (!d) throw new Error("bindPollingDeps() must be called before polling");
  return d;
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
  const authVersion = getAuthSessionVersion();
  const workspace = workspaceScopeVersion.value;
  const current = () => authVersion === getAuthSessionVersion() &&
    workspace === workspaceScopeVersion.value;
  const requested = new Set(scopes);
  if (!requested.size) return;
  const ready = await ensureFreshSession();
  if (!ready) {
    if (current()) stopPolling();
    return;
  }
  if (!current() || !deps.loggedIn.value) return;
  const seq = ++refreshSeq;
  // The health response also identifies a Platform restart.
  requested.delete("health");
  if (await SessionActions.refreshHealth()) {
    requested.add("runners");
    requested.add("devices");
    requested.add("managed-runner");
  }
  if (!current() || !deps.loggedIn.value) return;
  if (seq === refreshSeq) deps.error.value = "";
  try {
    const tasks: Promise<unknown>[] = [];
    for (const scope of requested) {
      switch (scope) {
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
          if (deps.activeTab.value === "jobs") {
            // JobsPanel loads its first page itself and owns the active filters and pagination.
            if (jobsPage) tasks.push(jobsPage.refresh());
          } else {
            tasks.push(ExecActions.refreshJobsList());
          }
          break;
        case "reports":
          tasks.push(ExecActions.refreshReportsList());
          break;
        case "artifacts":
          tasks.push(ExecActions.refreshArtifactsList());
          break;
        case "app-builds":
          tasks.push(ExecActions.refreshAppBuildsList());
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
  } catch (e) {
    if (!current() || seq !== refreshSeq) return;
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
  if (tabId === "jobs") lastJobsContextRefreshAt = performance.now();
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
    hasActiveJobs: deps.activeTab.value === "jobs"
      ? jobsPage?.hasActiveJobs() ?? false
      : hasActiveJobs(execJobs.value),
    pageVisible: deps.pageVisible.value,
    overlayBusy,
  };
}

let pollInFlight = false;

export function startPolling() {
  const deps = requireDeps();
  stopPolling();
  if (!deps.loggedIn.value || !deps.pageVisible.value || overlayBusy) return;
  const tab = deps.activeTab.value;
  const opts = pollOpts();
  const ms = pollIntervalForTab(tab, opts);
  if (ms == null) return;
  const jobsContextMs = tab === "jobs" && opts.hasActiveJobs
    ? pollIntervalForTab(tab, { ...opts, hasActiveJobs: false })
    : null;
  timer = window.setInterval(() => {
    if (!deps.pageVisible.value || overlayBusy) {
      stopPolling();
      return;
    }
    if (pollInFlight) return;
    pollInFlight = true;
    // Only task progress needs the fast cadence unless the creation form is using its live inputs.
    const work =
      jobsContextMs != null && deps.activeTab.value === tab && !jobsPage?.isCreateOpen() &&
      performance.now() - lastJobsContextRefreshAt < jobsContextMs
        ? refreshScopes(["jobs"])
        : refreshForTab(deps.activeTab.value);
    void work.finally(() => {
      pollInFlight = false;
      const next = pollIntervalForTab(deps.activeTab.value, pollOpts());
      if (next !== ms) startPolling();
    });
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
  if (!deps.loggedIn.value || deps.sessionHydrating.value) return;
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
