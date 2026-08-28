/** 自动化状态说明（设计域列表 / 筛选）。 */

import type { AutomationStatus } from "../../api/designCases";

export const AUTOMATION_STATUS_HINTS: Record<string, string> = {
  LOGICAL_ONLY: "仅有逻辑步骤，尚未导入 IDE。",
  INTENT_READY: "已导入 IDE，可本地运行或入队首跑。",
  PENDING_VERIFY: "首跑已通过，待补齐断言证据后即可正式执行。",
  BINDING_PARTIAL: "部分步骤缺少控件绑定；请在 IDE 补齐后再跑。",
  DRAFT_AUTOMATION: "自动化草稿，尚未进入稳定验证。",
  MAPPING_REQUIRED: "失败且需重新映射。",
  DEBUGGING: "最近批跑失败或待审阅；请在 IDE 查看失败意图。",
  EXECUTABLE: "验证通过，可发布或固化为普通步骤。",
  PUBLISHED: "已发布到正式回归集。",
  DEPRECATED: "已废弃，不再参与入队。",
};

export const AUTOMATION_QUICK_FILTERS: {
  value: AutomationStatus | "";
  label: string;
  title: string;
}[] = [
  { value: "", label: "全部", title: "不按自动化状态筛选" },
  { value: "PENDING_VERIFY", label: "待验证", title: AUTOMATION_STATUS_HINTS.PENDING_VERIFY },
  { value: "EXECUTABLE", label: "可执行", title: AUTOMATION_STATUS_HINTS.EXECUTABLE },
  { value: "DEBUGGING", label: "调试中", title: AUTOMATION_STATUS_HINTS.DEBUGGING },
  { value: "INTENT_READY", label: "意图可跑", title: AUTOMATION_STATUS_HINTS.INTENT_READY },
];

export function automationStatusHint(status: string | undefined): string {
  const key = String(status || "").trim();
  return AUTOMATION_STATUS_HINTS[key] || "自动化状态由导入与批跑结果自动更新。";
}

export function countByAutomationStatus(
  cases: readonly { automation_status?: string }[],
): Record<string, number> {
  const out: Record<string, number> = {};
  for (const c of cases) {
    const k = String(c.automation_status || "LOGICAL_ONLY").trim() || "LOGICAL_ONLY";
    out[k] = (out[k] || 0) + 1;
  }
  return out;
}
