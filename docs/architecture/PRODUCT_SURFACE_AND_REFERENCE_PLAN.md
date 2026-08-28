# 产品面与开源借鉴 Plan（架构边界 · 契约 · Web IA）

> **版本**：1.2（2026-08-20）  
> **地位**：Platform Web 信息架构与「向开源成熟产品借鉴」的**唯一立项真源**。  
> **冲突时**：以本文 + [`RBAC_BOUNDARY_CONTRACT.md`](./RBAC_BOUNDARY_CONTRACT.md) 为准；旧 Sonic / 运营 Plan 只保留设备云与告警切片细节。  
> **主仓**：`Autopilot-Platform`（Web + API）；IDE 仓仅契约镜像与能力矩阵，不重复做运维/云真机站。

---

## 0. 三句话

1. **我们是「关键字 IDE + 组织/项目工作台 + 批跑治理」**，不是 Sonic 式浏览器云真机，也不是第二套积木 Web IDE。  
2. **借鉴只借「路径与边界」**（谁先看见什么、租户怎么切、设备与任务怎么分），不借皮肤、不抄仓、不换主轴技术栈。  
3. **一切 UI / 功能立项必须先过硬契约**：组织硬隔离、项目必有 `org_id`、执行资源必有 `project_id`、双仓边界、人设分档。

---

## 1. 产品身份与架构边界

### 1.1 部署单元（双仓）

| 单元 | 仓 / 路径 | 主责 | 禁止 |
|------|-----------|------|------|
| **AutoPilot IDE** | `AutoPilot/autopilot/` | 用例编辑、Inspector/本机镜像、本地执行、Binding 真源、制品打包 | 不做云远控站、不做全局运维中心 |
| **Platform 服务** | `Autopilot-Platform/.../platform/` | 设计域、Job/计划/报告、设备池、制品、Org/RBAC、审计 | 不做第二套关键字 DSL、不嵌浏览器投屏产品 |
| **执行核 `ap/`** | Platform `autopilot_platform/ap/` | Runner 可部署切片（与 IDE 执行核同构） | 不是产品语义真源 |
| **Platform Web** | `frontend/` | 组织→项目上下文下的设计 / 批跑 / 报告 / 轻量设备与运维 | 默认人设=普通项目成员，运维 runbook 不得塞给全体 |

契约真源：IDE / Platform 同名 [`DUAL_REPO_CONTRACT.md`](../../../../AutoPilot/docs/architecture/DUAL_REPO_CONTRACT.md)（双仓同步）；改一边必须改另一边。

### 1.2 领域分层（与 Web 导航对齐）

```text
平台实例
├── 身份：JWT 用户 / Runner Token / 运维 Token
├── 租户：Organization（硬隔离）
│     └── Project（必须 org_id；工作空间）
│           ├── 设计域：需求 / 意图用例 / 知识 / 文档
│           └── 执行域：制品 / 应用包 / Job / 计划 / 报告
├── 调度面：Runner + Device + resource_pool（组织内软隔离）
└── 运维面：仅平台 admin（预算、Token、purge、配置中心）
```

设备列表**不是**第二条租户边界：不能靠设备板把外组织项目内容透出来。

---

## 2. 硬契约（立项前门禁）

下列条款**不可被「借鉴某某开源」推翻**。冲突时先改契约版本号，再改代码 / UI。

| ID | 契约 | 真源 | 对 Web 的硬约束 |
|----|------|------|-----------------|
| **C-RBAC** | 组织硬隔离；仅平台 admin 看全场；本组织 owner/admin ≡ 本组织全部项目的管理者；禁止外组织入项 | [`RBAC_BOUNDARY_CONTRACT.md`](./RBAC_BOUNDARY_CONTRACT.md) **v1.2+** | 顶栏组织/项目切换；组织管理员 `my_role` 固定为项目 owner；无「本组织管理员变 viewer」文案 |
| **C-OWN** | 项目必须有 `org_id`；制品/任务/计划必须有 `project_id`；创建者+ACL **不是**无归属通道。**Device 不是此类执行资源**（见边界契约 §5.2） | 同上 §3 / §5.2 | 创建表单强制选项目；禁止「无项目上传」入口；脏数据不做成兼容 UI；设备注册/看板不跟顶栏项目 |
| **C-ACL** | ResourceAcl 仅**同组织**跨项目分享执行资源；设计域不走 ACL | 同上 | 「共享」面板只出现在执行资源；分享对象必须是本组织用户 |
| **C-CAP** | 前端 `useCapabilities` 只做体验门禁；以后端 `rbac.can` 为准 | IDE `docs/rbac-capability-matrix.md` | 侧栏/按钮按人设隐藏；越权仍 403 |
| **C-DUAL** | IDE ↔ Platform 同构面与分叉面；禁止把 Platform 已有能力当 IDE 缺口重复立项 | `DUAL_REPO_CONTRACT.md` | Web 不复制 IDE 编辑器；远控不进 IDE 热路径 |
| **C-SONIC** | Sonic 对照只借公开能力；不整仓抄源码；B2/B3（WS claim、进程池、远控产品化、全程自动录）未书面解冻不立项 | IDE `docs/ROADMAP.md` 冻结项 | Web 不做云真机控制台心智 |

