/** 管理台按需刷新：每个 Tab 只拉当前视图所需数据，避免全量轮询。 */

export type McTabId =
  | "dashboard"
  | "projects"
  | "share"
  | "devices"
  | "artifacts"
  | "app-builds"
  | "jobs"
  | "schedules"
  | "reports"
  | "ops"
  | "audit"
  | "users"
  | "design-dashboard"
  | "design-docs"
  | "design-cases"
  | "design-knowledge";

export type RefreshScope =
  | "health"
  | "runners"
  | "managed-runner"
  | "devices"
  | "jobs"
  | "reports"
  | "artifacts"
  | "app-builds"
  | "projects"
  | "schedules"
  | "audit"
  | "ops-summary"
  | "ops-config"
  | "users";

/** 各 Tab 首次进入 / 轮询时需要的 API 范围 */
export const TAB_SCOPES: Record<McTabId, readonly RefreshScope[]> = {
  dashboard: ["health", "runners", "jobs"],
  projects: ["projects"],
  share: ["projects"],
  devices: ["runners", "devices", "managed-runner"],
  artifacts: ["artifacts"],
  "app-builds": ["app-builds"],
  jobs: ["jobs", "devices", "artifacts", "app-builds", "projects"],
  // devices：计划表单 DevicePicker 与批跑共用候选列表，不依赖「设备与执行」侧栏
  schedules: ["schedules", "projects", "artifacts", "app-builds", "devices"],
  reports: ["reports", "jobs"],
  ops: ["ops-summary", "ops-config"],
  audit: ["audit"],
  users: ["users"],
  // 设计域面板自行拉数；勿回落到 dashboard 以免误打 runners/devices/jobs/ops
  "design-dashboard": [],
  "design-docs": [],
  "design-cases": [],
  "design-knowledge": [],
};

/** 默认轮询间隔（ms）；null = 不自动轮询，仅切换 Tab / 手动 / 变更后刷新 */
export const TAB_POLL_MS: Record<McTabId, number | null> = {
  dashboard: 30_000,
  devices: 20_000,
  jobs: 15_000,
  schedules: 60_000,
  ops: 60_000,
  projects: null,
  share: null,
  artifacts: null,
  "app-builds": null,
  reports: null,
  audit: null,
  users: null,
  "design-dashboard": null,
  "design-docs": null,
  "design-cases": null,
  "design-knowledge": null,
};

const ACTIVE_JOB_STATUSES = new Set(["pending", "claimed", "running"]);

const PLATFORM_ADMIN_DASHBOARD_EXTRA: RefreshScope[] = ["devices", "ops-summary"];

export function scopesForTab(
  tab: string,
  opts?: { isPlatformAdmin?: boolean },
): RefreshScope[] {
  const known = TAB_SCOPES[tab as McTabId];
  if (known) {
    const base = [...known];
    if (tab === "dashboard" && opts?.isPlatformAdmin) {
      for (const s of PLATFORM_ADMIN_DASHBOARD_EXTRA) {
        if (!base.includes(s)) base.push(s);
      }
    }
    return base;
  }
  // 未知 design-* 等自管数据 Tab：空范围，避免误打 dashboard 全量 API
  if (tab.startsWith("design-")) return [];
  return scopesForTab("dashboard", opts);
}

export function pollIntervalForTab(
  tab: string,
  opts: { hasActiveJobs?: boolean; pageVisible?: boolean; overlayBusy?: boolean },
): number | null {
  if (opts.pageVisible === false) return null;
  // 远控全屏遮罩盖住设备板时，runners/devices/managed 日志轮询帮不上忙，还会和会话探测抢带宽。
  if (opts.overlayBusy) return null;
  const base = TAB_POLL_MS[tab as McTabId];
  if (base == null) return null;
  if (tab === "jobs") {
    return opts.hasActiveJobs ? 10_000 : 45_000;
  }
  if (tab === "dashboard" && opts.hasActiveJobs) {
    return 15_000;
  }
  return base;
}

export function hasActiveJobs(jobs: { status?: string }[]): boolean {
  return (jobs || []).some((j) => ACTIVE_JOB_STATUSES.has(String(j.status || "")));
}
