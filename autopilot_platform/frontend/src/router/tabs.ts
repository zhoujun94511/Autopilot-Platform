/**
 * Tab ↔ URL 单一目录（AUD-P2-009 Phase0）。
 * 现有 McTabId / refresh scopes 仍以 tab id 为真源；Router 只负责地址栏与深链。
 */
import type { McTabId, RefreshScope } from "../composables/mcRefreshScopes";
import { TAB_SCOPES } from "../composables/mcRefreshScopes";

export type TabGuard = "auth" | "ops" | "manageUsers";

export interface TabRouteDef {
  tab: McTabId;
  path: string;
  label: string;
  /** 侧栏分组（文档用） */
  section: "overview" | "design" | "exec" | "infra" | "admin";
  guards: TabGuard[];
  scopes: readonly RefreshScope[];
}

/** 主 Tab 路径（不含子区） */
export const TAB_ROUTES: readonly TabRouteDef[] = [
  { tab: "dashboard", path: "/dashboard", label: "概览", section: "overview", guards: ["auth"], scopes: TAB_SCOPES.dashboard },
  { tab: "projects", path: "/projects", label: "项目", section: "overview", guards: ["auth"], scopes: TAB_SCOPES.projects },
  { tab: "share", path: "/share", label: "共享", section: "overview", guards: ["auth"], scopes: TAB_SCOPES.share },
  { tab: "design-dashboard", path: "/design", label: "设计总览", section: "design", guards: ["auth"], scopes: TAB_SCOPES["design-dashboard"] },
  { tab: "design-docs", path: "/design/docs", label: "需求文档", section: "design", guards: ["auth"], scopes: TAB_SCOPES["design-docs"] },
  { tab: "design-cases", path: "/design/cases", label: "意图用例", section: "design", guards: ["auth"], scopes: TAB_SCOPES["design-cases"] },
  { tab: "design-knowledge", path: "/design/knowledge", label: "知识库", section: "design", guards: ["auth"], scopes: TAB_SCOPES["design-knowledge"] },
  { tab: "artifacts", path: "/exec/artifacts", label: "工程制品", section: "exec", guards: ["auth"], scopes: TAB_SCOPES.artifacts },
  { tab: "app-builds", path: "/exec/app-builds", label: "应用资源", section: "exec", guards: ["auth"], scopes: TAB_SCOPES["app-builds"] },
  { tab: "jobs", path: "/exec/jobs", label: "批跑", section: "exec", guards: ["auth"], scopes: TAB_SCOPES.jobs },
  { tab: "schedules", path: "/exec/schedules", label: "计划", section: "exec", guards: ["auth"], scopes: TAB_SCOPES.schedules },
  { tab: "reports", path: "/exec/reports", label: "报告", section: "exec", guards: ["auth"], scopes: TAB_SCOPES.reports },
  { tab: "devices", path: "/infra/devices", label: "设备", section: "infra", guards: ["auth"], scopes: TAB_SCOPES.devices },
  { tab: "ops", path: "/admin/ops", label: "运维 · 配置中心", section: "admin", guards: ["auth", "ops"], scopes: TAB_SCOPES.ops },
  { tab: "audit", path: "/admin/audit", label: "审计", section: "admin", guards: ["auth", "manageUsers"], scopes: TAB_SCOPES.audit },
  { tab: "users", path: "/admin/users", label: "用户", section: "admin", guards: ["auth", "manageUsers"], scopes: TAB_SCOPES.users },
] as const;

const BY_TAB = new Map(TAB_ROUTES.map((r) => [r.tab, r]));
const BY_PATH = new Map(TAB_ROUTES.map((r) => [r.path, r]));

/** 旧 tab / 废弃 id → 规范 tab */
export const LEGACY_TAB_REDIRECT: Record<string, McTabId> = {
  "design-chat": "dashboard",
  "design-config": "ops",
};

export function normalizeTabId(raw: string): McTabId {
  const t = (raw || "").trim();
  if (t in LEGACY_TAB_REDIRECT) return LEGACY_TAB_REDIRECT[t];
  if (BY_TAB.has(t as McTabId)) return t as McTabId;
  return "dashboard";
}

export function pathForTab(tab: string): string {
  const id = normalizeTabId(tab);
  return BY_TAB.get(id)?.path ?? "/dashboard";
}

export function labelForTab(tab: string): string {
  const id = normalizeTabId(tab);
  return BY_TAB.get(id)?.label ?? "";
}

export const SECTION_LABELS: Record<TabRouteDef["section"], string> = {
  overview: "概览",
  design: "测试设计",
  exec: "测试与执行",
  infra: "设备与执行",
  admin: "系统管理",
};

export function sectionIdForTab(tab: string): TabRouteDef["section"] {
  return defForTab(tab)?.section ?? "overview";
}

export function sectionLabelForTab(tab: string): string {
  return SECTION_LABELS[sectionIdForTab(tab)];
}

export function defForTab(tab: string): TabRouteDef | undefined {
  return BY_TAB.get(normalizeTabId(tab));
}

/** 最长前缀匹配 path → tab */
export function tabFromPath(path: string): McTabId {
  const p = (path || "/").replace(/\/+$/, "") || "/";
  if (p === "/" || p === "") return "dashboard";
  const exact = BY_PATH.get(p);
  if (exact) return exact.tab;
  let best: TabRouteDef | undefined;
  for (const def of TAB_ROUTES) {
    if (p === def.path || p.startsWith(def.path + "/")) {
      if (!best || def.path.length > best.path.length) best = def;
    }
  }
  return best?.tab ?? "dashboard";
}

/** DevicesHub / Projects 子区（query.section） */
export function hubSectionFromQuery(section: string, tab: McTabId): string {
  const s = (section || "").trim();
  if (tab === "devices") {
    if (s === "pools" || s === "runners" || s === "devices") return s;
    return "devices";
  }
  if (tab === "projects") {
    if (s === "org" || s === "collab") return s;
    return "";
  }
  return "";
}

export function opsCategoryFromQuery(category: string): string {
  return (category || "").trim();
}
