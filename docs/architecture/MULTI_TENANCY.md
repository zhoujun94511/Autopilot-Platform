# 多租户与账号体系策略

> **权限边界真源**：[`RBAC_BOUNDARY_CONTRACT.md`](./RBAC_BOUNDARY_CONTRACT.md)。  
> **前瞻分期 / 资源池**：见 [`ORG_RBAC_PLAN.md`](./ORG_RBAC_PLAN.md)。  
> **代码包结构收敛**：见 [`PLATFORM_PACKAGE_LAYOUT.md`](./PLATFORM_PACKAGE_LAYOUT.md)（`tenancy`/`authz`/`artifacts`/`ai` + 根 shim）。  
> 本文保留历史决策与落地勾选。冲突时改本文对齐边界契约。

## 1. 现状判断

Autopilot-Platform 今天是**单部署实例上的「项目空间软多租户」**：

| 层 | 现状 | 评价 |
|---|---|---|
| 平台用户 | 全局 `users` + `admin`/`operator`；bootstrap `admin/admin` | 像 demo：无邀请、无刷新令牌、无吊销 |
| 项目空间 | `projects` + `project_members`（owner/member） | 执行域（制品/Job/计划）已门禁 |
| 资源 ACL | `resource_acl` 跨项目分享 | 可用 |
| 设计域 | 仅有 `project_id` 字段过滤 | **未校验成员 → 跨项目可读可写（P0 必修）** |
| Org/Tenant | **无** | 用户名全局唯一，不适合多客户 SaaS |
| 设备/Runner | 全局池 | 符合实验室共享；非租户隔离 |

结论：账号/登录管理偏引导级；**真正要先打通的是「项目成员 → 设计域 → 制品/Job/IDE」同一套可见性**，再决定是否上 Organization。

## 2. 成熟参考（选型，不照搬整仓）

| 参考 | 可借鉴点 | 链接 |
|---|---|---|
| **org-manager**（FastAPI） | `organizations` + `memberships(role)`；`require_role()` 挂在路由 Depends，禁止业务里散落 if | https://github.com/AmroYasser/org-manager |
| **WorkOS Org RBAC 模式** | JWT 带**当前 org 上下文**；角色按 org 作用域，勿假设全局 admin=各租户 admin | https://workos.com/blog/rbac-authorization-python-apis-workos |
| **FastAPI + PG 真实多租户文** | 每表 `tenant_id`、查询默认过滤、配额原子计数 | https://dev.to/martin_palopoli/real-multi-tenancy-with-fastapi-and-postgresql-plans-quotas-and-data-isolation-36ah |
| **本仓已有** | `assert_can_access_project` / `visible_project_filter` / `acl.can_access_resource` | `platform/projects.py`、`platform/acl.py` |

推荐原则（对齐 org-manager + WorkOS）：

1. **鉴权依赖结构化**：`require_auth` → `require_user` → `require_project_member(project_id)`，路由级强制，业务服务不自行「忘记校验」。
2. **列表默认 deny-by-default**：非 admin 未指定项目时，只返回**可见项目**并集，禁止全库枚举。
3. **角色分两层**：平台角色（`admin`/`operator`）≠ 项目角色（`owner`/`member`/`viewer`）；日后 org 角色再叠一层。
4. **不做 schema-per-tenant**（除非明确做多客户 SaaS）；当前产品定位是**企业内统一平台 + 项目空间**。

## 3. 目标形态（推荐）

```
Platform Instance（单中心）
├── platform_users          # 全局账号（可对接 OIDC/SAML）
├── organizations（可选 P1） # 租户/事业部；成员 org_role
│     └── projects          # 现有项目空间；成员 project_role
│           ├── design_*    # 需求/逻辑用例/知识/文档
│           ├── artifacts / jobs / schedules
│           └── resource_acl
└── shared device pool      # 默认全局；P2 可挂 org 配额
```

**默认产品选择（建议确认）：**

- **A. 企业内软多租户（推荐默认）**：强化「项目 = 隔离边界」；Organization 可选（多事业部）。
- **B. 多客户 SaaS**：必须上 `tenant_id`、用户名租户内唯一、设备按租户隔离——工作量大，单独立项。

本文后续阶段按 **A** 编写；若选 B，阶段表需重排。

## 4. 打通「项目链路」（端到端）

目标闭环：

```
登录 → 选择/创建项目 → 设计域读写（仅成员）
  → APPROVED 导出 → IDE 导入（同 project_id）
  → 制品上传（成员门禁）→ Job（成员门禁）→ result 回写 automation_status
```

| 环节 | 门禁要求 |
|---|---|
| 设计域 CRUD / generate / export / stats | `assert_can_access_project`；列表按可见项目 |
| 文档上传 | 强制 `project_id` + 成员 |
| IDE `export` / `PATCH automation_status` | 同项目成员（或平台 admin） |
| 制品 / Job / 计划 | 已有，保持 |
| 顶栏 `filterProjectId` | 设计面板无项目时阻断写操作并提示 |

