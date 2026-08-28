# Organization / RBAC 架构计划

> **边界真源已迁出**：[`RBAC_BOUNDARY_CONTRACT.md`](./RBAC_BOUNDARY_CONTRACT.md)。谁能看见什么、非法组合、求值顺序以该文为准。  
> **Web 产品面 / 开源借鉴**：[`PRODUCT_SURFACE_AND_REFERENCE_PLAN.md`](./PRODUCT_SURFACE_AND_REFERENCE_PLAN.md)。  
> 本文保留分期历史、资源池细节与旧矩阵草稿。与契约冲突时**改本文**。

**修订**：2026-07-27（Phase 3 `resource_pool` 软隔离落地；结合代码现状 + ReportPortal / Harbor / DeviceFarmer 借鉴）

---

## 0. 代码现状快照（Plan 依据）

| 模块 | 路径 | 现状要点 |
|---|---|---|
| 模型 | `platform/models.py` | `organizations` + `organization_members(role: owner\|admin\|member)`；`projects.org_id`；`project_members(role: owner\|member\|viewer)`；`resource_acl`；`runners.org_id` / `project_ids_json` |
| 项目门禁 | `platform/projects.py` | `assert_can_access_project` / `assert_can_write_project` / `visible_project_filter`；**仅** `project_members`（admin 旁路） |
| 组织门禁 | `platform/services/organizations.py` | `assert_can_access_org` / `assert_can_manage_org`；**不**授予项目内容读 |
| 设计域 | `platform/services/design_access.py` | `ensure_project_access` / `resolve_list_scope` → 项目成员 |
| 资源 ACL | `platform/acl.py` | `can_access_resource` / `filter_resources_by_acl`；项目成员或显式 ACL |
| 鉴权 | `platform/auth.py` | JWT + `X-Org-Id`；Runner Token scope；`assert_can_manage_users`（org admin） |
| 设备 | `platform/services/devices.py` | `_filter_devices_for_auth`：org Runner / 可见项目忙任务 — **软隔离** |
| 列表 | artifacts / jobs / schedules / app_builds | 必须有 `project_id`；列表按可见项目 + 同组织 ACL |

**已对齐 ReportPortal 核心原则（代码已有，缺矩阵固化 + org-only 强化测试）**：

- 进组织 ≠ 进项目：`list_projects` 只返回 `project_members`，组织成员 alone 看不到项目元数据（更无内容）。
- 项目硬隔离：设计 / 制品 / Job 均依赖项目成员或显式 ResourceAcl。

**缺口（本轮要补）**：

1. 无集中 **Resource×Action 策略表**；权限散落在 `projects` / `acl` / `organizations` / `design_access`。
2. 无「仅 org 成员、无 project 成员 → 设计/制品/Job 不可见」专项集成测试（现有 `test_organizations` 只测「加入后可见」）。
3. 组织/项目邀请**无**「不能提权超过自己」等级校验（Phase 2）。
4. 无 Harbor 式统一 `can(...)`；关键路径逐步挂接，避免大爆炸重写。

---

## 1. 边界（是什么 / 不是什么）

```
Platform Instance
├── Platform User（全局账号）          ← 登录身份；非租户
├── Organization（= 事业部 UI）         ← 管人、建项目、用户/审计范围
│     └── Project（硬隔离边界）        ← 设计/制品/Job/计划/ACL 的数据域
│           └── ResourceAcl            ← 跨项目显式分享（例外通道）
└── Device / Runner 池                 ← 软隔离（Group/scope），非 project 租户硬列
```

| 层 | 职责 | **不是** |
|---|---|---|
| **Platform** | 全局用户、平台角色 `admin`/`operator`、运维 Token、bootstrap | 不是客户 SaaS schema；不是「事业部」之上再套一层 |
| **Organization** | 成员与 org 角色；可选 `X-Org-Id` 上下文；org admin 管本组织用户/审计；创建项目时校验 org 成员 | **不**隐式授予任何项目内容读/写；不是 GitHub Team；不是 Kiwi 多租户 schema |
| **Project** | 执行与设计硬隔离域；`project_members` 为唯一内容可见入口（+ admin / ACL） | 不是设备物理租户；不是全局用户命名空间 |
| **ResourceAcl** | 对 artifact/job/schedule/app_build 的显式 read/write 分享 | 不替代项目成员；不用于设计域（设计仅项目成员） |
| **Device / Runner 池** | `resource_pool` + Runner `org_id` / `project_ids`；设备列表按授权池 + org Runner 软过滤 | **不**给 Device 表硬塞 `project_id` 租户；不做 DeviceFarmer 整仓照搬 |

