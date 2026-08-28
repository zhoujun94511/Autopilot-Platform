# AutoPilot Platform · 领域边界

## 三链路定型（产品主叙事）

| 链路 | 职责 | 交付标准 |
|---|---|---|
| **1 · 传统自动化** | IDE 关键字编排 + Platform 制品/Job/Runner | **默认可交付**，无 AI |
| **2 · 设计 AI** | Platform：NL/文档 → 常规测试用例 + 人审 | **独立测设能力**；APPROVED ≠ 可执行自动化 |
| **3 · AI 辅助编写** | IDE：采页 + NL → 传统关键字 `.tc` → 本地试跑 → 可选上传 | **增强、可插拔**；编排真源在 IDE，非 Platform webhook |

- 链路 2 的 Webhook 自动导入、APPROVED 一键入队为**高级可选**，需 IDE 工程与 Binding。
- 链路 3 不依赖链路 2 的 APPROVED；定位器与 `.tc` 真源仍在 IDE。
- **厂商 AI Key 只在 Platform**（Ops 掩码 / 服务端 env）；IDE 企业路径经 `POST /ops/ai/codegen`（`cap.ops.ai.codegen`）持登录态调用，不持本机 Key。

## 产品形态

| 部署单元 | 仓库 | 职责 |
|---|---|---|
| **AutoPilot Platform** | 本仓 | 测试设计 + 执行治理统一 Web 平台（FastAPI + Vue） |
| **AutoPilot IDE** | `AutoPilot`（独立） | 关键字编排、Intent 运行时、Inspector、本地调试、制品发布客户端 |
| **TestRunner** | 本仓 `runner/` 与 IDE 内入口（双入口） | 向 Platform claim 任务并执行；不自建任务中心 |

旧仓 `TestPilot-vue` / `AutoPilot_Console` 为迁移来源，不再作为产品部署真源。

## 责任矩阵（摘要）

| 能力 | Platform | IDE | Runner |
|---|---|---|---|
| 需求 / Intent 用例 / RAG | 主责（生成 + 审核） | 导入 APPROVED → 可跑 intent 步骤 | 不负责 |
| Intent 运行时解析 / Binding / 自愈 | 只读状态 | 主责（工程内 Binding 真源） | 消费 Binding，可解析/自愈 |
| 关键字 / 对象库 / Inspector | 只读状态 | 主责（真源） | 消费执行 |
| 制品 / AppBuild / Job / 设备池 | 主责 | 上传/提交 | 下载执行 |
| 结构化结果 `result.json` | 索引主责 | 本地可生成 | 上传 |
| 用户 / 项目 / ACL / 审计 | 主责（IdP）；项目邀请 + 自助入项 | 接入登录 | Runner Token |

## Intent + Binding（三层）

| 层 | 真源 | 说明 |
|---|---|---|
| **Intent** | Platform `intent_case` / IDE `intent_act` 步骤 | 自然语言动作；默认可执行语义 |
| **Binding** | IDE 工程 `bindings/<logical_case_id>.json` | keyword + locator 缓存与自愈；随制品打包 |
| **Keyword** | IDE 关键字引擎 | WebDriver / Appium 实际驱动 |

## 禁止事项

- Platform 不做重型用例编辑器 / Inspector
- IDE 不自建云端 Job 队列
- 逻辑/Intent 用例 API **不**输出 Appium/Selenium 底层定位器（定位器只存在于 Binding 契约）
- Runner 不同时向多个任务中心领任务
- 不把 IDE 整仓并入 Platform
- 不以人工 `MAPPING_REQUIRED` 作为可跑前提（遗留枚举仅兼容旧数据）

## automation_status

| 状态 | 含义 |
|---|---|
| `LOGICAL_ONLY` | 仅文本，未结构化意图（遗留） |
| `INTENT_READY` | 已有 intent_steps，默认可跑（导入后目标态） |
| `PENDING_VERIFY` | 半自动 APPROVED，待首跑（本地或云端 result.json）验证 |
| `BINDING_PARTIAL` | 部分步无缓存，靠运行时解析 |
| `EXECUTABLE` | 最近一次全绿 |
| `DEBUGGING` | 失败且自愈未恢复（人审入口） |
| `PUBLISHED` | 制品发布 |
| `DEPRECATED` | 废弃 |
| `MAPPING_REQUIRED` / `DRAFT_AUTOMATION` | 遗留兼容，新导入不再写入 |

