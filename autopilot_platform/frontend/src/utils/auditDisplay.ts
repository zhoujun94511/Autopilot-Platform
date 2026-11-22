/** 审计 / 设计域活动可读化（全中文化摘要，详情抽屉保留原始技术字段）。 */

import type { AuditLog } from "../api";
import { parseApiTime } from "./parseApiTime";

const ACTION_LABELS: Record<string, string> = {
  "design.logical_case.create": "创建意图用例",
  "design.logical_case.update": "更新意图用例",
  "design.logical_case.delete": "删除意图用例",
  "design.logical_case.generate": "AI 生成用例",
  "design.logical_case.batch_generate": "批量生成用例",
  "design.logical_case.batch_delete": "批量删除用例",
  "design.logical_case.regenerate": "重新生成用例",
  "design.logical_case.enqueue_job": "提交远程批跑",
  "design.requirement.create": "创建需求",
  "design.requirement.update": "更新需求",
  "design.requirement.delete": "删除需求",
  "design.requirement.import": "导入需求",
  "design.requirement.batch_delete": "批量删除需求",
  "design.knowledge.create": "创建知识条目",
  "design.knowledge.update": "更新知识条目",
  "design.knowledge.delete": "删除知识条目",
  "design.knowledge.import": "导入知识库",
  "design.knowledge.rebuild": "重建知识索引",
  "design.knowledge.batch_delete": "批量删除知识",
  "design.document.upload": "上传需求文档",
  "design.document.import": "导入文档",
  "design.document.delete": "删除文档",
  "design.document.batch_delete": "批量删除文档",
  "design.document.analyze": "解析需求文档",
  "design.batch_export": "导出设计域数据",
  "design.config_update": "更新设计配置",
  "design.config_import": "导入设计配置",
  "design.experimental_action.confirm": "确认实验操作",
  "user.create": "创建用户",
  "user.update": "更新用户",
  "user.delete": "删除用户",
  "user.password_reset": "重置用户密码",
  "user.disable": "禁用用户",
  "user.enable": "启用用户",
  "org.create": "创建组织",
  "org.update": "更新组织",
  "org.member.add": "添加组织成员",
  "org.member.remove": "移除组织成员",
  "project.create": "创建项目",
  "project.update": "更新项目",
  "project.delete": "删除项目",
  "project.member.add": "添加项目成员",
  "project.member.update": "调整项目成员角色",
  "project.member.remove": "移除项目成员",
  "project.invite.create": "发送项目邀请",
  "project.invite.revoke": "撤销项目邀请",
  "project.invite.accept": "接受项目邀请",
  "project.invite.register": "通过邀请注册",
  "job.create": "创建批跑任务",
  "job.cancel": "取消批跑任务",
  "job.retry": "重试批跑任务",
  "job.reclaim": "回收超时任务",
  "schedule.create": "创建定时计划",
  "schedule.update": "更新定时计划",
  "schedule.delete": "删除定时计划",
  "schedule.enable": "启用定时计划",
  "schedule.disable": "停用定时计划",
  "schedule.run": "立即执行计划",
  "artifact.upload": "上传工程制品",
  "artifact.delete": "删除工程制品",
  "artifact.purge": "清理过期制品",
  "app_build.upload": "上传应用资源",
  "app_build.reuse": "复用应用资源",
  "app_build.update": "更新应用资源",
  "app_build.delete": "删除应用资源",
  "app_build.purge": "清理过期应用",
  "runner.register": "注册执行节点",
  "runner.update": "更新执行节点",
  "runner.delete": "注销执行节点",
  "runner.unregister": "注销执行节点",
  "runner.rotate_token": "轮换节点令牌",
  "device.reserve": "占用设备",
  "device.reservation.release": "释放设备占用",
  "device.reservation_release": "释放设备占用",
  "device.release": "强制释放设备",
  "device.maintenance": "切换设备维护状态",
  "device.disable": "设备停用维护",
  "device.enable": "设备恢复调度",
  "device.maintenance.enable": "设备停用维护",
  "device.maintenance.disable": "设备恢复调度",
  "device.remote_session_start": "开启远程调试",
  "device.remote_session_stop": "关闭远程调试",
  "device.remote_participant_promote": "移交远控控制权",
  "device.remote_session.start": "开启远程调试",
  "device.remote_session.create": "开启远程调试",
  "device.remote_session.stop": "关闭远程调试",
  "device.remote_session.close": "关闭远程调试",
  "device.remote_session.join": "加入旁观调试",
  "device.remote_session.leave": "退出旁观调试",
  "device.remote_command.accessibility": "远控无障碍操作",
  "device.remote_command.stream.configure": "调整远控画质流",
  "device.remote_command.clipboard": "远控剪贴板操作",
  "device.remote_command.file": "远控文件操作",
  "device.remote_command.app": "远控应用操作",
  "device.remote_command.input": "远控按键输入",
  "resource_pool.create": "创建设备池",
  "resource_pool.update": "更新设备池",
  "resource_pool.delete": "删除设备池",
  "resource_pool.device_add": "设备池添加设备",
  "resource_pool.device_remove": "设备池移除设备",
  "resource_pool.project_add": "设备池授权项目",
  "resource_pool.project_remove": "设备池取消项目授权",
  "acl.grant": "授予共享权限",
  "acl.revoke": "撤销共享权限",
  "share.create": "创建共享链接",
  "share.revoke": "撤销共享链接",
  "ops.config.update": "更新运维配置",
  "ops.config.import": "导入运维配置",
  "auth.login": "登录",
  "auth.login_failed": "登录失败",
  "auth.logout": "登出",
  "auth.oidc_login": "OIDC 单点登录",
  "auth.saml_login": "SAML 单点登录",
  "auth.ide_handoff": "IDE 授权登录",
};