---

## 2. 契约

### 2.1 角色枚举

| 作用域 | 角色 | 含义 |
|---|---|---|
| Platform | `admin` | 跨组织/项目旁路；运维 |
| Platform | `operator` | 普通登录用户（无平台旁路） |
| Platform | `ops_admin` | **扩展点**（当前 ≡ `admin`，见 `is_ops_admin`） |
| Organization | `owner` | 组织最高治理；可管成员/用户 |
| Organization | `admin` | 组织治理（管成员/用户）；**默认可建项目** |
| Organization | `member` | 组织内人；**默认无项目内容、不可建项目**；组织策略可放开建项目/邀请 member |
| Project | `owner` | 项目管理；加删成员 |
| Project | `member` | 读写项目内容 |
| Project | `viewer` | 只读项目内容；写需 ResourceAcl |
| Runner | `runner` + scope | 等同 Harbor Robot：绑 org/project 执行面 |

### 2.2 权限求值优先级（高 → 低）

1. **Platform admin**（含 admin API Token）→ allow（除明确禁止的自毁规则外）
2. **Runner Token** → 仅执行面 + `runner_scope_allows_project` + 已分配 Job 相关资源（见 `acl.runner_can_access_assigned_resource`）
3. **ResourceAcl**（显式分享）→ 对有 `project_id` 的执行资源：非成员也可按 ACL 读/写；**设计域不走 ACL**
4. **Project 角色**（`project_members`）→ 内容读/写的主路径
5. **Organization 角色** → 组织治理 API（成员、本组织用户、审计、建项目）；**org owner/admin 对本组织下项目视同 project owner**（覆盖该项目 viewer / 未加入）；**org member 永不单独满足项目内容**
6. 默认 **deny**

> 关键默认：`org member ∧ ¬project member` ⇒ 项目列表不含该项目；设计/制品/Job/计划列表不含该项目数据；直链 `?project_id=` → **403**。  
> `org owner/admin` 可读写本组织下全部项目内容，不受自己在 `project_members` 里是 viewer 的约束。

### 2.3 API 头与上下文

| 项 | 契约 |
|---|---|
| `Authorization: Bearer` | 用户 Access JWT |
| `X-API-Token` | Runner / Admin 运维通道 |
| `X-Org-Id` | 当前组织上下文；非成员 → **403**（platform admin 例外） |
| JWT `org_id` claim | 可选回退；以 Header 优先（现实现） |
| 列表无 `project_id` | deny-by-default：仅 `visible_project_filter` ∪ ACL 分享 ∪（admin 全量） |
| 列表有 `project_id` | 必须 `assert_can_access_project`（写再加 write） |

### 2.4 Runner / Robot scope

| 绑定 | 行为 |
|---|---|
| 无 `org_id` 且无 `project_ids` | 兼容旧 Runner：不按租户限制 claim（生产另有 `assert_production_runner_scoped`） |
| 仅 `org_id` | Job 所属项目 `org_id` 须匹配 |
| `project_ids` 非空 | claim 仅这些项目 |
| 独立 Token | 资源 ACL 仅本 runner 已分配 Job 相关 |

### 2.5 默认策略（产品）

| 场景 | 期望 |
|---|---|
| 仅 org 成员 | 可见组织本身；**不可见**未加入的项目元数据与内容 |
| 项目成员 | 可见该项目元数据 + 内容（viewer 只读） |
| 跨项目分享 | 仅执行资源走 ResourceAcl；设计域必须加成员或导出后本地 |
| 设备列表 | 软隔离；无组织表时不限制 |

---

## 3. 借鉴映射表

