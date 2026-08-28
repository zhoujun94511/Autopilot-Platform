/** 审计 / 设计域活动可读化（与后端 design_activity 对齐）。 */

import type { AuditLog } from "../api";

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
  "org.create": "创建组织",
  "org.update": "更新组织",
  "job.create": "创建批跑任务",
  "job.cancel": "取消任务",
  "job.retry": "重试任务",
  "artifact.upload": "上传制品",
  "artifact.delete": "删除制品",
  "runner.register": "注册 Runner",
  "runner.update": "更新 Runner",
  "auth.login": "登录",
  "auth.login_failed": "登录失败",
  "auth.logout": "登出",
};

const RESOURCE_LABELS: Record<string, string> = {
  logical_case: "用例",
  requirement: "需求",
  knowledge: "知识",
  document: "文档",
  project: "项目",
  job: "任务",
  artifact: "制品",
  user: "用户",
  org: "组织",
  runner: "Runner",
};

const KV_RE = /(\w+)=([^\s]+)/g;

function shortId(value: string, head = 8, tail = 4): string {
  const text = (value || "").trim();
  if (!text) return "";
  if (text.length <= head + tail + 1) return text;
  return `${text.slice(0, head)}…${text.slice(-tail)}`;
}

function parseDetailKv(detail: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const m of detail.matchAll(KV_RE)) {
    out[m[1]] = m[2];
  }
  return out;
}

export function auditActionLabel(action: string, fallback?: string): string {
  const key = (action || "").trim();
  if (ACTION_LABELS[key]) return ACTION_LABELS[key];
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
    const d = new Date(raw);
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
    const kv = parseDetailKv(raw);
    if (kv.count) {
      return act.includes("generate") ? `生成 ${kv.count} 条用例` : `共 ${kv.count} 条`;
    }
    if (kv.deleted || kv.failed) {
      const parts: string[] = [];
      if (kv.deleted) parts.push(`删除 ${kv.deleted} 条`);
      if (kv.failed && kv.failed !== "0") parts.push(`失败 ${kv.failed} 条`);
      if (parts.length) return parts.join(" · ");
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