const RESOURCE_LABELS: Record<string, string> = {
  logical_case: "意图用例",
  requirement: "需求条目",
  knowledge: "知识库",
  document: "需求文档",
  project: "项目",
  job: "批跑任务",
  schedule: "定时计划",
  artifact: "工程制品",
  app_build: "应用资源",
  user: "用户",
  org: "组织",
  runner: "执行节点",
  device: "设备",
  device_remote_session: "远控会话",
  device_reservation: "设备占用",
  acl: "共享授权",
  share: "共享链接",
};

const STATUS_LABELS: Record<string, string> = {
  released: "已释放",
  closed: "已关闭",
  active: "进行中",
  reserved: "已占用",
  failed: "失败",
  succeeded: "成功",
  cancelled: "已取消",
};

const PLATFORM_LABELS: Record<string, string> = {
  android: "安卓",
  ios: "苹果",
  web: "Web",
  http: "接口",
};

const KV_RE = /(\w+)=([^;\s]+)/g;

function shortId(value: string, head = 8, tail = 4): string {
  const text = (value || "").trim();
  if (!text) return "";
  if (text.length <= head + tail + 1) return text;
  const suffix = tail > 0 ? text.slice(-tail) : "";
  return `${text.slice(0, head)}…${suffix}`;
}

function parseDetailKv(detail: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const m of detail.matchAll(KV_RE)) {
    out[m[1]] = m[2];
  }
  return out;
}

function formatClientHint(ua: string): string {
  const s = (ua || "").toLowerCase();
  if (!s) return "";
  if (s.includes("mozilla") || s.includes("chrome") || s.includes("safari") || s.includes("edge") || s.includes("firefox")) {
    return "浏览器";
  }
  if (s.includes("python") || s.includes("curl") || s.includes("httpx")) {
    return "脚本/API 客户端";
  }
  return "客户端";
}

export function auditActionLabel(action: string, fallback?: string): string {
  const key = (action || "").trim();
  if (ACTION_LABELS[key]) return ACTION_LABELS[key];
  if (key.startsWith("device.remote_command.")) return "远控设备指令";
  if (key.startsWith("device.remote_session.")) return "设备远程调试";
  if (fallback && fallback !== key && !fallback.startsWith("design.")) return fallback;
  if (key.startsWith("design.")) {
    return key.replace(/^design\./, "").replace(/\./g, " · ").replace(/_/g, " ");
  }
  return key.replace(/\./g, " · ").replace(/_/g, " ") || "操作";
}

export function auditResourceLabel(resourceType: string): string {
  const rt = (resourceType || "").trim();
  return RESOURCE_LABELS[rt] || rt || "资源";
}

