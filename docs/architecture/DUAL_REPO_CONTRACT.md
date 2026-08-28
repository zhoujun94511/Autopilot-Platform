# IDE ↔ Platform 双仓代码边界与契约

> **适用仓库**  
> - IDE：兄弟仓 `AutoPilot`（包 `autopilot/`）  
> - Platform：本仓 `Autopilot-Platform`（执行切片 `autopilot_platform/ap/`，服务端 `platform/`）  
>
> **本文目标**：明确「必须同构维护」与「允许分叉维护」的边界、公开契约与扩展流程，避免后续改动把一边当真源单向覆盖另一边。  
> **门禁脚本**：`tools/check_dual_repo_contract.py`（IDE 仓）；测试：`tests/test_dual_repo_contract.py`。

相关文档：

| 文档 | 侧重点 |
|------|--------|
| [feature-modules.md](../feature-modules.md) | 产品形态与用户可见职责 |
| Platform `docs/architecture/DOMAIN_BOUNDARIES.md` | 设计域 / Job / Binding 责任矩阵 |
| Platform `docs/architecture/IDE_INTEGRATION.md` | HTTP API 与 IDE 对接清单 |
| [packaging.md](../packaging.md) | 发布前双仓检查 |
| [intent-hitrate.md](../intent-hitrate.md) | Intent Vision / 命中率 |
| [mobile-backend-boundaries.md](../mobile-backend-boundaries.md) | 移动后端与镜像正交边界 |
| [AI_AUTOMATION_ROADMAP.md](./AI_AUTOMATION_ROADMAP.md) | 三链路规划与已落地项 |

> 两仓均维护同名文件 `docs/architecture/DUAL_REPO_CONTRACT.md`，内容应保持一致；改一边时同步另一边。

---

## 1. 总原则

### 1.1 产品边界（不混淆）

| 部署单元 | 仓库路径 | 主责 |
|----------|----------|------|
| **AutoPilot IDE** | `AutoPilot/autopilot/` | 用例编辑、Inspector/镜像、本地执行、Binding 真源、制品打包与投递 |
| **Platform 服务** | `Autopilot-Platform/platform/` | 设计域（需求/逻辑用例/RAG）、Job 编排、设备池、制品索引、ACL/审计 |
| **执行核切片 `ap/`** | `Autopilot-Platform/autopilot_platform/ap/` | 云端 / 本机 Runner 可部署的执行核（IDE `autopilot/` 的可运行子集，**不是**第二套产品语义源） |
| **TestRunner** | 两边均可入口 | claim Job → 调执行核 → 回传 `result.json`；不自建任务中心 |

```text
IDE 编辑 / Binding / 本地跑
        │ JWT + 制品
        ▼
   Platform (编排 · 设计 · 索引)
        │ Job claim
        ▼
   Runner → ap/ 执行核 → result.json
```

### 1.2 维护原则：**互补合并，非单向覆盖**

两边都可能有独立演进。同步时：

1. **先判类别**（字节同构 / 语义对齐 / 故意分叉），再决定拷贝方向或合并方式。  
2. **禁止**默认「IDE 覆盖 Platform」或反之。  
3. **故意分叉**必须写进本文 §3，并在门禁里用**语义探针**而非强制字节一致。  
4. **禁止** IDE ↔ Platform 硬互相 import（仅允许懒加载 / try 多路径，如 `intent/ui_context` 解析 `inspector.tree`）。

### 1.3 `ap/` 的定位

- `ap/` = IDE 执行核的**可部署切片**，供 Runner 与无 Qt/Inspector 的主机使用。  
- 长期不以「再复制一套引擎」为产品策略；漂移靠契约 + 门禁收敛。  
- Platform **服务端**业务（`platform/`）不进 `ap/`；IDE **UI**（`autopilot/ui/`）不进 `ap/`。

### 1.4 AUD-P1-005：共享执行核包路线图（暂不落地 wheel）

**现状（已验证）**：双仓字节同构 + `check_dual_repo_contract.py` 门禁；关键路径 MATCH。

**目标态**：发布单一 `autopilot-runtime`（或同名）wheel，IDE / Platform Runner 均依赖该包，**禁止**再维护第二份执行核拷贝。

**过渡策略（当前强制）**：

