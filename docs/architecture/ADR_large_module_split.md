# ADR：巨型模块渐进拆分（AUD-2026-12 / AUD-2026-17）

## 状态

**DEFERRED（渐进中）** — 维护性债务；禁止整文件行为重写。按文件渐进拆分。

| 审计 ID | 模块 | 约 LOC | 策略 |
|---------|------|--------|------|
| AUD-2026-12 | `frontend/.../DesignChatPanel.vue` 等 1k+ SFC | 见下 | 抽 composable / 子组件 |
| AUD-2026-17 | IDE `ui/main_window/mgmt*.py` | 见下 | Mixin 按主题拆分 |

## AUD-2026-12 进度

| Wave | 内容 | 状态 |
|------|------|------|
| **1** | `DesignChatPanel`：`chatFabPosition` + `useDesignChatFab` + `useDesignChatSessions` | **done** |
| **2** | `DesignChatMessages` / `DesignChatComposer` + `chatMessageDisplay` | **done** |
| **3** | `DesignChatSessionList` 会话侧栏 | **done** |
| **4** | `DevicesPanel`：`deviceDisplay` + `useDeviceBoardFilters`；`OpsPanel`：`opsHealthRows` | **done** |
| **5** | `DeviceBoardCards` / `DeviceBoardTable`；`OpsHealthOverview` | **done** |

## AUD-2026-17 进度

| Wave | 内容 | 状态 |
|------|------|------|
| **1** | `mgmt_delivery.py`：投递/上传/HTTP；`mgmt_errors.py` | **done** |
| **2** | `mgmt_session.py`（登录/会话 UI）+ `mgmt_runner_web.py`（本机 Runner / 打开网页）；`mgmt.py` 仅入口薄壳 | **done** |

混入链：

```text
MainWindow
  → MgmtMixin
  → MgmtSessionMixin
  → MgmtRunnerWebMixin
  → MgmtDeliveryMixin
```

窗口仍只 `from .mgmt import MgmtMixin`；公开方法名不变。

## 决策

1. **接受**剩余体积，优先契约稳定。  
2. **禁止**为降 LOC 改公共 API 或顺手改行为。  
3. **允许**：Mixin 继承链拆文件；Vue 抽 `utils/` / `composables/` / 子 SFC。  
4. **重开条件**：多特性并行冲突，或单测无法落点。

## 已知清单（基线，非硬上限）

Platform Console：

- `components/design/DesignChatPanel.vue`
- `components/OpsPanel.vue`（Wave 4–5：`utils/opsHealthRows.ts` + `OpsHealthOverview.vue`）
- `components/DevicesPanel.vue`（Wave 4–5：`deviceDisplay` / `useDeviceBoardFilters` / `DeviceBoardCards` / `DeviceBoardTable`）
- `components/design/DesignCasesPanel.vue`
- `App.vue`
- `components/JobCreatePanel.vue`
- `components/ReportsPanel.vue`

IDE：

- `autopilot/ui/main_window/mgmt.py`（入口薄壳）
- `autopilot/ui/main_window/mgmt_session.py`
- `autopilot/ui/main_window/mgmt_runner_web.py`
- `autopilot/ui/main_window/mgmt_delivery.py`
- `autopilot/ui/main_window/mgmt_errors.py`

门禁：`tests/test_aud_large_module_inventory.py` 校验本 ADR 与路径仍存在。
