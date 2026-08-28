/** 设备列表展示辅助（AUD-2026-12 Wave 4 + 设备卡 UX 对齐）。 */

import type { Device } from "../api";
import { parseApiTime } from "./parseApiTime";

export type PlatformBucket = "android" | "ios" | "web" | "other";

export const PLATFORM_ORDER: PlatformBucket[] = ["android", "ios", "web", "other"];

export const PLATFORM_LABEL: Record<PlatformBucket, string> = {
  android: "安卓",
  ios: "苹果",
  web: "网页",
  other: "其他",
};

/** 上报名常为泛称，优先展示更具体的型号。 */
const GENERIC_NAMES = new Set([
  "iphone",
  "ipad",
  "ipod",
  "android",
  "phone",
  "device",
  "未知型号",
]);

export function normalizePlatform(raw: string | undefined | null): PlatformBucket {
  const p = String(raw || "").trim().toLowerCase();
  if (p === "android" || p === "and") return "android";
  if (p === "ios" || p === "iphone" || p === "ipad") return "ios";
  if (p === "web" || p === "browser" || p === "chrome" || p === "desktop") return "web";
  return "other";
}

export function platformBadgeLabel(raw: string | undefined | null): string {
  const p = String(raw || "").trim().toLowerCase();
  if (p === "http" || p === "api") return "接口";
  return PLATFORM_LABEL[normalizePlatform(raw)];
}

export function deviceKey(d: Device): string {
  return `${d.udid}::${d.runner_id}`;
}

/** DOM id 安全化（aria-controls / 展开区）。 */
export function deviceDomId(d: Device, prefix = "device"): string {
  return `${prefix}-${deviceKey(d).replace(/[^a-zA-Z0-9_-]/g, "_")}`;
}

export function udidSummary(udid: string): string {
  const u = String(udid || "").trim();
  if (!u) return "-";
  if (u.length <= 14) return u;
  return `${u.slice(0, 8)}…${u.slice(-4)}`;
}

/** Runner ID 截断：保留可读前缀 + 尾段，避免长串抢视线。 */
export function runnerSummary(runnerId: string): string {
  const id = String(runnerId || "").trim();
  if (!id) return "-";
  if (id.length <= 24) return id;
  return `${id.slice(0, 14)}…${id.slice(-8)}`;
}

const CODENAME_RE = /^[a-z][a-z0-9._-]{2,24}$/;
const ANDROID_SKU_RE = /^(sm-[a-z0-9]+|[a-z]{2,3}-[a-z0-9]+)$/i;

function looksLikeCodename(value: string): boolean {
  return CODENAME_RE.test(value);
}

function labelScore(value: string): number {
  const text = value.trim();
  if (!text) return -1;
  const lower = text.toLowerCase();
  if (GENERIC_NAMES.has(lower)) return 0;
  if (looksLikeCodename(text)) return 1;
  if (ANDROID_SKU_RE.test(text)) return 2;
  if (/iphone|ipad|pixel|galaxy/i.test(text) && /\s/.test(text)) return 6;
  if (/\s/.test(text)) return 5;
  if (/iphone|ipad|pixel|galaxy/i.test(text)) return 4;
  return 3;
}

/** 卡片主标题：市场型号，不把内部代号 / SKU 拼进标题。 */
export function displayName(d: { name?: string | null; model?: string | null }): string {
  const name = String(d.name || "").trim();
  const model = String(d.model || "").trim();
  if (!name && !model) return "未知型号";
  if (!model) return name;
  if (!name) return model;
  if (name.toLowerCase() === model.toLowerCase()) return name;
  const nameScore = labelScore(name);
  const modelScore = labelScore(model);
  if (nameScore !== modelScore) return nameScore > modelScore ? name : model;
  if (name.toLowerCase().includes(model.toLowerCase())) return name;
  if (model.toLowerCase().includes(name.toLowerCase())) return model;
  return name;
}

/** 用户给设备起的名字（与市场型号不同时才展示）。 */
export function deviceNickname(d: { name?: string | null; model?: string | null }): string {
  const name = String(d.name || "").trim();
  if (!name) return "";
  const title = displayName(d);
  if (!name || name === title) return "";
  if (labelScore(name) <= 2) return "";
  if (title.toLowerCase().includes(name.toLowerCase())) return "";
  return name;
}

export function deviceOsLabel(d: { platform?: string | null; os_version?: string | null }): string {
  const os = String(d.os_version || "").trim();
  if (!os) return "";
  const platform = normalizePlatform(d.platform);
  const lower = os.toLowerCase();
  if (platform === "android") {
    return lower.startsWith("android") ? os : `Android ${os}`;
  }
  if (platform === "ios") {
    if (lower.startsWith("ios") || lower.startsWith("ipados")) return os;
    return `iOS ${os}`;
  }
  return os;
}

export function deviceSourceLabel(d: Device): string {
  if (d.registration_source === "ide" && d.owner_user_id) return "IDE 私有";
  if (d.registration_source === "managed") return "平台托管";
  return "平台共享";
}

/** 执行节点来源：本机托管 / IDE / 远程设备机。 */
export function runnerSourceLabel(source?: string | null): string {
  const s = String(source || "").trim().toLowerCase();
  if (s === "managed") return "本机托管";
  if (s === "ide") return "IDE";
  return "远程设备机";
}

export type RunnerPresenceInput = {
  online?: boolean;
  last_heartbeat_at?: string | null;
  registration_source?: string | null;
  has_token?: boolean;
};

export type RunnerPresenceContext = {
  isManagedRow?: boolean;
  managedRunning?: boolean;
};