| 参考概念 | Autopilot 现有 / 拟增 |
|---|---|
| **ReportPortal** 全局 User | `users`（全局用户名） |
| RP Organization + membership | `organizations` / `organization_members` |
| RP「进 org ≠ 进 project」 | **已实现**：内容门禁仅 `project_members`；本轮用矩阵+测试钉死 |
| RP Project role | `project_members.role`（owner/member/viewer） |
| RP 邀请不提权超过自己 | Phase 2：`role_rank` 校验（org + project add_member / invite） |
| **Harbor** `role → Resource×Action` | 拟增 `ROLE_POLICIES` + `can(user, project, resource, action)`（`services/rbac.py` 或扩展 `acl.py`） |
| Harbor Robot | `runners` + `org_id` / `project_ids_json` + scoped token |
| Harbor `can(...)` 统一求值 | Phase 1：`rbac.can`；关键路径逐步委托，旧 `assert_*` 保留为薄包装 |
| **DeviceFarmer/STF** Device Group | Phase 3：**已落地** `resource_pool`（软隔离）；不做 Device `project_id` 硬租户 |
| ~~GitHub.com 整站~~ | **不做** |
| ~~平行事业部实体~~ | **不做**（Organization 即事业部） |
| ~~Team 中间层~~ | **默认不做** |
| ~~整锅 Casbin~~ | **不做**（策略表 + 函数即可） |
| ~~Kiwi schema 多租户~~ | **不做** |

---

## 4. 权限矩阵（Phase 0 固化目标）

图例：`✓` 允许 · `✗` 拒绝 · `A` 仅 ResourceAcl · `S` 仅 Runner scope/已分配

| Resource / Action | platform admin | org owner/admin | org member | project owner | project member | project viewer | runner |
|---|---|---|---|---|---|---|---|
| org.read / org.manage_members | ✓ | ✓ / ✓ | ✓ / 默认 ✗，策略可邀 member | — | — | — | ✗ |
| org.manage_users / audit(org) | ✓ | ✓ | ✗ | — | — | — | ✗ |
| project.create（属 org） | ✓ | ✓ | 默认 ✗，组织策略可开 | — | — | — | ✗ |
| project.meta.read（列表项） | ✓ | ✓†† | ✗** | ✓ | ✓ | ✓ | ✗ |
| design.read / design.write | ✓ | ✓ / ✓†† | ✗ | ✓ / ✓ | ✓ / ✓ | ✓ / ✗ | ✗ |
| artifact\|job\|schedule\|app.read | ✓ | ✓†† | ✗ | ✓ | ✓ | ✓ | S |
| 同上 .write | ✓ | ✓†† | ✗ | ✓ | ✓ | A | S（进行中） |
| resource_acl.manage | ✓ | ✓†† | ✗ | ✓ | ✓ | A(write) | ✗ |
| device.list（软） | ✓ | org Runner 可见 | 同左 | 忙任务可见项目 | 同 | 同 | 本 runner |

\* **已收紧**：`org:member` 默认不能 `project.create`；组织策略 `members_can_create_projects` 打开后由 `rbac.can()` 额外放行。owner/admin 与平台 admin 不受影响。  
\*\* 默认**不**做「org 下项目元数据对全体 org 成员可见」；若产品要做，须显式开关且**不得**附带内容读。  
†† **仅 org owner/admin**，且仅限该项目 `org_id` 属于其管理的组织；普通 org member 仍 ✗。

矩阵落地形态：Python 常量 `ROLE_POLICIES`（可测）+ 本文表格；单元测试逐格断言 `can(...)`。

---

## 5. 分阶段

### Phase 0 — 矩阵 + 测试固化（本轮必做）

- [x] 文档：本文 + `MULTI_TENANCY.md` 增加指向，避免双真源矛盾
- [x] 可测常量：角色枚举、Resource、Action、默认 deny（`services/rbac.py`）
- [x] 集成测试：仅 org 成员 → 设计/制品/Job 列表空或 403；直链 project 403（`tests/test_org_only_isolation.py`）
- [x] 审计关键列表 API 过滤；明确漏洞则最小修复（`list_reports` 带 `project_id` 补 `assert_can_access_project` → 403）

### Phase 1 — Harbor 式 `can()` + ROLE_POLICIES（本轮必做）

