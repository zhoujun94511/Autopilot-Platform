# Device Remote — Android MVP（C1 解冻说明）

> 状态：Android / iOS MVP 已交付  
> 关联：[`PRODUCT_SURFACE_AND_REFERENCE_PLAN.md`](./PRODUCT_SURFACE_AND_REFERENCE_PLAN.md) C1；iOS 见 [`DEVICE_REMOTE_IOS_PHASE2.md`](./DEVICE_REMOTE_IOS_PHASE2.md)

## 业务刚需

设备台已支持限时占用（手工调试 / 远控预留 / 演示联调）。缺浏览器内画面与触控时，占用只能「占住不给别人用」，无法完成调试与演示。成熟设备云（DeviceFarmer / BrowserStack Live）均以 Web 远控为主入口。

## 边界（不影响 C-RBAC / C-OWN / C-DUAL）

| 角色 | 职责 |
|------|------|
| Platform Web | 远控 UI 入口（占用后「远程调试」） |
| Platform API | 会话创建、占用人鉴权、短时票、信令中继、审计 |
| Platform Runner | USB 侧 scrcpy /（二期）WDA；WebRTC 或 MJPEG |
| AutoPilot IDE | **不**做云远控入口；本地 Inspector 镜像保留 |

## API 约定

- `POST /api/v1/devices/{device_id}/remote-sessions` — 占用人或 platform admin；`busy_kind=job` 拒绝
- `DELETE /api/v1/device-remote-sessions/{session_id}`
- `GET /api/v1/device-remote-sessions/{session_id}`
- 信令中继：`POST .../offer|answer|ice`，`GET .../signaling-poll`
- 媒体旁路（iOS MJPEG）：`POST .../media`，`GET .../media-poll`（与 SDP 队列隔离）
- Runner：`GET /api/v1/runners/me/remote-commands`（pending 会话）
- 短时票：`typ=device_remote`，claims：`session_id`、`device_id`、`runner_id`
- 审计：`device.remote_session_start` / `device.remote_session_stop`
- Capability：`cap.devices.remote`（authenticated + 服务层占用人校验）

## 分期

1. Android：scrcpy H.264 → WebRTC passthrough + DataChannel 触控 — **done（MVP）**
2. iOS：同一会话模型；WDA MJPEG + WDA 控制（设备层对齐 AutoPilot `IosDevicePrep`）— **done（MVP）**；见 [`DEVICE_REMOTE_IOS_PHASE2.md`](./DEVICE_REMOTE_IOS_PHASE2.md)
3. TURN / 多 viewer / 质量档硬化
