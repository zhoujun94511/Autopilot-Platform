# iOS 远控（Phase 2）

> 状态：implemented（与 Android 同会话模型；画面为 WDA MJPEG media 旁路）

## 已具备

- Platform `device_remote_sessions` 对 `platform=ios`：`capabilities: mirror, control, mjpeg, ios-wda`
- media 旁路（与 SDP 隔离）：`POST .../media`、`GET .../media-poll`（`frame` / `input`）
- Runner [`runner/remote/ios/session.py`](../../autopilot_platform/runner/remote/ios/session.py)：`IosDevicePrep` → MJPEG 切帧推送 → `WdaClient` 触控
- 公共组件 [`runner/remote/shared/`](../../autopilot_platform/runner/remote/shared/)：会话协议 / Platform 通道 / 坐标 / frame 载荷
- 多设备隔离：复用 `ap.runtime.device_runtime` 端口族，为每个 UDID 分配独立 tunnel / WDA / MJPEG 端口
- Web [`RemoteDeviceDialog.vue`](../../autopilot_platform/frontend/src/components/RemoteDeviceDialog.vue)：`capabilities` 含 `mjpeg` 时走 `<img>` + media-poll

## 设备层真源

| 能力 | Platform 路径（与 AutoPilot 契约同步） |
|------|----------------------------------------|
| 隧道 / runwda / forward | `ap/mobile/ios_bootstrap.py` → `IosDevicePrep` |
| WDA HTTP | `ap/keywords/mobile/wda_client.py` |
| MJPEG 切帧 | `runner/remote/ios/mjpeg_reader.py`（对齐 IDE `mjpeg_source.split_jpegs`） |

**禁止**从 WebAppFlaskauto-iOS 再抄第三套 `IOSAdapter`；禁止把 Qt Inspector 塞进 Platform Web。

## 冒烟

见 [`DEVICE_REMOTE_IOS_SMOKE.md`](./DEVICE_REMOTE_IOS_SMOKE.md)。

## 未纳入本期

- WebRTC 转码 iOS 画面
- TURN / 多 viewer（与 Android Phase 3 一并）
