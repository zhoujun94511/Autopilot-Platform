/** Ops 概览健康行（AUD-2026-12 Wave 4）。 */

export type OpsHealthNavAction = "ai_model" | "vector_rag" | "webhook_alert";

export type OpsHealthRow = {
  id: string;
  label: string;
  ok: boolean;
  value: string;
  detail?: string;
  action: OpsHealthNavAction;
  actionLabel: string;
  emphasize: boolean;
};

export type OpsHealthInput = {
  apiKeyConfigured: boolean;
  webhookConfigured: boolean;
  provider: string;
  model: string;
  embedder: string;
  ragOk: number;
  ragFail: number;
  ragLastError?: string | null;
};

export function buildOpsHealthRows(input: OpsHealthInput): OpsHealthRow[] {
  const provider = input.provider || "—";
  const model = input.model || "—";
  const embedder = input.embedder || "—";
  const ragFail = Number(input.ragFail || 0);
  const ragOk = Number(input.ragOk || 0);
  const lastError = String(input.ragLastError || "").trim();

  return [
    {
      id: "key",
      label: "API 密钥",
      ok: input.apiKeyConfigured,
      value: input.apiKeyConfigured ? "已配置" : "未配置",
      action: "ai_model",
      actionLabel: "配置 AI",
      emphasize: !input.apiKeyConfigured,
    },
    {
      id: "model",
      label: "当前模型",
      ok: Boolean(provider && provider !== "—" && model && model !== "—"),
      value: `${provider} / ${model}`,
      action: "ai_model",
      actionLabel: "编辑",
      emphasize: false,
    },
    {
      id: "rag",
      label: "知识检索",
      ok: !lastError,
      value: `${embedder} · 成功 ${ragOk} / 失败 ${ragFail}`,
      detail: lastError || "",
      action: "vector_rag",
      actionLabel: "调整参数",
      emphasize: Boolean(lastError),
    },
    {
      id: "webhook",
      label: "任务回调",
      ok: input.webhookConfigured,
      value: input.webhookConfigured ? "已配置 URL" : "未配置",
      action: "webhook_alert",
      actionLabel: "去配置",
      emphasize: false,
    },
  ];
}
