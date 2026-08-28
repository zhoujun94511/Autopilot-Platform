/** 运维统一配置中心 API（含 AI / RAG / 生成等全部 EDITABLE_KEYS） */

import { api } from "../api";

export type ConfigCategory = {
  id: string;
  title: string;
  description?: string;
  keys: string[];
};

export type OpsConfigResponse = {
  editable_keys: string[];
  ops_editable_keys?: string[];
  design_editable_keys?: string[];
  secret_keys: string[];
  secret_mask?: string;
  secret_configured?: Record<string, boolean>;
  values: Record<string, string>;
  sources: Record<string, string>;
  categories: ConfigCategory[];
  design_ai_summary?: {
    provider?: string;
    model?: string;
    base_url?: string;
    embedding_model?: string;
    rag_embedder?: string;
    api_key_configured?: boolean;
  };
  note?: string;
};

/** 与后端 ai_config.AI_PROVIDERS 对齐的 Provider 目录 */
export type AiProviderInfo = {
  id: string;
  label: string;
  default_base_url: string;
  default_model: string;
  models: string[];
};

export type AiProvidersResponse = {
  providers: AiProviderInfo[];
};

/** 分类内分组卡片（UI 层级，不改变后端 keys） */
export type ConfigFieldGroup = {
  id: string;
  title: string;
  subtitle?: string;
  keys: string[];
  danger?: boolean;
  /** 默认折叠（渐进披露） */
  collapsed?: boolean;
};

/** 前端任务向导航（可合成多后端分类） */
export type ConfigNavItem = {
  id: string;
  title: string;
  description: string;
  /** 对应后端 category id；合成项可多个 */
  backendIds: string[];
  overview?: boolean;
};

export const CONFIG_NAV_ITEMS: ConfigNavItem[] = [
  {
    id: "overview",
    title: "配置健康",
    description: "Key / 模型 / 检索 / 回调是否就绪",
    backendIds: ["overview"],
    overview: true,
  },
  {
    id: "ai_model",
    title: "AI 接入",
    description: "提供商、密钥与默认模型",
    backendIds: ["ai_model"],
  },
  {
    id: "vector_rag",
    title: "知识检索",
    description: "检索参数（语料在知识库管理）",
    backendIds: ["vector_rag"],
  },
  {
    id: "case_generation",
    title: "用例生成",
    description: "生成数量、去重与实验动作",
    backendIds: ["case_generation"],
  },
  {
    id: "webhook_alert",
    title: "通知与回调",
    description: "任务回调、设计事件与告警",
    backendIds: ["webhook_alert"],
  },
  {
    id: "platform_policy",
    title: "平台策略",
    description: "保留策略、调度约束与 Metrics",
    backendIds: ["storage", "devices_artifacts"],
  },
  {
    id: "performance",
    title: "性能与高级",
    description: "一般无需改：并发、流式、上传上限",
    backendIds: ["performance"],
  },
];

