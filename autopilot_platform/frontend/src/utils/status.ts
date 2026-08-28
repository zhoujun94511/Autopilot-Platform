/** 批跑 / 设备相关状态文案与规范化 */

const LABELS: Record<string, string> = {
  pending: "排队中",
  claimed: "已认领",
  running: "执行中",
  succeeded: "成功",
  failed: "失败",
  cancelled: "已取消",
  /** 设备调度：可用（与 job succeeded 语义分离） */
  ready: "空闲",
  idle: "空闲",
  unknown: "未知",
};

export function normalizeStatus(status: string | null | undefined): string {
  const s = (status || "unknown").toLowerCase().trim();
  return s || "unknown";
}

export function statusLabel(status: string | null | undefined): string {
  const key = normalizeStatus(status);
  return LABELS[key] || status || "未知";
}

export const JOB_STATUS_FILTERS = [
  { value: "", label: "全部" },
  { value: "pending", label: "排队中" },
  { value: "claimed", label: "已认领" },
  { value: "running", label: "执行中" },
  { value: "succeeded", label: "成功" },
  { value: "failed", label: "失败" },
  { value: "cancelled", label: "已取消" },
] as const;