## 5. 分阶段实施

### P0 — 项目链路打通与设计域隔离（本轮）

- [x] 文档：本策略
- [x] `services/design_access.py`：统一 `ensure_project_access` / `resolve_list_scope`
- [x] 设计域全部 API 接入；禁止非 admin 全库列表
- [x] 跨项目 403 冒烟测试
- [x] 前端设计面板：无当前项目时提示并禁用生成/上传

### P1 — 账号与成员体验去 demo 化

- [x] 邀请链接 + 自助注册入项
- [x] 项目角色 `viewer`
- [x] 基础密码策略（≥8 且字母+数字；bootstrap 除外）
- [x] Access + Refresh Token（`/auth/refresh`、`/auth/logout`；改密吊销全部 refresh）
- [x] 前端：项目下拉 + 当前项目 localStorage 持久化
- [x] 前端：refresh 持久化；API 401 自动续期

### P2 — Organization（可选）

- [x] 表：`organizations`、`organization_members`
- [x] `projects.org_id`；请求头 `X-Org-Id`（或 JWT claim `org_id`）校验组织成员
- [x] Org CRUD / 成员 API：`/api/v1/orgs*`
- [x] 项目列表按组织过滤；创建项目归属当前组织
- [x] 前端：顶栏 `OrgSelect` + `mc_filter_org_id`；项目页 `OrgPanelCard`
- [x] 用户管理下沉：org admin（`X-Org-Id`）可创建/列表/改密/禁用本组织用户；删除仍仅平台 admin
- [x] 审计带 `org_id`（写入 + 列表过滤；org admin 只读本组织）

参考实现骨架对齐 org-manager 的 membership + `require_role` Depends。

### P3 — 硬化与配额

- 登录限速改为 Redis；JWT 密钥强制非默认
- [x] Runner Token 可绑 `org_id`/`project_id` 范围（`runners.org_id` / `project_ids_json`；claim 跳过越权；`PATCH /runners/{id}/scope`）
- [x] 设备池可见性：平台 admin 看全部；多组织时非 admin 仅见本 org 绑定 Runner / 可见项目关联设备（无组织表时不限制）
- [x] Phase 3 资源池软隔离：`resource_pool` + 项目授权；池模式下 fail-closed claim；无池存量兼容（详见 `ORG_RBAC_PLAN.md`）
- [x] 生产 Token 拆分：`MC_ENV=production` / `MC_REQUIRE_ADMIN_API_TOKEN` 启动强警告；有 ADMIN token 时全局 `MC_API_TOKEN` 仅为 runner
- [x] `ops_admin` 扩展点（`is_ops_admin` / `require_ops_admin`）；当前仍等同 platform admin，文档标明后续可拆

## 6. IDE 对齐

- [x] 登录后缓存 `project_id`（单项目自动选；多项目登录门禁选择）
- [x] 导入/上传/Job 强制带缓存项目；禁止目录名回退与静默 `ensure_project`
- [x] 无项目成员 / 403：明确报错；状态回写无项目则跳过并提示
- [x] 可选 `mc_org_id` → 请求头 `X-Org-Id`
- [x] 不在 IDE 复制用户表（仍仅 HTTP 客户端）

## 7. 明确不做（短期）

- 不合 IDE 仓
- 不引入第二套 Flask 用户系统
- 不默认上 schema-per-tenant / 每客户独立库
- 不把设备池强行拆成多套物理集群（除非 P3 明确需求）

## 8. 已确认决策（2026-07-22）

1. **默认 A：企业软多租户**（项目空间隔离；不上 SaaS schema-per-tenant）
2. **邀请 + 自助注册入项：是**（`project_invites`；开放注册仅限有效邀请）
3. Organization：**P2 基础已落地**（软隔离层；org admin 管用户 / 审计 org_id 仍可深化）
4. Refresh Token：**已落地**（Access 短时 + Refresh 轮换/吊销）

### P2 落地（本轮）

- [x] `organizations` / `organization_members`；`projects.org_id`
- [x] `/orgs` CRUD + 成员；`X-Org-Id` 门禁；项目按组织过滤
- [x] 前端 `OrgSelect` / `OrgPanelCard`；`tests/test_organizations.py`
- [x] org admin 管本组织用户（`/auth/users` + `X-Org-Id`）；审计 `org_id`
- [x] `tests/test_org_user_admin.py`

### P1 落地（本轮）

- [x] `project_invites` 表 + 创建/列表/撤销/预览/接受/自助注册 API
- [x] 项目角色 `viewer`（只读）；写操作走 `assert_can_write_project`
- [x] 前端：`ProjectInviteCard` / `InviteAcceptCard`（`?invite=`）
- [x] 冒烟：`tests/test_project_invites.py`
- [x] 顶栏 `ProjectSelect` + `mc_filter_project_id` 持久化
- [x] `validate_password_policy`（建用户/改密/邀请注册）