变更流程：改契约版本与条款 → 改 `rbac.can` / 列表过滤 / 前端能力档 → 跑 `test_rbac_boundary_contract` / `test_org_only_isolation` / `test_frontend_persona_capabilities`。

---

## 3. 开源借鉴矩阵（借什么 / 不借什么）

### 3.1 参考对象与角色

| 参考 | 适合借 | 明确不借 |
|------|--------|----------|
| **ReportPortal** | 项目空间心智、结果/报告主路径、进组织≠进项目 | 整站 UI、他们的权限模型细枝 |
| **Harbor** | Robot/Token 作用域、Resource×Action、`can()` 求值顺序 | Harbor 门户皮肤、镜像仓库领域 |
| **DeviceFarmer / AWS Device Farm** | 「管池」与「任务里选设备」分离 | Device 硬 `project_id` 租户、整仓 STF |
| **SonicCloudOrg** | Runner/设备占用、证据/录屏、运营告警、失败趋势（已大部分交付） | 浏览器远控、积木 Web IDE、Java 微服务全家桶、sonic-client-web 当设计稿 |

### 3.2 借鉴判定标签（沿用 Sonic 审计）

`ALREADY_DONE` / `PARTIAL` / `WORTH_BORROW` / `DEFER` / `DO_NOT`

**动手前**必须填双仓取证表（IDE + Platform），禁止凭「开源有」立项。

### 3.3 与既有 Plan 的分工

| 文档 | 管什么 | 本文关系 |
|------|--------|----------|
| `RBAC_BOUNDARY_CONTRACT` | 谁能看见什么 | **硬依赖** |
| IDE `docs/ROADMAP.md` | 设备云冻结项与运营面已交付摘要 | 设备/告警细节以 IDE 摘要为准；**产品面/导航以本文为准** |
| `ORG_RBAC_PLAN` / `MULTI_TENANCY` | 分期历史 | 边界冲突时改旧文对齐契约 |
| 本文 | Web IA、人设默认屏、借鉴立项门禁 | 新开 UI/产品面工作从此拆 Todo |

---

## 4. Web 信息架构目标（Platform `frontend/`）

### 4.1 顶栏上下文（强制）

```text
[组织 X-Org-Id] → [项目 filterProjectId] → 当前页内容
```

- 未选组织：平台/组织管理员可进组织管理；普通成员提示先加入组织。  
- 未选项目：设计写 / 上传制品 / 建 Job / 建计划 **阻断**（对齐 C-OWN）；允许只读概览与闲聊（合成计费桶，不落设计域）。  
- **设备看板默认组织视图**：列表/摘要不跟顶栏项目走；项目仅用于批跑/计划 DevicePicker 的调度资格筛选。  
- 切换组织：清空跨组织残留的项目选择，避免「隔壁组织项目 ID 仍挂在顶栏」。

### 4.2 侧栏分区（已有 `router/tabs.ts`，钉死语义）

| section | 标签 | 默认可见人设 | 说明 |
|---------|------|--------------|------|
| `overview` | 概览 | 登录用户 | 仪表盘、项目、共享（执行资源 ACL） |
| `design` | 测试设计 | 项目可读成员 | 总览 / 文档 / 意图用例 / 知识；**无项目则只读或引导** |
| `exec` | 测试与执行 | 项目可读成员 | 制品 / 应用包 / 批跑 / 计划 / 报告 |
| `infra` | 设备与执行 | 登录用户（组织软过滤） | 设备板=组织在线设备；**批跑内选设备**才按项目池资格收窄；CRUD 池仍在本区 |
| `admin` | 系统/组织管理 | `canOps` 或 `canManageUsers` | 运维仅平台 admin；用户/审计可为组织管理员 |