export const CATEGORY_FIELD_GROUPS: Record<string, ConfigFieldGroup[]> = {
  ai_model: [
    {
      id: "provider",
      title: "模型接入",
      subtitle: "选择提供商与默认模型；密钥留空表示保持已有配置",
      keys: [
        "AP_AI_PROVIDER",
        "AP_AI_API_KEY",
        "AP_AI_BASE_URL",
        "AP_AI_MODEL",
        "AP_AI_PLANNING_MODEL",
        "AP_AI_LOCATE_MODEL",
      ],
    },
    {
      id: "inference",
      title: "推理参数",
      subtitle: "超时、Token、温度与重试",
      keys: [
        "AP_AI_TIMEOUT_SEC",
        "AP_AI_MAX_TOKENS",
        "AP_AI_CODEGEN_MAX_TOKENS",
        "AP_AI_TEMPERATURE",
        "AP_AI_CHAT_MAX_ATTEMPTS",
        "AP_AI_CODEGEN_MAX_ATTEMPTS",
      ],
      collapsed: true,
    },
    {
      id: "deepseek",
      title: "DeepSeek 扩展",
      subtitle: "仅在提供商为 DeepSeek 时生效",
      keys: ["AP_AI_DEEPSEEK_THINKING", "AP_AI_DEEPSEEK_REASONING_EFFORT"],
      collapsed: true,
    },
    {
      id: "token_budget",
      title: "Token 预算",
      subtitle: "按全局 / 项目 / 组织设置日预算；开启硬拦截后超限不再调用厂商",
      keys: [
        "AP_AI_DAILY_TOKEN_BUDGET",
        "AP_AI_PROJECT_DAILY_TOKEN_BUDGET",
        "AP_AI_ORG_DAILY_TOKEN_BUDGET",
        "AP_AI_ENFORCE_TOKEN_BUDGET",
      ],
      collapsed: true,
    },
  ],
  vector_rag: [
    {
      id: "embed",
      title: "嵌入与检索",
      subtitle: "语料在设计域「知识库」维护；此处只调检索与嵌入参数",
      keys: [
        "AP_AI_EMBEDDING_MODEL",
        "AP_RAG_EMBEDDER",
        "AP_RAG_TOP_K",
        "AP_RAG_SCORE_THRESHOLD",
        "AP_RAG_HYBRID",
        "AP_RAG_FTS_FACTOR",
        "AP_RAG_FTS_MAX_CANDIDATES",
        "AP_ENABLE_CASE_GENERATION_RAG",
      ],
    },
  ],
  case_generation: [
    {
      id: "gen",
      title: "生成与去重",
      subtitle: "最大用例数与生成后内容去重",
      keys: [
        "AP_MAX_CASE_NUM",
        "AP_CONTENT_SIMILARITY_THRESHOLD",
        "AP_ENABLE_CONTENT_DEDUP",
        "AP_CONTENT_DEDUP_BATCH_SIZE",
      ],
    },
    {
      id: "experimental",
      title: "实验能力",
      subtitle: "开启后 Chat 可执行实验动作，请谨慎",
      keys: ["AP_ENABLE_EXPERIMENTAL_ACTIONS"],
      danger: true,
    },
  ],
  performance: [
    {
      id: "perf",
      title: "并发与流式",
      subtitle: "文档分块、批量并发生成、Chat 流式与上传体积上限",
      keys: [
        "AP_CHUNK_SIZE",
        "AP_MAX_WORKERS",
        "AP_ENABLE_PARALLEL_PROCESSING",
        "AP_ENABLE_STREAMING",
        "AP_MAX_MEMORY_MB",
      ],
    },
  ],
  webhook_alert: [
    {
      id: "job_webhook",
      title: "任务回调",
      subtitle: "批跑完成等事件回调到外部系统",
      keys: ["MC_WEBHOOK_URL", "MC_WEBHOOK_SECRET"],
    },
    {
      id: "design_webhook",
      title: "设计域回调",
      subtitle: "逻辑用例审批等设计事件",
      keys: ["MC_DESIGN_WEBHOOK_URL", "MC_DESIGN_WEBHOOK_USE_JOB_URL", "MC_WEBHOOK_ALLOW_LOOPBACK"],
    },
    {
      id: "alert",
      title: "告警通道",
      subtitle: "失败、卡住、节点离线或没有可用设备时通知；密钥不想改就留空",
      keys: [
        "MC_ALERT_WEBHOOK_URL",
        "MC_ALERT_CHANNEL",
        "MC_ALERT_SECRET",
        "MC_ALERT_ON_FAILED",
        "MC_ALERT_ON_STALE",
        "MC_ALERT_ON_RUNNER_OFFLINE",
        "MC_ALERT_RUNNER_OFFLINE_COOLDOWN_SEC",
        "MC_ALERT_ON_DEVICE_EMPTY",
      ],
      danger: true,
    },
  ],
  storage: [
    {
      id: "retention",
      title: "保留与容量",
      keys: [
        "MC_JOB_STALE_SEC",
        "MC_ARTIFACT_RETENTION_DAYS",
        "MC_APP_BUILD_RETENTION_DAYS",
        "MC_APP_BUILD_MAX_MB",
        "MC_APP_BUILD_MAX_COUNT",
        "MC_APP_BUILD_MAX_TOTAL_MB",
      ],
    },
  ],
  devices_artifacts: [
    {
      id: "policy",
      title: "调度与校验策略",
      keys: [
        "MC_REQUIRE_JOB_DEVICES",
        "MC_REQUIRE_ARTIFACT_MANIFEST",
        "MC_ENFORCE_RUNTIME_VERSION",
        "MC_METRICS_ENABLED",
      ],
    },
  ],
};