- [x] 新增 `platform/services/rbac.py`：`can(...)` / `ROLE_POLICIES`
- [x] 优先级按 §2.2 实现；org member **不**隐式项目数据读；org owner/admin 提升为本组织项目 owner
- [x] 薄包装：`projects.assert_*` / `organizations.assert_*` / `acl.can_access_resource` 委托 `rbac.can`；`design_access` 经 projects 自动受益
- [x] 测试覆盖矩阵关键单元格（`tests/test_rbac_matrix.py`）

### Phase 2 — 组织治理（时间够做切片）

- [x] org admin/owner 建项目 → 自动首任 project owner（已有；补测试）
- [x] 邀请/加成员：不能提权超过自己（org `add_org_member` + project `add_member` + rank 单测）
- [x] 收紧 org member 建项目默认；组织策略 `members_can_create_projects` / `members_can_invite` + 管理台开关
- [ ] （可选，默认关）org 下列项目「仅元数据」——须与 §2.5 一致，默认不削弱隔离

### Phase 3 — 资源池软隔离（implemented）

外部代码与 REST 统一使用 **`resource_pool`**；UI 中文显示“设备池”。不再并行暴露
`DeviceGroup` 命名。资源池是调度资格与元数据可见性的软隔离层，**不是**新的项目
硬租户列，也不改变 `DeviceRow → RunnerRow` 的事实归属。

**模型与约束**

- `resource_pools(id, org_id, name, description, is_default, enabled, created_at, updated_at)`；
  `(org_id, name)` 唯一。`org_id` 必须引用现有 Organization。
- `resource_pool_runners(pool_id, runner_id)`、`resource_pool_devices(pool_id, device_id)`、
  `resource_pool_projects(pool_id, project_id)` 均以二元组为唯一键；外键删除策略为：
  删除 pool 级联删除授权/成员关系，Runner/Device 注销级联清理成员关系，Project
  删除级联清理授权。不得因删池删除 Runner、Device、Project 或 Job。
- Runner 成员表示该 Runner（以及其可匹配设备）进入池；Device 成员表示单台设备进入池。
  对指定 UDID 的 Job，每个目标设备必须通过“Runner 是成员”或“该 Device 是成员”命中
  至少一个已授权且启用的池；无指定 UDID 的移动 Job 可由池内 Runner，或拥有池内可调度
  Device 的 Runner 领取；Web Job 必须由池内 Runner 领取。
- `is_default` 只是组织内展示/运维标记；MVP 不自动把新 Runner/Device/Project 加入默认池，
  不因 default 将全局资源暴露给项目。创建第二个 default 时原 default 自动取消。

**激活、兼容与失败语义**

- 无 `project_id` 的历史 Job 保持旧调度规则。
- 对有组织的项目：该组织不存在任何启用池，且该项目不存在任何池授权时，视为**旧模式**，
  Runner scope 与原设备匹配逻辑不变（fail-open 仅用于这条明确的存量兼容窗口）。
- 一旦组织存在任一启用池，或项目存在任一池授权，进入**池模式**：只允许“启用池 ∩ 项目授权”
  中的 Runner/Device；项目未授权、授权池停用、成员为空或成员不匹配均 fail-closed，Job
  保持 pending，不能退回全局池。
- 资源池规则与既有 Runner `org_id/project_ids` scope 取交集，任何一层拒绝都不能 claim。
  规则在 claim 前判断，并在设备原子占用前再次体现在候选设备匹配中。
- 手写迁移沿用 `db.py`：新表由 `Base.metadata.create_all` 幂等创建；不改写旧行、不做自动归池。

**权限、列表与删除**

- platform admin：全局旁路；org owner/admin：本组织 pool CRUD、成员与项目授权管理。
- project owner/member/viewer：可读取自己项目已授权的池及必要 Runner/Device 状态，并使用其
  调度资格；均不可管理组织池。viewer 的“使用”仅指其只读可见性，创建/修改 Job 仍受原
  project write 权限限制。
- 普通用户的 `/devices`、`/runners` 仅返回其可访问项目所授权启用池的资源；指定
  `project_id` 时先做项目成员校验。org owner/admin 为管理池可查看本组织候选资源。
  platform admin 仍可全局查看。任何分支都不得泄漏其它组织 Runner/Device 元数据。