禁止：把「启动 Runner / CLI token / AP_*」类 runbook 放进普通成员默认路径（见 ORG_RBAC_PLAN §8.3）。

### 4.3 人设 → 第一屏

| 人设 | 登录后默认 | 侧栏隐藏 |
|------|------------|----------|
| 普通项目成员 / viewer | 设计总览或批跑（有项目时） | `ops`；无 `canManageUsers` 时无用户/审计 |
| 组织 owner/admin | 项目列表（本组织全部） | `ops`（除非同时是平台 admin） |
| 平台 admin | 概览或运维待办 | 无（全开） |

后端 `ProjectOut.my_role`：本组织管理员对本组织项目固定下发 `owner`。

### 4.4 关键任务路径（借鉴验收用，不是抄 UI）

立项 UI 改动时，用下表做「对照截图式」验收；只收「好且适用」：

| 用户任务 | 本产品目标路径 | 对照参考 |
|----------|----------------|----------|
| 进入正确租户再干活 | 顶栏选组织→选项目→进设计/批跑 | ReportPortal 项目上下文 |
| 建一次批跑 | 制品/应用包属项目 → Job 带 `project_id` → 可选设备/池 | Device Farm「任务里选设备」 |
| 看失败证据 | 报告 → evidence / 日志 / 录屏 | Sonic 结果页（能力级，非布局） |
| 管人 | 组织成员 ≠ 项目成员；邀请先入组织再入项 | Harbor / 契约 C-RBAC |
| 运维 | 仅 admin 进配置中心 / purge / Token | Harbor 管理员面 |

---

## 5. 现状差距（相对目标，非重复立项清单）

| 项 | 现状（取证级） | 判定 | 备注 |
|----|----------------|------|------|
| 侧栏五区 + tab 路由 | `tabs.ts` / `App.vue` 已有 | **ALREADY_DONE** | 勿为「像 Sonic」重做 |
| `useCapabilities` + 组织提升 | 已按契约提升，非「覆盖 viewer」 | **ALREADY_DONE** | 保持与后端一致 |
| 无归属创建拒绝 | API + 契约 1.2 + Web 表单强制 | **ALREADY_DONE** | A1 已收 |
| 设计无项目阻断 | ProjectContextBanner + ReadonlyBanner 文案区分 | **ALREADY_DONE** | A2 已收 |
| 设备区 vs 批跑选设备文案 | DevicesHub / DevicePicker 已钉死 | **ALREADY_DONE** | B3 已收 |
| 组织切换清项目上下文 | `selectOrg` + toast | **ALREADY_DONE** | B1 已收 |
| 云远控 / 投屏进 Web | Android/iOS MVP 已交付 | **UNFROZEN（C1）** | 见 [`DEVICE_REMOTE_ANDROID_MVP.md`](./DEVICE_REMOTE_ANDROID_MVP.md)；入口在 Platform Web，非 IDE |
| Job 性能曲线入报告 | 无 | **DEFER** | Sonic 审计 S-P1-C，非本 Plan 默认批次 |

---

## 6. 分期（仅产品面 / Web IA；须书面解冻）

### Todolist（执行态）

| ID | 状态 | 说明 |
|----|------|------|
| **A1** | ✅ | 执行域 UI + `mcExecActions` 强制 `project_id`；`ExecProjectGateBanner` |
| **A2** | ✅ | 设计域未选项目 vs viewer 文案区分 |
| **A3** | ✅ | 契约 §6 已链本文；人设单测覆盖 |
| **B1** | ✅ | `selectOrg` / `refreshProjects` 清跨组织项目 + toast |
| **B2** | ✅ | `resolvePersonaLandingTab` + 登录仅纠偏默认 dashboard |
| **B3** | ✅ | DevicesHub / DevicePicker 管池 vs 任务选设备文案 |
| **C1** | 🔄 Android first | Platform Web 远控（占用后远程调试）；见 DEVICE_REMOTE_ANDROID_MVP |
| **C2–C4** | 冻结 | 积木 IDE / WS claim / 换皮 — 未书面解冻禁止拆 Todo |

