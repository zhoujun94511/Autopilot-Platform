# AutoPilot IDE 对接清单（IDE 仓改造，本仓不拷贝 IDE）

Platform 基址默认：`http://127.0.0.1:8000`，API 前缀 `/api/v1`。

## 三链路对接要点

| 链路 | Platform | IDE |
|---|---|---|
| 1 传统 | 制品 / Job / 设备池 | 关键字 `.tc`、F5、上传、远程批跑 |
| 2 设计 AI | 文档分析、逻辑用例生成与人审 | **不强制**；Webhook / 导入意图为高级可选 |
| 3 AI 编写 | **持钥** LLM 网关 `POST /ops/ai/codegen`（`cap.ops.ai.codegen`）；不收设备 UI 树真源 | 采页 → 登录态调网关 → 传统 `.tc` → 试跑门禁；企业 IDE 不持 `AP_AI_*` |

**APPROVED** 只表示设计审核通过，**不等于**已有 Binding、不等于可云端批跑。

## 已提供 / 即将依赖的 API

| 用途 | 方法 | 路径 |
|---|---|---|
| 登录 / refresh / logout | POST | `/auth/login` `/auth/refresh` `/auth/logout` |
| 项目列表 | GET | `/projects` |
| 设计域统计 | GET | `/design/stats` |
| 需求 CRUD | * | `/design/requirements` |
| 拉取已评审逻辑用例 | GET | `/design/projects/{project_id}/logical-cases/export` |
| 单条逻辑用例 | GET | `/design/logical-cases/{id}` |
| 更新逻辑用例（含 automation_status） | PATCH | `/design/logical-cases/{id}` |
| 知识库 CRUD | * | `/design/knowledge` |
| 文档上传 / 分析 | * | `/design/documents` |
| RAG 健康 | GET | `/ops/rag-health` |
| 上传工程制品 | POST | `/artifacts` |
| 上传应用包 | POST | `/app-builds` |
| 提交远程 Job | POST | `/jobs` |
| 任务结构化结果 | GET | `/jobs/{id}/result` |
| 链路 3 LLM 网关（服务端持钥） | POST | `/ops/ai/codegen` |

Export bundle（v2）：含 `review_status=APPROVED` 的用例，带 `intent_steps`（及兼容字段 `logical_steps`）。**不含** xpath；Binding 只在 IDE 工程内。

## IDE 侧 Intent + Binding

1. `MgmtClient.export_approved_logical_cases(project_id)`
2. `write_logical_cases_as_drafts(...)` → `imported_logical/*.tc.yaml`（`intent_act`，默认可跑）
3. 工程 `bindings/<logical_case_id>.json`（`step_binding.v1`）
4. 关键字 `intent_act` → IntentRuntime（查 Binding → 解析 → 自愈 → 调现有 keyword）
5. 菜单：**管理台 → 导入意图用例…** / **审阅失败意图…**；CLI：
   - `python -m autopilot.intent import …`
   - `python -m autopilot.intent watch --once …`（轮询 APPROVED 增量导入）
   - `python -m autopilot.intent serve-webhook --project … --port 8765`（接收 Platform 推送）
   - `python -m autopilot.intent bind --locator …`（人审写 Binding）
   - `python -m autopilot.intent review …`
6. Platform `MC_DESIGN_WEBHOOK_URL`（见 Platform `.env.example`）：用例 APPROVED 时推送；IDE `.env.example` 中 `AUTOPILOT_INTENT_WEBHOOK_*`
7. 视觉解析：IDE `AUTOPILOT_INTENT_VISION`（默认 0）+ Vision/AI Key；上下文预算见 IDE `.env.example`
   （`AUTOPILOT_VISION_WHEN` / `SCREENSHOT` / `DOM` / 图片压缩参数，借鉴 Midscene compact 策略）
8. 上传工程：存在 `bindings/` 时 `manifest.json` 写入 `bindings_glob: "bindings/*.json"`（zip 纳入 `bindings/*.json`）
9. `.tc.yaml` schema 2.0 追踪字段保留
10. `automation_status` 回写：
   - 导入 → `INTENT_READY`（不再写 `MAPPING_REQUIRED`）
   - 本地通过且 Binding 全覆盖 → `EXECUTABLE`
   - 本地通过但 Binding 仅部分固化 → `BINDING_PARTIAL`
   - 本地失败（自愈未恢复）→ `DEBUGGING`
   - 制品上传 → `PUBLISHED`
   - **云端批跑**：Runner 上传 `result.json` 且 cases 含 `logical_case_id` 时，Platform 回写 passed→`EXECUTABLE` / failed→`DEBUGGING`
   - **APPROVED → Job**：`POST /design/logical-cases/enqueue-job`（artifact_id + 可选 logical_case_ids；制品须含对应入口）
11. `result.json` 步骤可含 `intent_id` / `binding_hit` / `heal_applied`
12. 执行核版本：`GET /ops/runtime-version`；`tools/check_ap_version.py`；`MC_ENFORCE_RUNTIME_VERSION`
13. 运维巡检 CLI（见 `tools/README.md`）：`init_platform` / `check_api_contract` / `smoke_http` / `dump_ops_config` / `knowledge_*`

## Platform 侧门禁

- 默认：上传后记录 `manifest_status`（missing/valid/invalid），不阻断
- 运维开启 `MC_REQUIRE_ARTIFACT_MANIFEST=1`：仅接受 `manifest=valid`

## 明确不做

- 不在 IDE 内复制 Platform 用户表
- 不在逻辑用例 API 返回底层定位器
- 不以人工 mapping 作为可跑门禁

## 双仓执行核

源码同构 / 故意分叉 / 契约门禁见本仓 [DUAL_REPO_CONTRACT.md](./DUAL_REPO_CONTRACT.md)
（与 IDE `docs/architecture/DUAL_REPO_CONTRACT.md` 同步维护）。

三链路与 Binding 边界见 [AI_AUTOMATION_ROADMAP.md](./AI_AUTOMATION_ROADMAP.md)。