export const CONFIG_KEY_LABELS: Record<string, string> = {
  AP_AI_PROVIDER: "AI 提供商",
  AP_AI_API_KEY: "API 密钥",
  AP_AI_BASE_URL: "API 基础 URL",
  AP_AI_MODEL: "模型名称",
  AP_AI_PLANNING_MODEL: "规划模型（AI 编写）",
  AP_AI_LOCATE_MODEL: "定位模型（深度定位）",
  AP_AI_TIMEOUT_SEC: "请求超时（秒）",
  AP_AI_MAX_TOKENS: "最大 Token 数",
  AP_AI_CODEGEN_MAX_TOKENS: "AI 编写单次最大输出 Token",
  AP_AI_TEMPERATURE: "采样温度",
  AP_AI_DEEPSEEK_THINKING: "DeepSeek 思考模式",
  AP_AI_DEEPSEEK_REASONING_EFFORT: "DeepSeek 推理强度",
  AP_AI_CHAT_MAX_ATTEMPTS: "对话最大重试次数",
  AP_AI_CODEGEN_MAX_ATTEMPTS: "AI 编写最大尝试次数",
  AP_AI_DAILY_TOKEN_BUDGET: "全局每日 Token 预算",
  AP_AI_PROJECT_DAILY_TOKEN_BUDGET: "单项目每日 Token 预算",
  AP_AI_ORG_DAILY_TOKEN_BUDGET: "单组织每日 Token 预算",
  AP_AI_ENFORCE_TOKEN_BUDGET: "超预算硬拦截",
  AP_AI_EMBEDDING_MODEL: "嵌入模型",
  AP_RAG_EMBEDDER: "RAG 嵌入器",
  AP_RAG_TOP_K: "召回条数 Top-K",
  AP_RAG_SCORE_THRESHOLD: "相似度阈值",
  AP_RAG_HYBRID: "启用 FTS5 混合检索",
  AP_RAG_FTS_FACTOR: "FTS 候选倍数",
  AP_RAG_FTS_MAX_CANDIDATES: "FTS 候选上限",
  AP_ENABLE_CASE_GENERATION_RAG: "用例生成启用知识检索",
  AP_MAX_CASE_NUM: "单次最大用例数",
  AP_CONTENT_SIMILARITY_THRESHOLD: "内容去重相似度阈值",
  AP_ENABLE_CONTENT_DEDUP: "启用内容去重",
  AP_CONTENT_DEDUP_BATCH_SIZE: "去重对照库条数上限",
  AP_CHUNK_SIZE: "文档分块大小（字符）",
  AP_MAX_WORKERS: "批量并发生成最大线程数",
  AP_ENABLE_PARALLEL_PROCESSING: "启用批量并发生成",
  AP_ENABLE_STREAMING: "启用 Chat 流式输出",
  AP_MAX_MEMORY_MB: "设计文档上传上限 (MB)",
  AP_ENABLE_EXPERIMENTAL_ACTIONS: "启用 Chat 实验动作",
  MC_WEBHOOK_URL: "任务完成后通知地址",
  MC_WEBHOOK_SECRET: "任务通知密钥",
  MC_DESIGN_WEBHOOK_URL: "审核通过后通知地址",
  MC_DESIGN_WEBHOOK_USE_JOB_URL: "设计事件复用任务通知地址",
  MC_WEBHOOK_ALLOW_LOOPBACK: "允许通知到本机（联调）",
  MC_ALERT_WEBHOOK_URL: "告警通知地址",
  MC_ALERT_CHANNEL: "告警渠道",
  MC_ALERT_SECRET: "告警密钥",
  MC_ALERT_ON_FAILED: "任务失败告警",
  MC_ALERT_ON_STALE: "卡住任务告警",
  MC_ALERT_ON_RUNNER_OFFLINE: "执行节点离线告警",
  MC_ALERT_RUNNER_OFFLINE_COOLDOWN_SEC: "离线告警冷却（秒）",
  MC_ALERT_ON_DEVICE_EMPTY: "没有可用设备时告警",
  MC_JOB_STALE_SEC: "任务卡住超时（秒）",
  MC_ARTIFACT_RETENTION_DAYS: "工程制品保留（天）",
  MC_APP_BUILD_RETENTION_DAYS: "应用资源保留（天）",
  MC_APP_BUILD_MAX_MB: "单包上限（MB，0=不限）",
  MC_APP_BUILD_MAX_COUNT: "单项目条数上限（0=不限）",
  MC_APP_BUILD_MAX_TOTAL_MB: "单项目容量上限（MB，0=不限）",
  MC_METRICS_ENABLED: "内部 Metrics 收集",
  MC_REQUIRE_JOB_DEVICES: "批跑必须指定设备",
  MC_REQUIRE_ARTIFACT_MANIFEST: "正式制品要求 Manifest",
  MC_ENFORCE_RUNTIME_VERSION: "强制 Runner 运行时版本匹配",
};