1. 继续以 IDE `autopilot/` 与 Platform `ap/` **字节一致**为唯一合法状态；改一边必须同步另一边。  
2. 新执行核文件进入同构清单前，先更新本文 §2 与门禁脚本。  
3. **本阶段不切** monorepo / 私有 PyPI；切包条件：门禁绿 ≥ 1 个发布周期 + Runner 安装路径验证 + 无紧急热修依赖双拷贝。  
4. 切包后：`ap/` 变为 thin re-export 或直接依赖外部包；门禁改为「版本钉 + ABI 探针」。

**非目标**：把 `platform/` 服务端或 `ui/` 塞进 runtime 包。

**相邻预留（非本 AUD）**：设备机 Runner 安装面削瘦 / 可选独立 `autopilot-runner` 包见 Platform `docs/managementconsole-split.md`；与「执行核切 wheel」分开，本阶段同样不落地。

---

## 2. 同构维护（须字节一致）

下列路径在 IDE `autopilot/` 与 Platform `autopilot_platform/ap/` 之间 **文件内容必须完全一致**。改任一处须同步另一仓，并由 `check_dual_repo_contract.py` 校验。

### 2.1 执行编排核

| 相对路径 | 说明 |
|----------|------|
| `engine/executor.py` | 步骤执行、Intent meta 重试等 |
| `engine/suite.py` | 套件编排 |
| `engine/run/__init__.py` | |
| `engine/run/config.py` | |
| `engine/run/parallel.py` | |
| `engine/run/sequential.py` | |
| `runtime/port_allocator.py` | 设备隔离端口族 |
| `runtime/device_runtime.py` | UDID 粘滞运行时 |
| `runtime/device_session.py` | 每设备 Appium/UIA2/WDA 注入 |
| `runtime/device_pool.py` | |
| `keywords/mobile/appium_server.py` | 按端口隔离的 Appium 进程池 |

### 2.2 Intent 栈

| 相对路径 | 说明 |
|----------|------|
| `intent/*.py`（除 `__main__.py`） | 运行时、解析、Vision、CLI、webhook 等 |
| `keywords/__init__.py` | 含 `intent_act` 注册 |
| `model/testcase.py` / `model/serializer.py` | 用例模型与序列化 |
| `metadata/keyword_defs/intent.xml` | Intent 关键字定义 |

`intent/__main__.py` 允许两侧包入口文案不同，**不在**字节门禁内；逻辑须仍指向同一 CLI。

### 2.3 Http 关键字与相关引擎

| 相对路径 | 说明 |
|----------|------|
| `keywords/http/*` | Session / Auth / Assert / Env 等 |
| `keywords/context.py` | |
| `engine/teardown.py` | |
| `metadata/keyword_defs/http.xml` | Http 关键字元数据（含 `risk_level` 等） |
| `mgmt/openapi_import.py` | OpenAPI/Postman → 确定性 HTTP `.tc.yaml` |

### 2.3.1 Web 关键字（Selenium + Playwright）

| 相对路径 | 说明 |
|----------|------|
| `keywords/web/*.py` | 浏览器/元素/校验/图像关键字与 `driver.py` 双引擎适配 |

改 Web 执行面后须同步 Platform `ap/keywords/web/`，并由 `check_dual_repo_contract.py` 的 **Web 关键字** 门禁校验。

**异常契约（双引擎一致）**：元素未找到、切换到非 frame/iframe 等失败路径须抛 `KeywordError`（勿向用例层泄漏 Selenium `NoSuchElementException` / `WebDriverException`）。Live 覆盖见 [WEB_LIVE_TESTING.md](../WEB_LIVE_TESTING.md)。

### 2.3.2 Data / SSH 关键字与 Public 元数据

| 相对路径 | 说明 |
|----------|------|
| `keywords/data/ssh.py` | SSH 连接主机信任（默认 RejectPolicy + known_hosts；未知主机须显式放行） |
| `metadata/keyword_defs/public.xml` | Public/Data 关键字元数据（含 `linux_ssh_*`、`risk_level` 等） |

改 SSH 主机信任或 Public 关键字元数据后须同步 Platform `ap/`，并由门禁 **Data/SSH 关键字** 校验字节一致。

`metadata/keyword_defs/mobile.xml` **允许**录屏注释等故意分叉，但高危关键字
（`mobile_app_adb_uninstall` / `mobile_app_reset_saveinfo` / `mobile_monkey`）的
`risk_level=irreversible` 须两边一致（门禁 **mobile destructive risk attrs**）。

