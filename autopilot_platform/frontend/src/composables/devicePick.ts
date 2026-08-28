import type { Device } from "../api";
import { isDevicelessPlatform } from "./runTargetOptions";

/** 解析表单中的 UDID 串（逗号 / 分号 / 空白）。 */
export function parseUdids(raw: string | null | undefined): string[] {
  return String(raw || "")
    .split(/[,;\s]+/)
    .map((s) => s.trim())
    .filter(Boolean);
}

export function serializeUdids(udids: Iterable<string>): string {
  return [...new Set([...udids].map((u) => u.trim()).filter(Boolean))].join(", ");
}

/**
 * 批跑 / 计划共用的设备候选过滤。
 * 对齐 DeviceFarmer 式列表筛选：平台 + ready + backend 兼容。
 */
export function filterDevicesForPick(
  devices: readonly Device[],
  opts: { platform?: string; backendMode?: string } = {},
): Device[] {
  const plat = (opts.platform || "").toLowerCase();
  const mode = (opts.backendMode || "auto").toLowerCase();
  return (devices || []).filter((d) => {
    if (plat && !isDevicelessPlatform(plat) && (d.platform || "").toLowerCase() !== plat) {
      return false;
    }
    const st = (d.state || "ready").toLowerCase();
    if (st && st !== "ready") return false;
    const backends = d.backends || [];
    if (!backends.length || mode === "auto") return true;
    if (mode === "uia2" || mode === "android-appium") {
      return backends.includes("android-appium");
    }
    if (mode === "wda" || mode === "ios-wda") return backends.includes("ios-wda");
    if (mode === "appium" || mode === "ios-appium") {
      if (plat === "ios") return backends.includes("ios-appium");
      if (plat === "android") return backends.includes("android-appium");
      return backends.includes("android-appium") || backends.includes("ios-appium");
    }
    return backends.includes(mode);
  });
}

export function deviceSearchHaystack(d: Device): string {
  return [
    d.name,
    d.model,
    d.udid,
    d.os_version,
    d.runner_id,
    ...(d.backends || []),
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
}
