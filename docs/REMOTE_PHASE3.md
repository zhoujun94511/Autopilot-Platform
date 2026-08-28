# 远控 Phase 3

## 链路

- Platform Web → Platform API：原生 WebSocket 优先，REST poll 自动降级。
- Android：scrcpy H.264 → 每个参与者独立 WebRTC PeerConnection；`adb` 可靠
  DataChannel 承载剪贴板、文件、App 与质量命令。
- iOS：WDA MJPEG → WebSocket fan-out；WDA 负责输入/剪贴板，go-ios
  `fsync`/`apps` 负责文件和 App。
- 一台设备只有一个活动主会话；一名 controller，可配置 0–32 名 viewer。
  viewer 可独立协商视频，但不能输入、执行命令或关闭会话。

## TURN

部署模板见 `deploy/docker/coturn/`。Platform 与 coturn 必须使用相同的
`MC_TURN_SECRET` / `TURN_STATIC_AUTH_SECRET`。生产启动会校验：

- `MC_TURN_ENABLED=1`
- `MC_TURN_URLS` 至少包含一个 `turn:` 或 `turns:`
- `MC_TURN_SECRET` 至少 32 字节

会话创建和 Runner 拉令都会收到绑定会话有效期的 coturn
`use-auth-secret` HMAC-SHA1 短时凭证。`GET /health/turn` 执行 STUN Binding
探测；部署冒烟用 `pytest tests/test_remote_turn_optional.py -q`（需 `MC_TURN_ENABLED=1`）。

## 会话 API

- `POST /devices/{id}/remote-sessions`：创建 controller 会话。
- `POST /devices/{id}/remote-sessions/join`：加入 viewer。
- `GET/POST/DELETE /device-remote-sessions/{id}/participants...`：列举、离开、
  强踢、转移控制权。
- `WS /device-remote-sessions/{id}/ws`：统一 signaling/media/command/event。
- `POST /device-remote-sessions/{id}/commands` 与
  `GET .../commands/{request_id}`：REST 命令降级和长任务状态。
- 旧 `offer/answer/ice/signaling-poll/media/media-poll` 保持兼容。

## 文件与 App 边界

- Android 文件根可浏览，但 `/`、`/system`、`/vendor`、`/data`、`/sdcard`
  等关键根路径禁止删除。上传/下载分块、顺序校验、进度和取消均走可靠通道。
- iOS 文件仅限 AFC 媒体根，或启用了文件共享的 App Documents
  （命令参数 `app=bundleId`）；不是任意系统文件浏览。
- Android 支持 APK 安装、签名冲突确认后覆盖、卸载、启动、停止和 base APK
  导出。split APK 当前只导出 base APK。
- iOS 支持 IPA 安装、卸载、启动和终止；非越狱设备不能导出已安装 IPA，
  前端明确显示该平台限制。

## 真机验收

分层覆盖（仓库内不默认跑真机）：

| 层 | 命令 | 门禁 |
|----|------|------|
| L0 白盒 | `pytest tests/test_*remote*.py -q` | CI `remote-phase3` |
| L1 TURN | `pytest tests/test_remote_turn_optional.py -q` | `MC_TURN_ENABLED=1` |
| L2 真机 | `tests/live/remote_live_smoke.py` | `AUTOPILOT_REMOTE_LIVE=1` |
| L3 UI | Vitest；Playwright 有意后置 | — |

本机自动冒烟：

```bat
cd /d <platform-root>
set AUTOPILOT_REMOTE_LIVE=1
set AUTOPILOT_LIVE_ANDROID_UDID=<android-udid>
.\.venv\Scripts\python.exe tests\live\remote_live_smoke.py
```

人工清单见下文。细化步骤：[Android 冒烟](./architecture/DEVICE_REMOTE_ANDROID_SMOKE.md)、[iOS 冒烟](./architecture/DEVICE_REMOTE_IOS_SMOKE.md)、`deploy/docker/coturn/README.md`。

- [ ] WS 断开后浏览器和 Runner 自动转入 HTTP poll，重连后无重复输入。
- [ ] 不同公网/NAT 下 selected candidate 为 `relay`，UDP、TCP、TLS TURN 各测一次。
- [ ] controller + 至少 3 viewer 同时观看；viewer 输入和破坏命令返回 403。
- [ ] controller 强踢 viewer、转移控制权、释放占用后所有 Peer/WDA 会话清理。
- [ ] Android/iOS 剪贴板双向同步；Android “写入并粘贴”行为正确。
- [ ] 双端文件列举、上传、下载、重命名/删除（iOS 按 AFC 能力）、取消和断线恢复。
- [ ] Android APK 全生命周期与导出；签名冲突需要二次确认。
- [ ] iOS IPA 安装/卸载/启动/终止，导出入口显示不支持。
- [ ] Android 手动码率/FPS/宽度/IDR、关键帧和自适应阶梯生效。
- [ ] iOS MJPEG FPS/quality、自适应阶梯和 screenshot fallback 生效。
- [ ] 诊断面板显示码率、FPS、丢包、RTT、ICE pair、解码/丢帧。

## 鉴权与运维 ACL（Phase 3.1）

- Browser WebSocket：**首帧** `type=auth` 携带短时票；query `access_token` 仅兼容。
- Platform admin：**可**关闭/踢人/promote；**不可**仅凭 admin 身份触控或发可靠命令（旁观默认 viewer）。
