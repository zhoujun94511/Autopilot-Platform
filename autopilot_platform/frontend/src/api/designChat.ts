/** 设计域：AI 对话 API */

import { api, parseApiError, sessionFetch } from "../api";
import { downloadDesignBlob } from "./designDownload";
import {
  DEFAULT_PAGE_SIZE,
  normalizePagedResult,
  type PagedResult,
} from "../utils/pagination";

export type ChatSession = {
  id: string;
  project_id: string;
  title: string;
  created_by: string;
  created_at: string;
  updated_at: string;
  message_count?: number;
  preview?: string;
};

export type ChatMessage = {
  id: string;
  session_id: string;
  role: string;
  content: string;
  tokens_used?: number;
  model_name?: string;
  created_at: string;
};

export type ChatOptions = {
  provider: string;
  default_model: string;
  available_models: string[];
  default_temperature: number;
  default_max_tokens: number;
  key_configured: boolean;
  base_url: string;
  templates: Array<{ id: string; name: string; content: string }>;
};

export type ChatExportFormat = "json" | "txt" | "csv" | "xlsx";

export async function getChatOptions(): Promise<ChatOptions> {
  return await api<ChatOptions>("/api/v1/design/chat/options");
}

export async function listChatSuggestions(context?: string): Promise<string[]> {
  const q = context?.trim()
    ? `?context=${encodeURIComponent(context.trim())}`
    : "";
  const out = await api<{ suggestions?: string[] }>(`/api/v1/design/chat/suggestions${q}`);
  return Array.isArray(out?.suggestions) ? out.suggestions : [];
}

export async function listChatSessionsPage(
  projectId?: string,
  opts?: { page?: number; pageSize?: number },
): Promise<PagedResult<ChatSession>> {
  const page = opts?.page ?? 1;
  const pageSize = opts?.pageSize ?? DEFAULT_PAGE_SIZE;
  const q = new URLSearchParams();
  if (projectId?.trim()) q.set("project_id", projectId.trim());
  q.set("page", String(page));
  q.set("page_size", String(pageSize));
  const qs = q.toString() ? `?${q.toString()}` : "";
  const raw = await api<PagedResult<ChatSession>>(`/api/v1/design/chat/sessions${qs}`);
  return normalizePagedResult(raw, page, pageSize);
}

/** @deprecated 请用 listChatSessionsPage */
export async function listChatSessions(
  projectId?: string,
  opts?: { limit?: number; offset?: number },
): Promise<ChatSession[]> {
  const pageSize = opts?.limit ?? DEFAULT_PAGE_SIZE;
  const page = opts?.offset != null ? Math.floor(opts.offset / pageSize) + 1 : 1;
  return (await listChatSessionsPage(projectId, { page, pageSize })).items;
}

export const CHAT_SESSION_PAGE_SIZE = DEFAULT_PAGE_SIZE;

export async function createChatSession(body: {
  project_id?: string;
  title?: string;
}): Promise<ChatSession> {
  return await api<ChatSession>("/api/v1/design/chat/sessions", {
    method: "POST",
    body: JSON.stringify({ title: "新对话", ...body }),
  });
}

export async function renameChatSession(
  sessionId: string,
  title: string,
): Promise<ChatSession> {
  return await api<ChatSession>(`/api/v1/design/chat/sessions/${sessionId}`, {
    method: "PATCH",
    body: JSON.stringify({ title }),
  });
}

export async function clearChatSession(sessionId: string): Promise<{ cleared_messages?: number }> {
  return await api(`/api/v1/design/chat/sessions/${sessionId}/clear`, {
    method: "POST",
  });
}

export async function deleteChatSession(sessionId: string): Promise<void> {
  await api(`/api/v1/design/chat/sessions/${sessionId}`, { method: "DELETE" });
}

export async function listChatMessages(sessionId: string): Promise<ChatMessage[]> {
  return (
    (await api<ChatMessage[]>(`/api/v1/design/chat/sessions/${sessionId}/messages`)) ||
    []
  );
}

export type ChatSendBody = {
  session_id: string;
  message: string;
  use_knowledge?: boolean;
  temperature?: number;
  model?: string;
  max_tokens?: number;
  mode?: string;
  require_confirmation?: boolean;
};

export type ActionPlan = {
  intent?: string;
  tool_name?: string;
  risk_level?: string;
  args?: Record<string, unknown>;
  requires_confirmation?: boolean;
  reason?: string;
};

export type ExperimentalActionResult = {
  success?: boolean;
  status?: string;
  execution_id?: string;
  message?: string;
  plan?: ActionPlan;
  action_plan?: ActionPlan;
  tool_output?: unknown;
  error?: string;
};