- 删除池时，若其成员 Device 正被活动 Job 占用，或成员 Runner 正承载 claimed/running Job，
  返回 409；否则只安全解绑关系并删除 pool。所有创建、修改、删除、成员变更、项目授权变更
  写入现有 audit log。

**API / UI 最小闭环**

- 组织范围 CRUD；Runner/Device 添加与移除；Project 授权与撤销；列池、池内资源及项目可用
  资源。所有管理 API 在后端强制 org owner/admin。
- 设备页提供成熟卡片 + 弹窗式“设备池管理”，至少支持创建、状态查看、绑定
  Runner/Device、授权 Project；前端权限判断只做体验门控。

- [x] `resource_pool` 模型、迁移、API、RBAC 与审计
- [x] 调度 claim / 设备匹配与 devices/runners 列表过滤
- [x] 前端设备池管理与 TS 契约
- [x] 隔离、角色、调度兼容、删除安全测试（`tests/test_resource_pools.py`）
- [x] **不做**：Device 行强制 `project_id` 租户化

### Phase 3.1 — 设备来源、所有权与限时占用

资源池继续只决定“项目可调度哪些资源”；设备来源/所有权是与资源池、Runner
`org_id/project_ids` **取交集**的第二层资格，不把 Device 硬绑定到唯一项目。

**来源与兼容**

- Runner 增加 `registration_source=ide|platform|managed` 与既有
  `owner_user_id` 配套使用；Device 从所属 Runner 继承来源和所有者。
- IDE 使用用户 JWT 预注册 `source=ide`，服务端忽略客户端伪造的 owner 并写入当前
  `user_id`；随后签发当前项目 scoped Runner Token。Runner Token 只能刷新自身登记。
- Platform CLI Runner 为 `platform`；Platform 本机托管进程为 `managed`，均无个人 owner。
- 存量 `owner_user_id` 为空的 Runner/Device 一律按平台共享资源处理；不得根据 hostname
  或 runner_id 前缀猜来源。

**使用与管理**

- IDE 私有设备：仅 owner、platform admin、所属组织 owner/admin 可见、可创建 Job、
  可被该用户 Job claim；同一规则适用于维护、强制释放和注销等管理动作。
- Platform/managed 共享设备：有现有组织/项目/资源池使用资格的用户均可使用；仅
  platform admin 或所属组织 owner/admin 可管理。
- 设备列表、Job 创建校验、claim 候选和原子占用均执行所有权规则；池模式下最终资格为
  `项目池授权 ∩ Runner scope ∩ 设备所有权/来源 ∩ 设备健康/占用状态`。

**独立限时占用**

- `device_reservations` 记录 `device_id/user_id/username/start_at/expires_at/reason/status`
  及释放时间；同一设备同时只允许一个 active 记录。
- API 支持创建占用、查询活动占用、本人停止占用；管理员可强制停止并写审计。
- 创建占用要求该用户具有设备使用权；活动 Job 期间普通用户不能创建占用。活动占用期间
  仅占用人创建的 Job 可 claim，其他人的 Job 保持 pending。
- 到期在设备列表、heartbeat 与 claim 路径惰性扫描释放；无需引入独立调度依赖。
- Job 的 `busy_job_id` 生命周期保持不变：complete ACK 后释放；取消 claimed/running
  Job 仍等待 Runner complete ACK，避免旧进程与新任务并发。独立占用到期或主动停止不
  强杀正在运行的 Job。

- [x] Runner 来源/owner 注册契约与存量兼容
- [x] 列表、Job 创建、claim、设备管理所有权门禁
- [x] 限时占用模型、API、惰性到期、审计
- [x] 设备卡片来源/所有者/剩余时间与占用操作
- [x] 私有/共享、角色、池交集、占用冲突与到期测试

---

## 6. 非目标与兼容性

**非目标**

- 不照搬 GitHub.com / 新建事业部表 / Kiwi schema / 默认 Team / Casbin
- 不大改前端 UI；IDE 仓仅在契约变更时最小改动（本轮预期 **零** IDE 改动）
- 不放宽 CORS；不用裸 `except: pass` 掩盖鉴权失败

**兼容性**

