# 一次性包收敛脚本（已退役）

这些脚本已经跑过，**禁止再执行**。再跑会按过时路径写回 shim
（例如 `services/schedules.py`），破坏当前
`services.execution` / `identity` / `tenancy` / `authz` 真源布局。

当前布局以 `docs/architecture/PLATFORM_PACKAGE_LAYOUT.md` 为准。

| 脚本 | 当时用途 |
|------|----------|
| `converge_platform_packages.py` | Phase 1–5：根模块迁入 tenancy/authz/artifacts/ai，并把 schedules 平铺进 services |
| `converge_platform_phase6.py` | Phase 6：core/ops/identity/design 搬家并去 shim |
| `rewrite_platform_shims.py` | 根目录 shim 改 alias |
| `fix_package_imports.py` | 收敛后相对导入修补（仍含旧扁平 sibling 名） |
| `fix_services_sibling_imports.py` | 把 services 内部 import 改回旧 sibling 名 |
| `fix_phase6_leftover_imports.py` | Phase 6 后残留 `from platform import X` |
| `fix_session_factory_access.py` | `_SessionLocal` → `session_factory` |

每个 `.py` 文件顶部已 `SystemExit`，直接运行会立即失败。

若只是对照历史改写逻辑，只读即可；不要去掉保护后对当前树重放。
