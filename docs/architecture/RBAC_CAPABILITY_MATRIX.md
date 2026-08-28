# RBAC 能力矩阵

**边界真源**：[`RBAC_BOUNDARY_CONTRACT.md`](./RBAC_BOUNDARY_CONTRACT.md)

**能力 ID / UI 映射**（与 AutoPilot 仓同步）：

兄弟仓 `AutoPilot/docs/rbac-capability-matrix.md`

Platform 实现映射：

- 后端：`autopilot_platform/platform/services/rbac.py`、`tenancy/projects.py`
- 前端：`autopilot_platform/frontend/src/composables/useCapabilities.ts`
- 测试：`tests/test_rbac_caps.py`、`tests/test_rbac_boundary_contract.py`
