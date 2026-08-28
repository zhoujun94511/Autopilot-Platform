# AI Provider Profile（多厂商模型适配）

> 实现：`autopilot_platform/platform/ai/provider_profile.py`  
> 接入：`ai_client._build_chat_body`、运维配置中心、IDE `autopilot/intent/provider_profile.py`

## 原则

- **不引入 LangChain**：继续 OpenAI 兼容 Chat Completions + 薄 Profile。
- **统一推理档位** `AP_AI_REASONING_EFFORT`：`none|minimal|low|medium|high|max`。
- **verbosity** `AP_AI_VERBOSITY`：`none|low|medium|high`（仅 OpenAI gpt-5；`none`=不传）。
- **temperature** `AP_AI_TEMPERATURE`：默认 `0.2`；gpt-5 / Gemini 3·2.5 / DeepSeek thinking 时省略。
- **不静默改模型名**：旧模型只打弃用日志。
- **Gemini**：OpenAI 兼容网关下 `reasoning_effort` **原样传递**（勿把 `low` 改写成 `minimal`）。见 [Gemini OpenAI compatibility](https://ai.google.dev/gemini-api/docs/openai)。

## 默认模型（目录）

| Provider | 默认 | 备注 |
|----------|------|------|
| openai | `gpt-5.4-mini` | 另含 `gpt-5.6-terra` / `gpt-5-mini`；4o 标 legacy |
| deepseek | `deepseek-v4-flash` | **无**像素多模态 |
| qwen | `qwen-plus` | 视觉用 `qwen-vl-plus` |
| gemini | `gemini-3.5-flash` | 2.5 临近退役 |
| ollama | `llama3.2` | 本地 |

## 档位映射（摘要）

| 档位 | DeepSeek | OpenAI (gpt-5*) | Qwen | Gemini（OpenAI 兼容） |
|------|----------|-----------------|------|----------------------|
| none | thinking disabled | 不传 | enable_thinking=false | 2.5→`none`；3.x 省略（不能全关） |
| minimal/low/medium/high | thinking + high | **原样** | enable_thinking + 近似 budget | **原样** |
| max | thinking + max | **原样 `max`** | 更大 budget | `high`（官表无 max） |

千问 `thinking_budget` 数值为工程近似（对齐 Gemini 兼容表量级），非 DashScope 固定枚举。

IDE Intent Vision：`AUTOPILOT_VISION_REASONING_EFFORT`（默认 `none`）、
`AUTOPILOT_VISION_TEMPERATURE`（默认 `0.1`）、`AUTOPILOT_VISION_VERBOSITY`（默认 `none`），
均可回退到对应 `AP_AI_*`；另有 `model_accepts_images`。
DeepSeek thinking 开启时请求体省略 `temperature`（官方无效）。
