# AI 自动化后续规划（Platform 摘要）

权威全文在 IDE 仓 `docs/architecture/AI_AUTOMATION_ROADMAP.md`。本文只记 Platform 侧职责，避免双仓各维护一份长文。

| 链路 | Platform 职责 |
|------|----------------|
| 1 传统 | 制品 / Job / 设备 / Runner |
| 2 设计 AI | 文档分析、逻辑用例生成与人审；Webhook/入队为高级可选 |
| 3 AI 编写 | **持钥** `POST /ops/ai/codegen`（`cap.ops.ai.codegen`）；**不**持有定位器真源 |

配置见 [AI_CONFIG.md](./AI_CONFIG.md)、[TOKEN_BUDGET.md](./TOKEN_BUDGET.md)、[DOMAIN_BOUNDARIES.md](./DOMAIN_BOUNDARIES.md)。

**明确不做：** Platform 下发 xpath/定位器；无 Binding 的无人值守全 AI 批跑；默认开启 Vision。
