# Token / 上下文预算控制

> 审计 Canvas：`token-budget-audit.canvas.tsx`、`ai-token-burn-risks.canvas.tsx`  
> 修订：2026-08-07

## 目标

在**不引入完整计费系统**的前提下：

1. **继续**输入侧节流（压缩截图、截断 RAG、限制条数）  
2. **新增**解析厂商返回的 `usage`，落盘 + 日志 + 设计域 stats / Prometheus  
3. **可选**日累计软/硬预算（环境变量）  
4. **T7** 按项目 / 组织分账日配额（JSONL 字段 + 进程内累计）

**明确不做**：按用户账单、tiktoken 预估硬拦截、跨进程分布式配额存储。

---

## Plan → Todo

| ID | 项 | 状态 |
|----|-----|------|
| T1 | Platform `ai_usage`：extract / JSONL / 日汇总 | **done** |
| T2 | `ai_client` 记录 usage + `check_budget_before_call` | **done** |
| T3 | `design_stats.tokens` 接真实汇总 | **done** |
| T4 | Prometheus `mc_ai_*` 计数 | **done** |
| T5 | IDE Vision `intent/usage.py` 落盘+日志 | **done** |
| T6 | 文档（本文 + AI_CONFIG / .env.example） | **done** |
| T7 | 组织/项目级硬配额 / 分账 | **done（2026-07-30）** |
| T8 | 打爆风险专项：门禁 / 上限 / 全路径分账 | **done（2026-08-07）** |

---

## T8 打爆风险专项（2026-08-07）

| 风险 | 处置 |
|------|------|
| Runner / API Token 可调 `/ops/ai/chat*` | `assert_ai_gateway_caller`：AI 网关三个端点统一只允许 `kind=user`，Runner/运维令牌 403 |
| 超大 prompt 直转厂商 | `MAX_AI_PROMPT_CHARS=60000`（`api/ops.py`）超限 413；IDE 侧 `MAX_PROMPT_CHARS` 同值本地先拦 |
| 单请求塞入超长消息 / 超多需求 | `design_schemas`：`MAX_CHAT_MESSAGE_CHARS=20000`、`MAX_CHAT_HISTORY_ITEMS=40`、`MAX_BATCH_REQUIREMENTS=50` |
| 流式 / 闲聊 / 文档分析绕过分账 | `iter_sse_chunks`、`ephemeral_send`、`iter_ephemeral_sse`、`analyze_document` 外层统一 `set_ai_billing_scope`；无项目落合成桶 `__ephemeral__` / `__platform__` |
| Embedding 无预算、异常直接 500 | `OpenAIEmbedder`：调用前 `check_budget_before_call`，按响应 `usage` 记账（`source=embedding`），`MAX_EMBED_ITEMS=512`，`httpx.HTTPError` 转 `RuntimeError` 交给 RAG 降级 |
| 生产未配预算无人知晓 | `ai_usage.budget_config_warnings()`；启动体检写日志（生产 error），`/ops` 用量汇总含 `config_warnings` |
| IDE 重复触发整轮 AI 编写 | `AiAuthoringDialog._generating` 互斥 + `assert_llm_ready()` 先做登录/Key 预检 |
| Vision 按步触发无上限 | `AUTOPILOT_VISION_MAX_CALLS_PER_CASE=30`，`run_testcase` 每用例重置 |
| Authoring 多回合 prompt 线性膨胀 | `prompt.py`：历史仅保留最近 8 条，页面摘要截断到 24000 字符 |

---

## 配置

### Platform（设计 Chat / 生成）

| 变量 | 默认 | 说明 |
|------|------|------|
| `AP_AI_MAX_TOKENS` | 4096 | 单次**输出**上限 |
| `AP_AI_CODEGEN_MAX_TOKENS` | 同 `AP_AI_MAX_TOKENS` | 链路 3 单次输出上限；只在要压成本时下调（长用例调低会被截断） |
| `AP_AI_CODEGEN_MAX_ATTEMPTS` | 2 | 链路 3 最多尝试次数（含首次），上限 4 |
| `AP_AI_DAILY_TOKEN_BUDGET` | 0 | **全局**日累计 `total_tokens`；0=关闭 |
| `AP_AI_PROJECT_DAILY_TOKEN_BUDGET` | 0 | **按 project_id** 日累计；0=关闭 |
| `AP_AI_ORG_DAILY_TOKEN_BUDGET` | 0 | **按 org_id** 日累计；0=关闭 |
| `AP_AI_ENFORCE_TOKEN_BUDGET` | 0 | 1=超预算抛错阻断；0=仅 warning |

以上四个预算项已接入平台「运维 → AI 接入 → Token 预算」并读取运行时配置，
不再只认进程环境变量。建议至少配置单项目/组织日预算并开启硬拦截；具体数值应按
账号套餐和团队规模设定，平台不擅自假设一个通用额度。
| `AP_RAG_TOP_K` / `AP_CHUNK_SIZE` / `AP_MAX_CASE_NUM` | 见运维配置 | 输入侧节流 |

落盘目录：`{artifacts_root 的 parent}/ai_usage/usage-YYYY-MM-DD.jsonl`  
JSONL 行含 `project_id` / `org_id`（由 `set_ai_billing_scope` 注入；生成用例 / Design Chat 已接线）。  
汇总：设计域 stats 的 `tokens`；`/ops/summary` → `ai.tokens`；`/metrics` 含 `mc_ai_*`。

### IDE（Vision）

| 变量 | 默认 | 说明 |
|------|------|------|
| `AUTOPILOT_INTENT_VISION` | 0 | 总开关 |
| `AUTOPILOT_VISION_*` | 见 `.env.example` | 压缩/DOM/detail/WHEN |
| `AUTOPILOT_VISION_MAX_CALLS_PER_CASE` | 30 | 单用例 vision 调用硬顶；0=不限（不建议） |
| `AUTOPILOT_VISION_ALLOW_LOCAL_KEY` | （空） | 企业锁定 Platform URL 时默认禁用本机 Vision Key；Runner 注入 Key 时显式 `1` |
| Vision 请求 `max_tokens` | 800 | 代码内写死输出封顶 |
| `AUTOPILOT_VISION_USAGE_DIR` | `~/.autopilot/vision_usage` | usage JSONL 目录 |

企业：Design/编写 Key 只在 Platform Ops；用户 IDE 勿放厂商 Key，Vision 默认关。与链路 3 策略对齐见 IDE `docs/CONFIGURATION.md`。

---

## 代码锚点

| 仓 | 路径 |
|----|------|
| Platform | `platform/ai/ai_usage.py`、`ai_client.py`、`services/design_stats.py`、`core/metrics.py` |
| IDE | `autopilot/intent/usage.py`、`vision_plugin.py`、`context_budget.py`、`config.py` |

---

## 验证

```powershell
# Platform
python -m pytest tests/test_ai_usage.py tests/test_ai_token_guardrails.py -q -p no:xonsh

# IDE
python -m pytest tests/test_intent_usage.py tests/test_ai_call_guardrails.py -q -p no:xonsh
```
