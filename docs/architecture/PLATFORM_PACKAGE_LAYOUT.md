# Platform 包结构收敛计划

> **目标**：消除 `platform/` 根目录业务模块与 `services/` **双轨并存**，按职能收敛为 Python 包。  
> **原则**：真源进包、搬家与业务改动分离、一次一域；Phase 6 后根目录不再留业务 shim。  
> **关联**：领域边界见 `DOMAIN_BOUNDARIES.md`；权限边界见 `RBAC_BOUNDARY_CONTRACT.md`。

**修订**：2026-08-21

---

## 0. 历史问题（已收敛）

| 原现象 | 现状 |
|--------|------|
| 根目录 ~40 个 `.py` 平铺 | 根仅启动 + `auth`；业务进包 |
| 同职能分裂（projects vs organizations） | `tenancy/` 统一入口 |
| 基础设施与领域混杂 | `core/` / `ops/` / `identity/` / `design/` |

---

## 1. 目标形态

```text
platform/
├── app.py / __main__.py / routes.py / auth.py / __init__.py
├── core/           # db, settings, models, env_file, security, api_messages, error_handlers, metrics, login_rate
├── ops/            # alerts, notify, runtime_*, scheduler_loop, audit
├── identity/       # oidc, saml, session_tokens, refresh_cookie, ide_handoff
├── design/         # design_models, design_schemas, intent_normalize, rag_context
├── authz/          # acl + rbac 真源
├── tenancy/        # projects + organizations + project_invites 真源
├── artifacts/      # users_artifacts, app_builds, storage, manifest, quality, upload, app_meta
├── ai/             # ai_client, ai_config, ai_case_generator, ai_requirements_analyze
├── api/            # 按域路由
├── services/       # shared / design / execution / remote / reports / observability
└── rag/            # 已成包
```

根目录**不再**保留业务 shim；旧路径需改为真源包路径。

### 边界约定

| 包 | 是什么 | 不是什么 |
|----|--------|----------|
| `tenancy/` | 组织/项目/成员可见性入口 | 不放 Job/设计内容 CRUD |
| `authz/` | 资源 ACL + RBAC 策略求值 | 不放登录协议细节（仍 `auth.py`） |
| `artifacts/` | 制品/应用包/存储/清单/质量 | 不放用户登录主流程长期目标（`users_artifacts` 暂整文件迁入，日后再拆 users） |
| `ai/` | LLM 客户端与生成/分析 | 不放 HTTP 路由（仍在 `api/design`） |
| `services/` | 执行与设计域业务服务 | 不再接收「组织/ACL/制品存储」新模块 |
| 根目录 | 仅启动装配与 `auth.py` | **禁止新增业务模块** |

---

## 2. Import 契约（Phase 6 后）

- 新代码只写真源路径：`tenancy.projects` / `authz.rbac` / `core.db` /
  `ops.notify` / `identity.session_tokens` / `services.execution.jobs` 等。
- 根级旧模块名（`platform.projects`、`platform.db`…）**已删除**，不要再依赖。
- `services.__init__` 不提供聚合 facade；禁止使用已删除的
  `services.jobs`、`services.devices`、`services.runners` 等扁平路径。
- 后续若需兼容外部脚本，可再加薄 shim；默认保持根目录干净。

---

## 3. 分阶段 Todo（实施顺序）

| Phase | 内容 | 验收 |
|-------|------|------|
| **0** | 本文档 + MULTI_TENANCY / DOMAIN 交叉引用；根目录冻结说明 | 文档可查 |
| **1** | `tenancy/`：迁 `projects.py`；`__init__` re-export organizations | pytest 绿 |
| **2** | `authz/`：迁 `acl.py`；re-export `services.rbac` 关键符号 | pytest 绿 |
| **3** | `artifacts/`：迁 users_artifacts / app_builds / storage / manifest / quality / upload* | pytest 绿 |
| **4** | `ai/`：迁 ai_* | pytest 绿 |
| **5** | `schedules.py` → `services/schedules.py` | 与 jobs 同层 |
| **6** | `core/` / `ops/` / `identity/` / `design/`；删根 shim；全仓改 import | 根 `ls` 干净；pytest 绿 |

**明确不做（仍开放）**：拆 `users_artifacts`、`auth` 入 `authz`、改 HTTP 路径、改业务权限语义。

---

## 4. 风险与回滚

| 风险 | 缓解 |
|------|------|
| 相对 import 深度错误 | 迁入后统一包路径；全量 pytest |
| 循环依赖 | `auth` 暂留根 |
| 外部脚本硬编码旧路径 | 文档约定改真源路径；必要时再加薄 shim |
| 回滚 | 还原包目录 + 恢复原文件 |

---

## 5. 落地状态

| 项 | 状态 |
|----|------|
| Phase 0 文档 | **done** — 本文 + DOMAIN/MULTI_TENANCY 交叉引用 + `platform/__init__.py` 冻结说明 |
| Phase 1 tenancy | **done** — `tenancy/projects.py`；根 `projects.py` 模块别名 shim；`organizations` 惰性 re-export |
| Phase 2 authz | **done** — `authz/acl.py`；根 `acl.py` shim；`rbac` 惰性 re-export |
| Phase 3 artifacts | **done** — users_artifacts / app_builds / storage / manifest / quality / upload* |
| Phase 4 ai | **done** — ai_client / ai_config / ai_case_generator / ai_requirements_analyze |
| Phase 5 schedules→services | **done** — 现真源 `services.execution.schedules` |
| Phase 6 core/ops/identity/design + deshim | **done** — 根仅 `app`/`auth`/`routes`/`__main__`/`__init__` + 包目录 |
| Services 领域拆包 | **done** — shared/design/execution/remote/reports/observability；身份、租户、权限、运维真源归位 |
| 验证 | 全量 pytest；OpenAPI 契约、前端 typecheck/test/build；`python tools/check_types.py`（platform 闸门） |

一次性搬家脚本已退役，只读归档在 `archive/platform_package_converge/`（顶部 `SystemExit`，不可重放）。
类型检查：默认 `include = ["autopilot_platform/platform"]`；`ap/`、`runner/` 用 `python tools/check_types.py --runtime`。
