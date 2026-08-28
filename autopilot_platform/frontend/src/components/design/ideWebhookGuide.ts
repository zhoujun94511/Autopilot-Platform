/** 审核通过后 → IDE 自动导入指引（高级可选）。 */

export const DEFAULT_DESIGN_WEBHOOK_URL = "http://127.0.0.1:8765/hooks/intent";

export const IDE_WEBHOOK_SETUP_STEPS = [
  "在 AutoPilot IDE 打开目标工程，并登录当前管理台项目。",
  "在 IDE 终端启动接收服务（详见文档）。",
  "到管理台「运维 → 配置」填写通知地址并保存，再点「发送测试」。",
  "网页端审核通过后，IDE 会自动写入工程。",
] as const;

export const IDE_WEBHOOK_ALTERNATIVES = [
  "也可在 IDE 用菜单「导入意图用例」一次性拉取。",
  "或使用命令行 watch / import（详见文档）。",
] as const;
