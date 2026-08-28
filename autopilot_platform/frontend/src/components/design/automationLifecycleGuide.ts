/** 自动化生命周期指引（面向测试同学，不暴露内部状态码）。 */

export const VERIFIER_LIFECYCLE_STEPS = [
  "设计用例审核通过后，导入 IDE 或等待管理台同步。",
  "在本机运行或远程批跑完成首跑；通过后平台会标为可执行。",
  "若步骤定位失败，请在 IDE 补齐绑定或审阅失败意图后再跑。",
] as const;

export const SOLIDIFY_CLI_STEPS = [
  "多次稳定命中后，可用 IDE 菜单「固化稳定意图步…」把意图步骤变成普通关键字。",
  "也可在命令行对工程批量固化（详见文档）。",
] as const;

export function verifierHintFromStats(byAutomation: Record<string, number> | undefined): string {
  const pending = Number(byAutomation?.PENDING_VERIFY || 0);
  const executable = Number(byAutomation?.EXECUTABLE || 0);
  const debugging = Number(byAutomation?.DEBUGGING || 0);
  if (pending > 0) {
    return `${pending} 条待首跑验证：请入队批跑或在 IDE 本地运行，通过后即可执行。`;
  }
  if (debugging > 0) {
    return `${debugging} 条调试中：请在 IDE 查看失败意图并补齐绑定。`;
  }
  if (executable > 0) {
    return `${executable} 条已可执行；稳定步骤可在 IDE 固化为普通关键字。`;
  }
  return "首跑验证通过后，用例会进入可执行状态。";
}