export async function sendChatMessage(body: ChatSendBody): Promise<{
  success?: boolean;
  response?: string;
  assistant_message?: ChatMessage;
  user_message?: ChatMessage;
  model_name?: string;
  suggestions?: string[];
  status?: string;
  execution_id?: string;
  plan?: ActionPlan;
  action_plan?: ActionPlan;
  message?: string;
}> {
  return await api("/api/v1/design/chat/message", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function confirmExperimentalAction(body: {
  execution_id: string;
  metadata?: Record<string, unknown>;
}): Promise<ExperimentalActionResult> {
  return await api("/api/v1/design/experimental-actions/confirm", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function cancelExperimentalAction(body: {
  execution_id: string;
  reason?: string;
}): Promise<ExperimentalActionResult> {
  return await api("/api/v1/design/experimental-actions/cancel", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export type ChatStreamEvent = {
  type: "start" | "chunk" | "end" | "error" | "action";
  content?: string;
  full_response?: string;
  session_id?: string;
  model_name?: string;
  /** token=上游真流式；buffered=整段生成后再分块（降级） */
  stream_mode?: "token" | "buffered";
  suggestions?: string[];
  code?: string;
  message?: string;
  retryable?: boolean;
  detail?: string;
  status?: string;
  execution_id?: string;
  plan?: ActionPlan;
  action_plan?: ActionPlan;
};

async function consumeChatSse(
  res: Response,
  onEvent: (ev: ChatStreamEvent) => void,
): Promise<void> {
  if (!res.body) throw new Error("流式响应不可用");
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    const parts = buf.split("\n\n");
    buf = parts.pop() || "";
    for (const part of parts) {
      let eventName = "";
      for (const line of part.split("\n")) {
        if (line.startsWith("event:")) {
          eventName = line.slice(6).trim();
          continue;
        }
        if (!line.startsWith("data:")) continue;
        const raw = line.slice(5).trim();
        if (!raw) continue;
        try {
          const parsed = JSON.parse(raw) as ChatStreamEvent;
          if (eventName === "action" && !parsed.type) {
            parsed.type = "action";
          }
          onEvent(parsed);
        } catch {
          /* ignore malformed chunk */
        }
      }
    }
  }
}

/** SSE 流式发送；失败时抛出以便上层 fallback 到 sendChatMessage */
export async function streamChatMessage(
  body: ChatSendBody,
  onEvent: (ev: ChatStreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await sessionFetch("/api/v1/design/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok) throw await parseApiError(res);
  await consumeChatSse(res, onEvent);
}

export type EphemeralChatBody = {
  message: string;
  history?: Array<{ role: string; content: string }>;
  temperature?: number;
  model?: string;
  max_tokens?: number;
};

/** 无项目闲聊：不落设计域、不注入知识库 */
export async function sendEphemeralChat(body: EphemeralChatBody): Promise<{
  success?: boolean;
  ephemeral?: boolean;
  response?: string;
  model_name?: string;
  suggestions?: string[];
}> {
  return await api("/api/v1/ops/ai/chat", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function streamEphemeralChat(
  body: EphemeralChatBody,
  onEvent: (ev: ChatStreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await sessionFetch("/api/v1/ops/ai/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok) throw await parseApiError(res);
  await consumeChatSse(res, onEvent);
}

export async function exportChatSession(
  sessionId: string,
  format: ChatExportFormat = "json",
): Promise<void> {
  const ext = format === "xlsx" ? "xlsx" : format;
  await downloadDesignBlob(
    `/api/v1/design/chat/sessions/${encodeURIComponent(sessionId)}/export?format=${encodeURIComponent(format)}`,
    { filename: `chat_${sessionId.slice(0, 8)}.${ext}` },
  );
}

/** 将后端/网络错误整理成可读文案 */
export function formatChatError(err: unknown): { text: string; retryable: boolean } {
  const msg =
    err && typeof err === "object" && "message" in err
      ? String((err as { message?: string }).message || "")
      : String(err || "");
  const low = msg.toLowerCase();
  if (/api key|未配置|密钥/.test(msg) || low.includes("api key")) {
    return {
      text: "AI 尚未开通。请到「运维」填写模型密钥后重试。",
      retryable: false,
    };
  }
  if (/401|unauthorized|鉴权/.test(low + msg)) {
    return { text: "模型鉴权失败，请检查运维中的密钥配置。", retryable: false };
  }
  if (/429|限流|rate limit/.test(low + msg)) {
    return { text: "上游限流，请稍后重试。", retryable: true };
  }
  if (/timeout|超时/.test(low + msg)) {
    return { text: "上游请求超时，可重试。", retryable: true };
  }
  if (/network|连接|connect/.test(low + msg)) {
    return { text: "无法连接上游服务，请检查网络或 Base URL 后重试。", retryable: true };
  }
  return { text: msg || "对话失败", retryable: true };
}