export const CONFIG_KEY_HELPERS: Record<string, string> = {
  AP_AI_API_KEY: "已配置时显示为掩码；留空保存表示不修改",
  AP_AI_BASE_URL: "切换提供商时若仍是目录默认会自动填充；自定义 URL 不会被覆盖",
  AP_AI_MODEL: "可从推荐列表选择，也可直接输入自定义模型名",
  AP_AI_PLANNING_MODEL: "可选；留空则用默认模型。用于编写规划 / NL 抽槽",
  AP_AI_LOCATE_MODEL: "可选；留空则用规划模型或默认模型。仅深度定位二次调用",
  AP_RAG_EMBEDDER: "有密钥时用远程嵌入，否则本机离线计算",
  MC_WEBHOOK_SECRET: "已配置则留空保持；填写则覆盖",
  MC_DESIGN_WEBHOOK_URL:
    "设计事件回调地址；本机联调示例 http://127.0.0.1:8765/hooks/intent",
  MC_WEBHOOK_ALLOW_LOOPBACK:
    "开启后允许回调到本机地址（仅联调；默认关闭）",
  MC_ALERT_SECRET: "已配置则留空保持；填写则覆盖",
  MC_ALERT_ON_RUNNER_OFFLINE: "节点心跳由在线变为离线时推送（需告警 URL）",
  MC_ALERT_RUNNER_OFFLINE_COOLDOWN_SEC: "同一 Runner / 设备池事件的最短间隔，默认 3600",
  MC_ALERT_ON_DEVICE_EMPTY: "仍有在线 Runner 但在线设备数变为 0 时推送",
  MC_DESIGN_WEBHOOK_USE_JOB_URL: "开启后设计事件可回落到任务回调 URL",
  MC_METRICS_ENABLED: "关闭后 /metrics 不再暴露进程内计数",
  MC_ENFORCE_RUNTIME_VERSION: "开启后拒收运行时版本不匹配的 Runner 上报",
  AP_ENABLE_EXPERIMENTAL_ACTIONS: "仅建议在受控环境开启",
  AP_ENABLE_CONTENT_DEDUP: "生成落库前按标题+步骤相似度过滤重复草稿",
  AP_CONTENT_SIMILARITY_THRESHOLD: "0~1，越高越严格",
  AP_CONTENT_DEDUP_BATCH_SIZE: "与最近 N 条已有用例比对",
  AP_CHUNK_SIZE: "文档启发式分析时单块最大字符数",
  AP_ENABLE_PARALLEL_PROCESSING: "批量生成选「并行」时生效",
  AP_MAX_WORKERS: "并发生成线程上限",
  AP_ENABLE_STREAMING: "关闭后 Chat 改为整段生成再推送",
  AP_MAX_MEMORY_MB: "超过该体积的设计文档上传会被拒绝",
};

