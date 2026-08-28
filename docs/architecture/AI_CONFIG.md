# AI 配置（设计域用例生成）

通过环境变量 / 运维区启用 **OpenAI 兼容** Chat Completions。未配置 Key 时自动回退启发式草稿（`degraded=true`）。

设 `AP_AI_REJECT_DEGRADED=1` 时：LLM 失败或未配置 Key **不再**回落启发式，生成/分析返回 503 / 失败（默认 `0`，避免打断现网）。

## Provider 一览

运维配置中心可通过 `GET /api/v1/ops/config/ai-providers` 拉取目录（单一事实来源：`platform/ai_config.py` 的 `AI_PROVIDERS`）。切换 Provider 时前端会自动填充对应默认 Base URL / 模型（自定义值不会被覆盖）。

| `AP_AI_PROVIDER` | 默认 Base URL | 默认模型 | 分厂商 Key |
|---|---|---|---|
| `openai` | `https://api.openai.com/v1` | `gpt-4o-mini` | `OPENAI_API_KEY` |
| `deepseek` | `https://api.deepseek.com` | `deepseek-v4-flash` | `DEEPSEEK_API_KEY` |
| `gemini` | `https://generativelanguage.googleapis.com/v1beta/openai` | `gemini-3.1-flash-lite` | `GEMINI_API_KEY` |
| `qwen` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-plus` | `DASHSCOPE_API_KEY` |
| `ollama` | `http://127.0.0.1:11434/v1` | `llama3.2` | （本地一般无需） |

通用覆盖：`AP_AI_API_KEY` / `AP_AI_BASE_URL` / `AP_AI_MODEL`（优先于分厂商变量）。

**与 IDE Vision 的边界**：本文件的 Key 供 Platform 设计域 / `/ops/ai/codegen`。IDE Intent Vision 在企业锁定 `AUTOPILOT_PLATFORM_URL` 时默认不读本机 Key（`AUTOPILOT_VISION_ALLOW_LOCAL_KEY=1` 才放行）；勿把企业 Key 下发到用户 IDE。

链路 3 用途分模型（可选；运维「AI 接入」可配）：

| 变量 | 用途 | 回落 |
|------|------|------|
| `AP_AI_PLANNING_MODEL` | 编写规划 / NL 抽槽（`purpose=authoring\|planning`） | `AP_AI_MODEL` |
| `AP_AI_LOCATE_MODEL` | 深度定位二次调用（`purpose=locate`） | `AP_AI_PLANNING_MODEL` → `AP_AI_MODEL` |

`GET /ops/ai/capabilities` 返回 `model` / `planning_model` / `locate_model`（解析后生效值）。

## DeepSeek（[官方文档](https://api-docs.deepseek.com/zh-cn/)）

- 推荐模型：`deepseek-v4-flash`（快）/ `deepseek-v4-pro`（推理）
- 旧别名 `deepseek-chat` / `deepseek-reasoner` 将于 **2026/07/24** 弃用；**不会静默 remap**，仅打日志提示
  - 官方兼容：`chat` ≈ flash 非思考；`reasoner` ≈ flash 思考
- 官方 API 默认 `thinking=enabled`；本平台 flash 路径会**显式 `disabled`**，`v4-pro` / `AP_AI_DEEPSEEK_THINKING=1` 才开启
- `AP_AI_DEEPSEEK_REASONING_EFFORT=high|max`（`low`/`medium`→`high`，`xhigh`→`max`）
- 空 content / 5xx 自动退避重试（`AP_AI_CHAT_MAX_ATTEMPTS`，默认 3）
- DeepSeek 当前配置判定为**文本模型**：`GET /ops/ai/capabilities` 返回
  `accepts_images=false` / `image_policy=text_only_ui_tree`。链路 3 只发 UI 树，不会把截图
  交给 DeepSeek；能力预检本身不调用厂商、不消耗 token

```powershell
$env:AP_AI_PROVIDER="deepseek"
$env:DEEPSEEK_API_KEY="sk-xxx"
$env:DEEPSEEK_MODEL="deepseek-v4-flash"
python start_dev.py
```

## Gemini

走 **Google 官方 OpenAI 兼容端点**（与 TestPilot/Scenario_Engine 约定一致：不用原生 Generative Language SDK）。

```powershell
$env:AP_AI_PROVIDER="gemini"
$env:GEMINI_API_KEY="AIza..."
$env:GEMINI_MODEL="gemini-3.1-flash-lite"
python start_dev.py
```

若使用第三方兼容网关，设置 `GEMINI_BASE_URL` 或 `AP_AI_BASE_URL` 即可。

## 其它

| 变量 | 默认 | 说明 |
|---|---|---|
| `AP_AI_TIMEOUT_SEC` | `180` | 超时秒 |
| `AP_AI_MAX_TOKENS` | `4096` | 最大输出 |
| `AP_AI_CODEGEN_MAX_TOKENS` | 同 `AP_AI_MAX_TOKENS` | 链路 3 单次输出上限；留空跟随通用上限，仅需压成本时下调 |
| `AP_AI_TEMPERATURE` | `0.2` | 采样温度 |
| `AP_AI_CHAT_MAX_ATTEMPTS` | `3` | 空内容/5xx 重试 |
| `AP_AI_CODEGEN_MAX_ATTEMPTS` | `2` | 链路 3 最大尝试次数（上限 4），避免故障放大消耗 |
| `AP_AI_EMBEDDING_MODEL` | 按 provider | RAG embedding |
| `AP_RAG_EMBEDDER` | `auto` | `auto` / `hashing` / `openai` |
| `AP_AI_DAILY_TOKEN_BUDGET` | `0` | 日累计 total_tokens 预算；0=关闭 |
| `AP_AI_ENFORCE_TOKEN_BUDGET` | `0` | `1` 超预算阻断调用；默认仅打日志 |

用量落盘与设计域 `tokens` 汇总见 [TOKEN_BUDGET.md](./TOKEN_BUDGET.md)（与 IDE 文档同名）。

完整样例见仓库根 [`.env.example`](../../.env.example)。