## Platform 代码布局

业务模块按职能收敛为包（`tenancy` / `authz` / `artifacts` / `ai` / `services`），根目录仅保留启动、`auth` 与兼容 shim。详见 [`PLATFORM_PACKAGE_LAYOUT.md`](./PLATFORM_PACKAGE_LAYOUT.md)。**禁止**在 `platform/` 根目录新增业务模块。

## 契约

见仓库根目录 `contracts/jsonschema/`：

- `logical_case.v1.json`（兼容）
- `intent_case.v2.json`
- `step_binding.v1.json`
- `artifact_manifest.v1.json`（含 `bindings_glob`）
- `result.v1.json`（含 intent/binding 步进字段）

## 边界 vs 契约：`ap/` 与 IDE `autopilot/`

**权威维护文档（双仓同名）**：[DUAL_REPO_CONTRACT.md](./DUAL_REPO_CONTRACT.md)  
（同构字节清单、故意分叉、公开契约、扩展检查清单、门禁命令。）  
三链路规划见 [AI_AUTOMATION_ROADMAP.md](./AI_AUTOMATION_ROADMAP.md)。

**结论（建议立场）**：本地测试机注册 TestRunner 到云端，是**边界内**的预期能力；真正需要收紧的是**执行核版本契约**，不是「本地执行 / 云端编排」本身。

| 维度 | 判定 | 说明 |
|---|---|---|
| **边界（正确）** | Platform 管编排（Job / 设备 / 制品）；IDE 管编写与 Binding；Runner 在「执行主机」跑用例 | 本地机注册 Runner = **云编排 + 本地执行**，与「云端托管 Runner」同属边界内部署形态，不是架构错误 |
| **契约风险（需收紧）** | 漂移来自「两套执行核拷贝」 | Platform Runner 消费仓内 `autopilot_platform/ap/`；IDE 消费独立仓 `autopilot/`。长期分叉会导致关键字语义、`result.json` 字段、Intent 步进解释不一致 |

**应对契约（发布对齐）**：

1. **制品格式**（`artifact_manifest` / bindings）+ **Job API** + **`result.json`** 为跨部署单元硬契约
2. **执行核版本对齐**：Runner 与 IDE 应共用同一 `autopilot` 包版本，或 CI 校验 `ap/` 与上游 IDE 包同步（pin / 同步脚本 / 差异门禁）
3. 不以「再复制一套引擎」作为长期方案；`ap/` 视为 IDE 执行核的可部署切片，而非独立产品语义源

### automation_status 回写职责

| 动作 | 职责方 |
|---|---|
| 设计态生成 / 审核 → `INTENT_READY` / `PENDING_VERIFY` 等 | Platform 设计域 / IDE 导入客户端 |
| 本地跑通 / Binding 覆盖 → `EXECUTABLE` / `BINDING_PARTIAL` / `DEBUGGING` | **IDE 本地或 mgmt 客户端**（`run_status_sync` 等） |
| Console / 云端 TestRunner 完成 Job 且 `result.json` 含 `logical_case_id` | **Platform 回写**：passed→`EXECUTABLE`，failed→`DEBUGGING`（跳过 `PUBLISHED`/`DEPRECATED`） |
| 无 `logical_case_id` 的批跑结果 | **不回写**设计域 |

`PENDING_VERIFY` = 半自动 APPROVED 后待首跑；首跑结果（本地或云端 result.json）驱动跃迁。

**APPROVED → 云端批跑**：`POST /design/logical-cases/enqueue-job`（需已上传含 `logical_case_id` 入口的制品）。APPROVED 本身只表示设计审核通过，不等于已有可执行制品。

**执行核版本**：`contracts/RUNTIME_PIN` ↔ `autopilot_platform.ap.__version__`；制品 `required_runtime_version` 在 `MC_ENFORCE_RUNTIME_VERSION=1` 时创建 Job 强校验（`GET /ops/runtime-version`）。