export type FieldKind = "text" | "password" | "number" | "select" | "toggle" | "model_combo";

export function fieldKind(key: string, secretKeys: string[]): FieldKind {
  if (secretKeys.includes(key) || key.endsWith("_SECRET") || key.endsWith("_API_KEY")) {
    return "password";
  }
  if (key === "AP_AI_PROVIDER") return "select";
  if (key === "AP_AI_MODEL" || key === "AP_AI_PLANNING_MODEL" || key === "AP_AI_LOCATE_MODEL") {
    return "model_combo";
  }
  if (key === "AP_RAG_EMBEDDER") return "select";
  if (key === "MC_ALERT_CHANNEL") return "select";
  if (key === "AP_AI_DEEPSEEK_REASONING_EFFORT") return "select";
  if (
    key.startsWith("AP_ENABLE_") ||
    key === "AP_RAG_HYBRID" ||
    key.endsWith("_THINKING") ||
    key.startsWith("MC_ALERT_ON_") ||
    key.startsWith("MC_REQUIRE_") ||
    key.startsWith("MC_ENFORCE_") ||
    key === "MC_METRICS_ENABLED" ||
    key === "MC_DESIGN_WEBHOOK_USE_JOB_URL"
  ) {
    return "toggle";
  }
  if (
    key.includes("TEMPERATURE") ||
    key.includes("THRESHOLD") ||
    key.includes("CASE_NUM") ||
    key.includes("BATCH_SIZE") ||
    key.includes("CHUNK_SIZE") ||
    key.includes("WORKERS") ||
    key.includes("MEMORY") ||
    key.includes("TIMEOUT") ||
    key.includes("TOKENS") ||
    key.includes("TOP_K") ||
    key.includes("FTS_FACTOR") ||
    key.includes("FTS_MAX_CANDIDATES") ||
    key.includes("ATTEMPTS") ||
    key.includes("_SEC") ||
    key.includes("_DAYS") ||
    key.includes("_MB") ||
    key.includes("_COUNT")
  ) {
    return "number";
  }
  return "text";
}

/** 前端兜底（API 未返回时）；正式数据来自 GET /ops/config/ai-providers */
export const FALLBACK_AI_PROVIDERS: AiProviderInfo[] = [
  {
    id: "openai",
    label: "OpenAI",
    default_base_url: "https://api.openai.com/v1",
    default_model: "gpt-4o-mini",
    models: ["gpt-4o-mini", "gpt-4o", "gpt-4.1-mini", "gpt-4.1"],
  },
  {
    id: "deepseek",
    label: "DeepSeek",
    default_base_url: "https://api.deepseek.com",
    default_model: "deepseek-v4-flash",
    models: [
      "deepseek-v4-flash",
      "deepseek-v4-pro",
      "deepseek-v4-flash-vision-exp",
      "deepseek-chat",
      "deepseek-reasoner",
    ],
  },
  {
    id: "qwen",
    label: "通义千问 (Qwen)",
    default_base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    default_model: "qwen-plus",
    models: ["qwen-flash", "qwen-plus", "qwen-max"],
  },
  {
    id: "gemini",
    label: "Gemini",
    default_base_url: "https://generativelanguage.googleapis.com/v1beta/openai",
    default_model: "gemini-3.1-flash-lite",
    models: [
      "gemini-3.1-flash-lite",
      "gemini-2.0-flash",
      "gemini-2.5-flash",
      "gemini-1.5-pro",
      "gemini-1.5-flash",
    ],
  },
  {
    id: "ollama",
    label: "Ollama（本地）",
    default_base_url: "http://127.0.0.1:11434/v1",
    default_model: "llama3.2",
    models: ["llama3.2", "phi:2.7b", "gemma:2b"],
  },
];