### 2.3.3 ADB shell 命令面（AUD-2026-10）

| 项 | 约定 |
|----|------|
| `mobile/adb.py` → `adb_shell(command: str)` | **产品内部能力**；无公开「任意 shell」关键字 |
| 插值参数 | 须 `require_adb_shell_safe_token` / `require_android_package` / `require_adb_input_safe_text` |
| 审计 | 每次 shell 打 `AUD-2026-10` 日志（截断命令） |
| Intent / Authoring | 默认拒绝 irreversible；禁止向 NL 暴露 raw shell |
| `safe_zip`（AUD-2026-19） | IDE `runtime/safe_zip` 与 Platform `core/safe_zip` **函数体 AST 对齐**；`ap.runtime.safe_zip` **仅再导出**（包路径分叉允许） |

改 adb 校验/审计后须同步 Platform `ap/mobile/adb.py`（及对应关键字调用点），保留两侧 import 边界。

**XAPK 安装（2026-08）**：`mobile/xapk.py` 与 `keywords/mobile/session.py` 中 Android 装包路径须**语义对齐**（解压 + `install-multiple`）；允许 IDE 用 `mobile.errors.PackageError`、Platform `ap/` 用 `appparse.errors.PackageError` 的包边界分叉。

### 2.4 Intent 可达依赖切片（Platform 须具备且与 IDE 对齐）

下列为 `ap/` 跑通 Intent CLI / review / webhook / ui_context 所需；**内容与 IDE 对应文件字节一致**：

| 相对路径 |
|----------|
| `runtime/env_file.py` |
| `mgmt/binding_coverage.py` |
| `mgmt/logical_import.py` |
| `mgmt/status_sync.py` |
| `mgmt/auth_api.py` |
| `mgmt/client.py` |
| `inspector/tree.py`（仅树解析；非完整 Inspector UI） |

Platform 侧尚须存在：`mgmt/__init__.py`、`inspector/__init__.py`（可为薄包）。

### 2.5 同步操作约定

```powershell
# 示例：从 IDE 推 Intent 栈到 Platform（仅当判定为同构类且本轮以 IDE 为合并结果）
$src = "<ide-root>\autopilot"
$dst = "<platform-root>\autopilot_platform\ap"
# 按 §2 清单逐文件 Copy-Item；禁止整目录盲拷覆盖故意分叉文件

python <ide-root>\tools\check_dual_repo_contract.py
```

合并冲突时：保留两边各自有意的分叉（§3），只合并同构文件的逻辑变更。

---

## 3. 分叉维护（故意不同 / 仅语义对齐）

### 3.1 语义对齐（允许文件不同，行为探针须两边都有）

| 模块 | IDE | Platform `ap/` | 必须共有的行为 |
|------|-----|----------------|----------------|
| `keywords/mobile/driver.py` | 可接 Inspector `ControlSink` | **`mirror_control_sink` stub → `None`**；禁止引入 `WdaControlSink` / `AppiumControlSink` | `terminate_app(bundle_id)`、`AUTOPILOT_INTENT_KEEP_WDA` / `IOS_KEEP_WDA`、`_KEEP_WDA_MANAGERS` |
| `keywords/mobile/wda_client.py` | 允许分叉：远控 `alert_buttons` / `_request(..., rooted=)` 可仅 Platform | 同左可缺远控专用 API | `_request`/`_post` 支持单次 `timeout`；`press_button` 走 `/wda/pressButton` 且 **`timeout=3.0`** |
| `runtime/settings.py` | 完整设置（含 UI 主题等） | 可保留**内联 ui_theme** 等包边界差异 | `mc_api_token_enc` / `mc_jwt_enc` / `mc_refresh_enc`、钥匙串/DPAPI、`settings.json` ACL、`mc_org_id`、清空 refresh 的安全语义 |

改 driver / settings 时：**不要**为对齐而抹掉 Platform stub 或 IDE 的 ControlSink；只保证探针列表与安全语义。

### 3.2 包边界故意分叉（预期 DIFF，勿强行字节一致）