- 现有 JWT / Refresh / Runner Token / `X-Org-Id` 语义不变
- 现有 `project_members` 语义不变（仍是内容可见唯一主路径）
- 对外 REST 路径与状态码保持；内部改为委托 `rbac.can`
- 项目必须有 `org_id`，制品/任务/计划必须有 `project_id`（见 `RBAC_BOUNDARY_CONTRACT.md` §3）

---

## 7. 关键路径挂接顺序（Phase 1，防大爆炸）

1. `rbac.py` 实现 + 矩阵单测  
2. `projects.assert_can_access_project` / `assert_can_write_project` 委托  
3. `design_access`（已调 projects，自动受益）  
4. `acl.can_access_resource` 读路径与项目角色对齐 `rbac`（保留 Runner/ACL 分支）  
5. 冒烟：org-only 隔离 + 既有 `test_design_project_acl` / `test_organizations` / `test_permission_hardening`

---

## 8. UI 人设与编辑职责

后端矩阵见 §2 / §4；前端必须以**普通项目成员**为默认人设，不得把运维 runbook 塞给全体登录用户。

### 8.1 人设映射

| 人设 | 角色映射 | 默认心智 |
|---|---|---|
| 普通用户（最多） | platform `operator` + project `member` / `viewer` | 设计域 + 批跑/报告；不谈运维 |
| 组织管理员 | org `owner` / `admin`（现有 `canManageUsers`） | 项目/成员/用户/审计/设备池 |
| 平台运维 | platform `admin`（`canOps`） | 运维配置、Runner、健康检查、旁路 |

### 8.2 前端能力档（与 API 对齐）

| 档位 | 谁 | UI 行为 |
|---|---|---|
| **view** | 项目成员含 `viewer` | 可看设计/批跑/报告；写控件隐藏或禁用 |
| **edit** | 项目 `member` / `owner`（+ 本组织 owner/admin + platform admin） | 设计写、建 Job、上传制品、计划 CRUD |
| **project-manage** | 项目 `owner`（+ 本组织 owner/admin + platform admin） | 成员/邀请；**无** project `admin` 角色 |
| **org-manage** | org `owner`/`admin`（+ platform admin） | 组织成员、本组织用户/审计、设备池管理 |
| **ops** | 仅 platform admin | 运维配置中心；`openOpsConfig` 禁止非 admin 进入 |

**执行路径 vs 运维路径（设备）**

- 普通用户在 **批跑 / 计划** 内用共享 `DevicePicker`：自动分配（留空）或勾选/手填 UDID；**不**依赖侧栏「设备与执行」。
- 「设备与执行」（池 CRUD、Runner、占用/维护）仅 org-manage / ops。
- 借鉴 AWS Device Farm「选池或指定设备」、DeviceFarmer 多选列表；池管理与任务绑定分离。

项目列表 API 下发 `ProjectOut.my_role`，前端派生 `canViewProject` / `canEditProject` / `canManageProject` / `canOps`。

### 8.3 文案规则

- 普通用户：禁用「启动 Runner / CLI token / 配置 `AP_*` / `/health`」类 runbook；缺 AI Key →「联系管理员配置」
- 平台运维：可保留接入与配置 runbook
- 侧栏平台角色中文化：`operator` → 普通用户；`admin` → 管理员

### 8.4 写路径强制（与 §2 一致）

- 设计域 `batch-delete` / `delete_*`：对**每条**资源做项目写校验
- 写路径**禁止**空 `project_id` / 空 `org_id`（含平台管理员；见契约 §3）
- `POST /orgs`：仅 platform admin（对齐 `ROLE_POLICIES` 的 `org.create`）

---

## 9. 与 MULTI_TENANCY.md 关系

| 文档 | 角色 |
|---|---|
| `MULTI_TENANCY.md` | 历史决策、已完成勾选、账号/邀请/Refresh 等落地记录 |
| **本文** | Org/RBAC **边界、契约、矩阵、分阶段、UI 人设**；实施以本文为准 |

`MULTI_TENANCY.md` §P2/P3 中已勾选的 Organization / Runner scope / 设备过滤仍然有效；本文在其上补齐「策略表 + 统一求值 + org≠project 钉死测试 + UI 人设」。

边界与非法组合以 `RBAC_BOUNDARY_CONTRACT.md` 为准。
