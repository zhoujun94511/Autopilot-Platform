# Frontend Architecture Evolution

> Panel / App / capabilities / guards 直连 Pinia；运行时接线在 `composables/platformRuntime.ts`（`wirePlatformRuntime`；`useMcStore.ts` 仅 re-export 兼容旧路径）。

## 切片

| 域 | State | Actions | Pinia |
|----|-------|---------|-------|
| 执行 | `mcExecState` | `mcExecActions` | `useExecStore` |
| 管理 | `mcAdminState` | `mcAdminActions` | `useAdminStore` |
| 运维/ACL | `mcOpsState` | `mcOpsActions` | `useOpsStore` |
| 项目 | `mcProjectsState` | `mcProjectsActions` | `useProjectsStore` / `useContextStore` |
| 会话 | `mcSessionState` | `mcSessionActions` | `useAuthStore` |
| Shell | `mcShellState` | openOpsConfig 等 | `useShellStore` |
| 轮询 | — | `mcPolling` |（由 shell 驱动）|

- `platformRuntime.ts` ≈ **150 行**（仅 bind*Deps + watch 封装 + Router/Pinia 挂载）；`useMcStore.ts` 薄 re-export
- `pageVisible` 已迁至 `mcShellState`
- 产物约 **235KB** gzip ~82KB（以 `npm run build` 为准）

## 已直连

- [x] 全部业务 Panel（Exec / Admin / Ops / Infra / Projects / Design / Dashboard）
- [x] `App.vue`、`LoginView`、`useCapabilities`、`router/guards`
- [x] 删一次性 `tools/patch_*.py`
- [x] 移除 `useMcStore()` 门面导出

## 冒烟清单

1. 登录 / 登出 / SSO  
2. Tab 切换 + 按需刷新  
3. Org/Project 切换与 invite  
4. Design 全路径 + enqueue  
5. Exec / Infra / Admin 深链路  
6. 轮询与 KeepAlive  

## 白盒回归

- `tests/test_aud_p2_009_frontend_whitebox.py`（Tab/Router/guards/Shell/Polling/runtime 接线、ops 深链、项目过滤行为镜像、Panel Pinia 正向清单、SPA 深链运行时）  
- 另有 `test_frontend_auth_timing` / `test_frontend_persona_capabilities` 已对齐 `mcSessionActions` / `mcShellState`

## 可选后续

1. ~~本文件可重命名为 `platformRuntime.ts`~~（已完成）；`main.ts` import `wirePlatformRuntime`。  
2. `useCapabilities` 改读 `mc*State` 或 Pinia 实例（若未来 SSR/测试需要）  

## 通知分层

见 [`NOTIFY.md`](./NOTIFY.md) / `src/composables/useNotify.ts`：列表错误 → `notify`；表单校验 → 局部 `xxxMsg`；不全局统一。