export function formatAuditTime(iso?: string | null, display?: string): string {
  if (display && !display.includes("T")) return display;
  const raw = (iso || display || "").trim();
  if (!raw) return "—";
  try {
    const d = new Date(parseApiTime(raw));
    if (Number.isNaN(d.getTime())) return raw.slice(0, 19).replace("T", " ");
    const now = Date.now();
    const diff = now - d.getTime();
    if (diff < 60_000) return "刚刚";
    if (diff < 3_600_000) return `${Math.floor(diff / 60_000)} 分钟前`;
    if (diff < 86_400_000) {
      return d.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
    }
    if (diff < 604_800_000) return `${Math.floor(diff / 86_400_000)} 天前`;
    return d.toLocaleString("zh-CN", {
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return raw.slice(0, 19).replace("T", " ");
  }
}

export function formatAuditDetail(
  action: string,
  detail: string,
  resourceType?: string,
  resourceId?: string,
): string {
  const raw = (detail || "").trim();
  const act = (action || "").trim();
  if (raw && raw !== act) {
    if (raw === "password") return "账号密码登录";
    if (raw === "oidc") return "企业 OIDC 登录";
    if (raw === "saml") return "企业 SAML 登录";

    const kv = parseDetailKv(raw);
    if (kv.ip || kv.ua) {
      const parts: string[] = [];
      if (kv.ip) parts.push(`来源 IP ${kv.ip}`);
      if (kv.ua) parts.push(formatClientHint(kv.ua));
      return parts.join(" · ");
    }
    if (kv.count) {
      return act.includes("generate") ? `生成 ${kv.count} 条用例` : `共 ${kv.count} 条`;
    }
    if (kv.deleted || kv.failed) {
      const parts: string[] = [];
      if (kv.deleted) parts.push(`删除 ${kv.deleted} 条`);
      if (kv.failed && kv.failed !== "0") parts.push(`失败 ${kv.failed} 条`);
      if (parts.length) return parts.join(" · ");
    }
    if (kv.udid || kv.platform) {
      const parts: string[] = [];
      if (kv.platform) parts.push(PLATFORM_LABELS[kv.platform.toLowerCase()] || kv.platform);
      if (kv.udid) parts.push(`设备编号 ${kv.udid}`);
      if (kv.status) parts.push(STATUS_LABELS[kv.status.toLowerCase()] || kv.status);
      return parts.join(" · ");
    }
    if (kv.reservation_id || (kv.status && (kv.device_id || act.startsWith("device.")))) {
      const parts: string[] = [];
      if (kv.status) parts.push(STATUS_LABELS[kv.status.toLowerCase()] || kv.status);
      if (kv.reason) parts.push(`用途：${kv.reason.replace(/^\[|\]$/g, "")}`);
      if (kv.reservation_id) parts.push(`占用单 ${shortId(kv.reservation_id, 8, 0)}`);
      if (parts.length) return parts.join(" · ");
    }
    if (kv.request_id && Object.keys(kv).length === 1) {
      return `指令编号 ${shortId(kv.request_id, 8, 0)}`;
    }
    if (kv.project && kv.artifact) {
      return `项目 ${kv.project} · 制品 ${shortId(kv.artifact)}`;
    }
    if (kv.project) return `项目 ${kv.project}`;
    if (raw.length <= 120 && !raw.startsWith("design.")) return raw;
  }
  const rt = (resourceType || "").trim();
  const rid = (resourceId || "").trim();
  if (rid) return `${auditResourceLabel(rt)} ${shortId(rid)}`;
  return raw || "—";
}

export function formatAuditRow(row: AuditLog): {
  time: string;
  actionLabel: string;
  detailSummary: string;
  resourceSummary: string;
} {
  const action = row.action || "";
  const rt = row.resource_type || "";
  const rid = row.resource_id || "";
  return {
    time: formatAuditTime(row.created_at),
    actionLabel: auditActionLabel(action),
    detailSummary: formatAuditDetail(action, row.detail || "", rt, rid),
    resourceSummary: rid ? `${auditResourceLabel(rt)} ${shortId(rid)}` : "—",
  };
}

/** @deprecated 使用 auditActionLabel */
export const designActivityLabel = auditActionLabel;

/** @deprecated 使用 formatAuditTime */
export const formatActivityTime = formatAuditTime;