export function fieldOptions(
  key: string,
  providers: AiProviderInfo[] = FALLBACK_AI_PROVIDERS,
): { value: string; label: string }[] {
  if (key === "AP_AI_PROVIDER") {
    const list = providers.length ? providers : FALLBACK_AI_PROVIDERS;
    return list.map((p) => ({ value: p.id, label: p.label }));
  }
  if (key === "AP_RAG_EMBEDDER") {
    return [
      { value: "hashing", label: "本地 hashing（默认）" },
      { value: "openai", label: "OpenAI Embedding" },
      { value: "auto", label: "自动（有 Key 则外部）" },
    ];
  }
  if (key === "MC_ALERT_CHANNEL") {
    return [
      { value: "json", label: "JSON" },
      { value: "dingtalk", label: "钉钉" },
      { value: "feishu", label: "飞书" },
      { value: "slack", label: "Slack" },
    ];
  }
  if (key === "AP_AI_DEEPSEEK_REASONING_EFFORT") {
    return [
      { value: "", label: "默认" },
      { value: "low", label: "low" },
      { value: "medium", label: "medium" },
      { value: "high", label: "high" },
      { value: "max", label: "max" },
    ];
  }
  return [];
}

export function findAiProvider(
  providers: AiProviderInfo[],
  id: string,
): AiProviderInfo | undefined {
  const pid = (id || "").trim().toLowerCase();
  return providers.find((p) => p.id === pid);
}

/** 是否仍为某 Provider 的「目录默认」URL（可被切换覆盖） */
export function isCatalogDefaultBaseUrl(
  url: string,
  providers: AiProviderInfo[],
  previousProviderId?: string,
): boolean {
  const cur = (url || "").trim().replace(/\/+$/, "");
  if (!cur) return true;
  if (previousProviderId) {
    const prev = findAiProvider(providers, previousProviderId);
    if (prev && prev.default_base_url.replace(/\/+$/, "") === cur) return true;
  }
  return providers.some((p) => p.default_base_url.replace(/\/+$/, "") === cur);
}

/** 是否仍为旧 Provider 默认模型（可被切换覆盖） */
export function isReplaceableAiModel(
  model: string,
  providers: AiProviderInfo[],
  previousProviderId?: string,
): boolean {
  const cur = (model || "").trim();
  if (!cur) return true;
  if (previousProviderId) {
    const prev = findAiProvider(providers, previousProviderId);
    if (prev && prev.default_model === cur) return true;
  }
  return providers.some((p) => p.default_model === cur);
}

export async function getOpsConfig(): Promise<OpsConfigResponse> {
  return await api<OpsConfigResponse>("/api/v1/ops/config");
}

export async function getAiProviders(): Promise<AiProvidersResponse> {
  return await api<AiProvidersResponse>("/api/v1/ops/config/ai-providers");
}

export async function saveOpsConfig(values: Record<string, string>): Promise<OpsConfigResponse> {
  return await api<OpsConfigResponse>("/api/v1/ops/config", {
    method: "PUT",
    body: JSON.stringify({ values }),
  });
}

export async function exportOpsConfig(): Promise<OpsConfigResponse & { format?: string; version?: number }> {
  return await api("/api/v1/ops/config/export");
}

export async function importOpsConfig(payload: {
  values?: Record<string, string>;
  [k: string]: unknown;
}): Promise<OpsConfigResponse> {
  return await api<OpsConfigResponse>("/api/v1/ops/config/import", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