| 主题 | 说明 |
|------|------|
| 包导入 | IDE `autopilot.*` vs Platform `autopilot_platform.ap.*`；`appparse` 等导入路径可不同 |
| 版本号 | **公开契约** `runtime_contract.json` → canonical `MAJOR.MINOR.PATCH`（不加 `-vendored`）；**包标记** `ap.__version__` / `RUNTIME_PIN` 可带 `-vendored` |
| `safe_zip` 双份（AUD-2026-19） | 允许两份文件直至 AUD-2026-03；**安全逻辑**须门禁 AST 对齐；Platform `ap.runtime` 只再导出 `core` |
| Inspector / UI / 镜像 | IDE 独有完整 UI 与 stream；`ap/` 仅保留 Runner 所需切片（如 `tree.py`） |
| `report/result_json.py` vs Runner 侧结果装配 | 字段契约以 schema 为准；实现落点可分文件，但 `result.v1` 语义须一致。`attachments[]` 须同时写 `case` 与兼容别名 `case_name`（AUD-2026-14；门禁探针） |
| iOS mirror 相关 stub | 无画面宿主上的降级 / 空实现 |

若某 DIFF 不再需要：先更新本文与门禁，再收敛文件。

### 3.3 仅一侧维护（禁止误同步进另一侧）

| 范围 | 所在仓 | 说明 |
|------|--------|------|
| `autopilot/ui/**`、Qt 壳、Inspector 面板 | IDE | 桌面 IDE |
| `platform/**`、Vue Console、设计域 RAG/生成 | Platform | Web 平台与 API |
| 设计域 JSON Schema 权威副本 | Platform `contracts/jsonschema/` | IDE **须**镜像全部同名 schema（门禁校验字节一致）；改契约以 Platform 为准再同步 IDE |
| 工程内 `bindings/*.json` | IDE 工程（制品内） | Binding 真源不在 Platform DB 存定位器 |

---

## 4. 公开契约（跨部署单元硬接口）

这些是**产品契约**，与「源码是否字节一致」正交：两边实现可变，载荷形状不可 silently 漂移。

### 4.1 运行时能力声明

两边各有一份，须 **schema_version、runtime major.minor、capabilities 集合**一致；
`runtime_version` 字符串宜两边同为 **canonical semver**（`MAJOR.MINOR.PATCH`，**不要**把 `-vendored` 写进公开契约）：

- IDE：`contracts/runtime_contract.json`
- Platform：`contracts/runtime_contract.json`

命名分层（AUD-P1-001）：

| 字段 | 真源 | 含义 |
|------|------|------|
| `runtime_contract.json` → `runtime_version` | 双仓公开契约 | 协议/能力基线版本（canonical） |
| `contracts/VERSION` | 双仓镜像 | 公开契约目录版本（AUD-2026-16）；与 `RUNTIME_PIN` 不同 |
| `ap.__version__` / `RUNTIME_PIN` | 仅 Platform | 内嵌执行核包装版本，可带 `-vendored` |
| `contracts/openapi/openapi.v1.json` | 仅 Platform | REST OpenAPI 导出（AUD-2026-11；`tools/export_openapi.py`） |
| 制品 `required_runtime_version` | manifest | 与执行核兼容比较：剥 `-vendored` 后看 major.minor |

兼容语义（勿改为全量字符串相等，除非 RFC 升级）：`runtime_compat.versions_compatible` / IDE `mgmt.runtime_contract`。

公开能力补充（行为已在执行核/Platform 落地，契约仅登记）：

- `runner_keep_appium_v1`：`AUTOPILOT_RUNNER_KEEP_APPIUM=1` 跳过 suite Appium teardown
- `mobile_screen_record_android_v1`：Android Appium `mobile_start/stop_screen_record` → evidence → Platform 报告播放
- `mobile_screen_record_ios_goios_v1`：iOS go-ios `screenshot --stream` + OpenCV；资源不全则关键字报不可用

当前能力示例：`artifact_manifest_v1`、`intent_binding_status_v1`、`result_json_v1`、`runner_project_scope_v1`。

新增能力：先改 JSON → 实现 → 门禁 → 文档。

### 4.2 制品 / 结果 / Binding Schema

Platform 权威目录：`contracts/jsonschema/`；IDE 必须镜像**全部**同名 `*.json`（字节一致，门禁 `check_jsonschema_sync`）。

| Schema | 用途 |
|--------|------|
| `artifact_manifest.v1.json` | 制品清单（含 `bindings_glob`、runtime 要求等） |
| `step_binding.v1.json` | 工程 Binding |
| `intent_case.v2.json` / `logical_case.v1.json` | 设计域导出 |
| `result.v1.json` | 结构化结果（含 intent/binding 步进、`resolved_keyword_id` 等） |

