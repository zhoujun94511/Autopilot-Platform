/**
 * Tab → Panel 懒加载（vue-router 原生 async；降首包）。
 */
import type { McTabId } from "../composables/mcRefreshScopes";

export type PanelLoader = () => Promise<Record<string, unknown>>;

export const TAB_PANEL_LOADERS: Record<McTabId, PanelLoader> = {
  dashboard: () => import("../components/DashboardPanel.vue"),
  projects: () => import("../components/ProjectsPanel.vue"),
  share: () => import("../components/SharePanel.vue"),
  "design-dashboard": () => import("../components/design/DesignDashboardPanel.vue"),
  "design-docs": () => import("../components/design/DesignDocsPanel.vue"),
  "design-cases": () => import("../components/design/DesignCasesPanel.vue"),
  "design-knowledge": () => import("../components/design/DesignKnowledgePanel.vue"),
  devices: () => import("../components/DevicesHub.vue"),
  artifacts: () => import("../components/ArtifactsPanel.vue"),
  "app-builds": () => import("../components/AppBuildsPanel.vue"),
  jobs: () => import("../components/JobsPanel.vue"),
  schedules: () => import("../components/SchedulesPanel.vue"),
  reports: () => import("../components/ReportsPanel.vue"),
  ops: () => import("../components/OpsPanel.vue"),
  audit: () => import("../components/AuditPanel.vue"),
  users: () => import("../components/UsersPanel.vue"),
};

/** KeepAlive 缓存名（与 defineOptions.name 对齐） */
export const TAB_PANEL_NAMES: Record<McTabId, string> = {
  dashboard: "DashboardPanel",
  projects: "ProjectsPanel",
  share: "SharePanel",
  "design-dashboard": "DesignDashboardPanel",
  "design-docs": "DesignDocsPanel",
  "design-cases": "DesignCasesPanel",
  "design-knowledge": "DesignKnowledgePanel",
  devices: "DevicesHub",
  artifacts: "ArtifactsPanel",
  "app-builds": "AppBuildsPanel",
  jobs: "JobsPanel",
  schedules: "SchedulesPanel",
  reports: "ReportsPanel",
  ops: "OpsPanel",
  audit: "AuditPanel",
  users: "UsersPanel",
};

export const KEEPALIVE_INCLUDE = Object.values(TAB_PANEL_NAMES);
