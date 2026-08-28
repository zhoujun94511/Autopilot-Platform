/** 设计域状态枚举 → 中文（单一来源，供总览 / 列表 / 统计共用）。 */

import {
  AUTOMATION_STATUS_OPTIONS,
  REVIEW_STATUS_OPTIONS,
  type AutomationStatus,
} from "../api/designCases";

export { AUTOMATION_STATUS_OPTIONS, REVIEW_STATUS_OPTIONS };

const AUTOMATION_MAP = Object.fromEntries(
  AUTOMATION_STATUS_OPTIONS.map((o) => [o.value, o.label]),
) as Record<AutomationStatus, string>;

const REVIEW_MAP = Object.fromEntries(
  REVIEW_STATUS_OPTIONS.filter((o) => o.value).map((o) => [o.value, o.label]),
);

export function automationStatusLabel(status: string | undefined | null): string {
  const key = String(status || "").trim();
  if (!key) return "—";
  return AUTOMATION_MAP[key as AutomationStatus] || key;
}

export function reviewStatusLabel(status: string | undefined | null): string {
  const key = String(status || "").trim();
  if (!key) return "—";
  return REVIEW_MAP[key] || key;
}

export function formatAutomationStatusKey(key: string): string {
  return automationStatusLabel(key);
}

export function formatReviewStatusKey(key: string): string {
  return reviewStatusLabel(key);
}