### Phase A — 契约对齐收口（默认可做，不增产品面）

| ID | 项 | 验收 |
|----|-----|------|
| **A1** | 创建制品/Job/计划/应用包：UI 强制 `project_id`；无项目隐藏提交 | 与 API 403/400 一致；人设单测不回归 |
| **A2** | 无项目设计写路径：统一 ReadonlyBanner / 空态文案 | viewer 与「未选项目」文案可区分 |
| **A3** | 文档与能力矩阵指针：本文 + 契约 1.2 | `RBAC_BOUNDARY_CONTRACT` §6 链到本文 |

### Phase B — 上下文与人设体验（薄改，解冻后）

| ID | 项 | 验收 |
|----|-----|------|
| **B1** | 切换组织时清空非法项目选择并提示 | 无法用旧 `project_id` 打到外组织 API |
| **B2** | 默认落地页按人设（§4.3） | 普通成员不落 ops；组织管理员不默认进运维 |
| **B3** | infra vs exec 引导：批跑内选设备 vs 侧栏管池 | 文案 + 一次空态引导即可，不做第二设备站 |

### Phase C — 远控与其余冻结项

| ID | 项 | 状态 |
|----|-----|------|
| **C1** | Platform Web 远控 / 投屏（Android 先行，iOS 同会话模型二期） | **已书面解冻** — 入口在设备台「远程调试」，Runner 托管 scrcpy/WDA；IDE 不做云远控站 |
| **C2** | Web 积木步骤 IDE（第二套 DSL） | 冻结 |
| **C3** | WS/gRPC claim、Agent 进程池、Job 全程自动录 | 冻结 |
| **C4** | 为「视觉对齐 Sonic client-web」做大改版皮肤 | 冻结 |

C2–C4 解冻条件：书面说明业务刚需 + 双仓审计表 + 不影响 C-RBAC / C-OWN / C-DUAL。  
C1 解冻依据：调试/远控/演示链路刚需；占用模型已落地；实现落 Platform Runner + Web，不影响双仓契约（IDE Inspector 仍为本机 USB）。

---

## 7. 明确不做（DO_NOT）

- 以 Sonic / ReportPortal / 任意开源站为设计稿整页换皮。  
- 把无 `org_id` 项目、无 `project_id` 制品做成「管理员可见的兼容模式」产品入口。  
- 组织管理员在本组织项目里展示为 viewer，或用「顶栏覆盖」假装提权。  
- 在 IDE 仓再实现一套 Platform Ops / Dashboard / 告警中台。  
- 把设备列表做成跨组织内容通道。

---

## 8. 文档与代码指针

| 文件 | 职责 |
|------|------|
| **本文** | 产品面 + 借鉴门禁 + Web IA |
| `RBAC_BOUNDARY_CONTRACT.md` | 租户/角色边界真源 |
| IDE `docs/rbac-capability-matrix.md` | 能力 ID ↔ 控件 |
| IDE `docs/ROADMAP.md` | 设备云冻结项；运营告警已交付（主仓 Platform） |
| `frontend/src/router/tabs.ts` | Tab ↔ 分区真源 |
| `frontend/src/composables/useCapabilities.ts` | Web 体验门禁 |
| `platform/services/rbac.py` | `can()` |

---

## 9. 变更与验收清单

开任何「借鉴 / 改导航 / 改默认屏」PR 前勾选：

- [ ] 未违反 §2 硬契约（尤其 C-RBAC、C-OWN）  
- [ ] 已填参考来源与判定标签（§3.2），且非 DO_NOT / 未解冻 DEFER  
- [ ] 双仓是否需要改动已声明；无则写 NO  
- [ ] 人设：普通成员路径无运维 runbook  
- [ ] 相关单测：边界契约 + 前端人设能力（若动 UI）

---

## 修订记录

| 版本 | 日期 | 说明 |
|------|------|------|
| 1.0 | 2026-08-13 | 首版：会话结论（借鉴边界）+ 契约 1.2（无归属拒绝）+ 现有 Web 五区导航钉死 |
| 1.1 | 2026-08-13 | Phase A/B 落地：执行域强制项目、组织切换清项目、人设落地、设备区文案；Todolist 勾选 |