改 schema：先改 Platform → 同步拷贝到 IDE `contracts/jsonschema/` → 跑双仓门禁。

执行核 pin：`contracts/RUNTIME_PIN` ↔ `ap.__version__`；运维可开 `MC_ENFORCE_RUNTIME_VERSION`。

### 4.3 HTTP / 状态回写（摘要）

详见 Platform `IDE_INTEGRATION.md`。要点：

- 逻辑/Intent API **不**下发底层定位器；定位器只在 Binding。  
- `automation_status`：设计域与执行侧按 DOMAIN 矩阵回写；无 `logical_case_id` 的批跑不回写设计域。  
- IDE 客户端：`autopilot/mgmt/client.py`（与 `ap/mgmt/client.py` 同构）。

### 4.4 Intent 运行时职责分层

| 层 | 真源 | 同构？ |
|----|------|--------|
| Intent 文本 / 审核 | Platform 设计域 | 否（服务端） |
| Binding | IDE 工程 `bindings/` | 文件格式契约一致 |
| IntentRuntime / Vision / heal | `intent/` 包 | **是（字节）** |
| Keyword 驱动 | `keywords/` + driver | Http/Intent 相关字节；mobile driver **语义** |

---

## 5. 软耦合规则

1. **无硬跨仓 import**：开发机可同时 editable 安装两边，但代码不得 `import` 对仓包路径作为硬依赖。  
2. **多路径懒加载**：例如 `ui_context._load_mobile_tree_parsers` 按当前包名优先 `autopilot_platform.ap.inspector.tree` 或 `autopilot.inspector.tree`。  
3. **CLI 双入口**：  
   - `python -m autopilot.intent …`  
   - `python -m autopilot_platform.ap.intent …`  
   行为应对齐（help、子命令）。  
4. **Webhook**：IDE/Runner 收 Platform `logical_case.approved`；密钥与 loopback 规则见 `intent/webhook_server.py`。  
5. **链路 3 LLM 密钥**：厂商 `AP_AI_*` **只在 Platform**（Ops 掩码 / 服务端 env）；IDE 企业路径只持登录 JWT，经 `POST /api/v1/ops/ai/codegen`（`cap.ops.ai.codegen`）转发。本机 `AP_AI_*` 仅为未锁定部署时的开发逃生口，禁止写入工程仓或 `settings.json`。

---

## 6. 扩展检查清单（改代码前）

1. **落在哪一类？** 同构 / 语义对齐 / 故意分叉 / 单侧。  
2. **若同构**：改完后同步另一仓对应文件 → 跑  
   `python tools/check_dual_repo_contract.py`。  
3. **若语义对齐**：更新探针列表（`check_mobile_session_semantics` / `check_settings_security_semantics` / `check_wda_press_button_timeout`）并两边实现。  
4. **若新故意分叉**：先补本文 §3，再改门禁（不要用字节比较误杀）。  
5. **若新公开字段**：更新 `contracts/jsonschema/*` 与 `runtime_contract.json` capabilities（如需要）→ IDE/Platform 实现 → 相关单测。  
6. **Intent / Http / engine**：默认按同构处理，禁止只改一侧。  
7. **不要**把 IDE UI 或 Platform `platform/` 业务拷进对侧「为了对齐」。

---

## 7. 门禁与验证

| 检查 | 命令 / 位置 |
|------|-------------|
| 双仓契约总检 | `python tools/check_dual_repo_contract.py` |
| 显式根路径 | `--ide-root` / `--platform-root` |
| 单测 | `tests/test_dual_repo_contract.py`（IDE） |
| 打包前 | 见 [packaging.md](../packaging.md)「打包前双仓契约检查」 |

门禁覆盖摘要：

- `runtime_contract.json` schema / major.minor / capabilities  
- `contracts/jsonschema/*` 全量镜像（Platform 权威）  
- Http 关键字字节一致  
- Intent 栈字节一致  
- 执行编排核字节一致  
- mobile driver / settings / **WDA `press_button` 3s 超时** 语义探针  
- Platform `ap` Intent 依赖文件存在 + mgmt/tree 与 IDE 一致 + import 冒烟  

---

## 8. 修订记录

| 日期 | 说明 |
|------|------|
| 2026-07-29 | 初版：同构清单、故意分叉、公开契约、扩展清单与门禁交叉引用 |
