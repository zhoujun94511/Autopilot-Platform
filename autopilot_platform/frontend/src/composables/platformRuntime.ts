/**
 * Platform 前端运行时接线。
 * 仅负责 bind*Deps + 全局 watch + Router/Pinia 挂载后接线；无业务 reactive 门面。
 */
import type { Router } from "vue-router";
import { getActivePinia } from "pinia";
import { runnerCliFallback } from "../api/bootstrap";
import { installTabRouteSync } from "../navigation/tabSync";
import { useAuthStore } from "../stores/auth";
import { useContextStore } from "../stores/context";
import { useExecStore } from "../stores/execution";
import { useAdminStore } from "../stores/adminStore";
import { useOpsStore } from "../stores/opsStore";
import { useProjectsStore } from "../stores/projectsStore";
import { useShellStore } from "../stores/shellStore";
import * as ExecActions from "./mcExecActions";
import * as AdminActions from "./mcAdminActions";
import * as OpsActions from "./mcOpsActions";
import * as opsState from "./mcOpsState";
import * as Polling from "./mcPolling";
import * as projectsState from "./mcProjectsState";
import * as ProjectsActions from "./mcProjectsActions";
import * as sessionState from "./mcSessionState";
import * as SessionActions from "./mcSessionActions";
import * as shellState from "./mcShellState";

const LIST_PAGE_SIZE = 50;

async function refreshOrgsVoid(): Promise<void> {
  await ProjectsActions.refreshOrgs();
}

async function refreshProjectsVoid(): Promise<void> {
  await ProjectsActions.refreshProjects();
}

function bindSessionActionDeps() {
  SessionActions.bindSessionDeps({
    activeTab: shellState.activeTab,
    refreshOrgs: refreshOrgsVoid,
    refreshProjects: refreshProjectsVoid,
    refreshForTab: Polling.refreshForTab,
    startPolling: Polling.startPolling,
    stopPolling: Polling.stopPolling,
  });
}

function bindProjectsActionDeps() {
  ProjectsActions.bindProjectsDeps({
    user: sessionState.user,
    activeTab: shellState.activeTab,
    refreshForTab: Polling.refreshForTab,
  });
}

function bindPollingActionDeps() {
  Polling.bindPollingDeps({
    loggedIn: sessionState.loggedIn,
    pageVisible: shellState.pageVisible,
    activeTab: shellState.activeTab,
    error: shellState.error,
    isPlatformAdmin: sessionState.isPlatformAdmin,
    getRouter: () => shellState.getShellRouter(),
    onUnauthorized: () => {
      void SessionActions.onLogout();
    },
    refreshHealth: SessionActions.refreshHealth,
    refreshOrgs: refreshOrgsVoid,
    refreshProjects: refreshProjectsVoid,
  });
}

function bindAdminActionDeps() {
  AdminActions.bindAdminDeps({
    canManageUsers: sessionState.canManageUsers,
    currentUser: sessionState.user,
  });
}

function bindOpsActionDeps() {
  OpsActions.bindOpsDeps({
    isAdmin: () => sessionState.user.value?.role === "admin",
    activeTab: shellState.activeTab,
  });
}

function bindExecActionDeps() {
  ExecActions.bindExecDeps({
    filterProjectId: projectsState.filterProjectId,
    isPlatformAdmin: sessionState.isPlatformAdmin,
    listPageSize: LIST_PAGE_SIZE,
    getRefreshSeq: Polling.getRefreshSeq,
    refreshScopes: Polling.refreshScopes,
    runnerCliFallback,
    appBuildRetentionDays: () => String(opsState.opsConfig.MC_APP_BUILD_RETENTION_DAYS || "90"),
  });
  ExecActions.installExecFormWatchers();
}

function installRuntimeWatchers() {
  ProjectsActions.installProjectFilterWatcher({ loggedIn: sessionState.loggedIn });
  Polling.installActiveTabWatcher();
}

/** 模块加载即完成域依赖注入（Router 未就绪时 shell router 为 null）。 */
bindSessionActionDeps();
bindPollingActionDeps();
bindProjectsActionDeps();
bindExecActionDeps();
bindAdminActionDeps();
bindOpsActionDeps();
installRuntimeWatchers();

/**
 * main.ts：Pinia + Router 挂载后接线，激活 URL ↔ activeTab 同步。
 */
export function wirePlatformRuntime(router: Router): void {
  shellState.setShellRouter(router);
  installTabRouteSync(router, {
    activeTab: shellState.activeTab,
    opsFocusCategory: shellState.opsFocusCategory,
  });
  const pinia = getActivePinia();
  if (pinia) {
    useAuthStore(pinia);
    useShellStore(pinia);
    useExecStore(pinia);
    useAdminStore(pinia);
    useOpsStore(pinia);
    useProjectsStore(pinia);
    useContextStore(pinia);
  }
  // Router 就绪后重绑依赖（getRouter / activeTab 等已可用）
  bindExecActionDeps();
  bindAdminActionDeps();
  bindOpsActionDeps();
  bindPollingActionDeps();
}

/** @deprecated 旧名；请用 wirePlatformRuntime */
export const wireMcStoreToRouter = wirePlatformRuntime;
