/** DesignChat 消息展示辅助（AUD-2026-12 Wave 2）。 */

import { renderChatMarkdown } from "./chatMarkdown";

export function formatChatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString("zh-CN", {
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

export function chatRoleLabel(role: string): string {
  if (role === "assistant") return "助手";
  if (role === "system") return "系统";
  return "我";
}

function escapePlain(s: string): string {
  return String(s || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\n/g, "<br>");
}

export function renderChatBody(content: string, role: string): string {
  if (role === "user") {
    return (
      renderChatMarkdown(content).replace(/<\/?p>/g, (t) =>
        t.startsWith("</") ? "<br>" : "",
      ) || escapePlain(content)
    );
  }
  return renderChatMarkdown(content) || escapePlain(content);
}