function relativeLastSeen(iso: string): string {
  const time = parseApiTime(iso);
  if (!Number.isFinite(time)) return iso;
  const seconds = Math.max(0, Math.floor((Date.now() - time) / 1000));
  if (seconds < 60) return "刚刚";
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分钟前`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} 小时前`;
  return `${Math.floor(seconds / 86400)} 天前`;
}

/** 列表主状态徽章：区分在线 / 未运行 / 待连接 / 离线。 */
export function runnerOnlineBadgeLabel(
  r: RunnerPresenceInput,
  ctx: RunnerPresenceContext = {},
): string {
  if (r.online) return "在线";
  if (!r.last_heartbeat_at && ctx.isManagedRow && !ctx.managedRunning) {
    return "未运行";
  }
  if (!r.last_heartbeat_at && r.has_token) {
    return "待连接";
  }
  return "离线";
}

export function runnerOnlineBadgeClass(
  r: RunnerPresenceInput,
  ctx: RunnerPresenceContext = {},
): string {
  if (r.online) return "status-succeeded";
  if (!r.last_heartbeat_at && (ctx.isManagedRow || r.has_token)) {
    return "status-ready";
  }
  return "status-failed";
}

/** 心跳副文案：避免「离线 + 从未上报」误导为异常。 */
export function runnerHeartbeatHint(
  r: RunnerPresenceInput,
  ctx: RunnerPresenceContext = {},
): string {
  if (r.online && r.last_heartbeat_at) {
    return relativeLastSeen(r.last_heartbeat_at);
  }
  if (r.last_heartbeat_at) {
    return `末次心跳 ${relativeLastSeen(r.last_heartbeat_at)}`;
  }
  if (ctx.isManagedRow && ctx.managedRunning === false) {
    return "请在上方「Platform 同机托管」中启动";
  }
  if (r.has_token) {
    return "已登记，等待节点启动并上报";
  }
  if (String(r.registration_source || "").toLowerCase() === "managed") {
    return "已登记，尚未启动本机托管";
  }
  return "尚无心跳记录";
}

export function runnerHeartbeatTitle(lastHeartbeatAt?: string | null): string {
  if (!lastHeartbeatAt) {
    return "无心跳时间戳（节点未连接，或 Platform 重启后已清空旧心跳）";
  }
  const time = parseApiTime(lastHeartbeatAt);
  if (!Number.isFinite(time)) return String(lastHeartbeatAt);
  return new Date(time).toLocaleString();
}

export function runnerDetailHeartbeatLabel(
  r: RunnerPresenceInput,
  ctx: RunnerPresenceContext = {},
): string {
  if (r.last_heartbeat_at) {
    const time = parseApiTime(r.last_heartbeat_at);
    if (Number.isFinite(time)) {
      return new Date(time).toLocaleString();
    }
    return String(r.last_heartbeat_at);
  }
  return runnerHeartbeatHint(r, ctx);
}

/** 卡片副行：系统 · 来源（所有者单独用 chip）。 */
export function deviceCardSummary(d: Device): string {
  const parts: string[] = [];
  const os = deviceOsLabel(d);
  if (os) parts.push(os);
  parts.push(deviceSourceLabel(d));
  return parts.join(" · ");
}

export type DeviceAvailability = {
  status: string;
  label: string;
  /** 维护态用独立 badge，不用 StatusPill */
  kind: "pill" | "maint";
};

/** 调度态：空闲用 ready（非 job succeeded 绿）。 */
export function deviceAvailability(d: Device): DeviceAvailability {
  if (d.admin_disabled) {
    return { status: "maint", label: "维护中", kind: "maint" };
  }
  if (d.busy) {
    return {
      status: "claimed",
      label: d.busy_kind === "reservation" ? "已占用" : "任务占用",
      kind: "pill",
    };
  }
  if (d.state && d.state !== "ready") {
    return { status: "failed", label: String(d.state), kind: "pill" };
  }
  return { status: "ready", label: "空闲", kind: "pill" };
}

export function remainingLabel(seconds?: number): string {
  const value = Math.max(0, Number(seconds || 0));
  if (value < 60) return "不足 1 分钟";
  const minutes = Math.ceil(value / 60);
  const hours = Math.floor(minutes / 60);
  const mins = minutes % 60;
  if (hours && mins) return `${hours}小时${mins}分`;
  if (hours) return `${hours}小时`;
  return `${minutes}分钟`;
}

/** 预占备注：去掉用途标签后仍有独立说明才展示，避免再画一遍「[手工调试]」。 */
export function reservationExtraNote(d: Device): string {
  const reason = String(d.reservation_reason || "").trim();
  if (!reason) return "";
  const purpose = String(d.reservation_purpose || "").trim();
  const stripped = reason.replace(/^\[[^\]]+\]\s*/, "").trim();
  if (!stripped) return "";
  if (purpose && stripped.toLowerCase() === purpose.toLowerCase()) return "";
  return stripped;
}

export function occupyLabel(d: Device): string {
  const base = (d.occupy_summary || "").trim() || (d.busy ? "占用中" : "");
  if (!base) return "";
  if (d.busy_kind === "reservation") {
    return `${base} · 剩余 ${remainingLabel(d.reservation_remaining_seconds)}`;
  }
  return base;
}

export function groupDevicesByPlatform(devices: Device[]) {
  const buckets: Record<PlatformBucket, Device[]> = {
    android: [],
    ios: [],
    web: [],
    other: [],
  };
  for (const d of devices) {
    buckets[normalizePlatform(d.platform)].push(d);
  }
  return PLATFORM_ORDER.filter((key) => buckets[key].length).map((key) => ({
    key,
    label: PLATFORM_LABEL[key],
    items: buckets[key],
  }));
}
