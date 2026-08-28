# Device Remote — 容量与预热（2026-08）

> 对齐成熟设备云（STF 每设备 worker、ws-scrcpy adb 先暖、BrowserStack slot 上限）的 **轻量落地**，不引入微服务拆分。

## 环境变量

| 变量 | 默认 | 作用 |
|------|------|------|
| `AUTOPILOT_MAX_CONCURRENT_REMOTE` | `4` | Runner 同时拉起的远控会话数（本地 spawn 上限） |
| `AUTOPILOT_REMOTE_COLD_START_LIMIT` | `2` | 同时 scrcpy 冷启动（push + 建连）上限 |
| `MC_MAX_REMOTE_SESSIONS_PER_RUNNER` | `4` | Platform 单 Runner active 远控会话上限；`0`=不限制 |

## 行为

### 1. adb 先暖（ws-scrcpy-web）

Runner 远控 sync 前调用 `ensure_adb_daemon()`，避免多 worker 同时 `adb start-server`。

### 2. 占用后 soft prewarm（STF 设备托管轻量版）

- Platform：`GET /api/v1/runners/me/remote-prewarm-hints` 返回 **已占用、尚无 active 远控** 的设备。
- Runner 心跳/远控 sync 周期拉取并：
  - **Android**：`peek_client` 存活则跳过；否则仅确保 jar（sha256 一致不 push）。
  - **iOS**：`runtime + mjpeg_alive` 就绪则跳过；未就绪不并行 prep（防双开 WDA）。

### 3. 冷启动队列

`scrcpyclients.get_client()` 慢路径受 `ColdStartGate` 限流；fast path（已 alive）不受限。

### 4. Runner 并发 defer

`RemoteSessionHub.sync` 本地 session 数 ≥ `AUTOPILOT_MAX_CONCURRENT_REMOTE` 时 **defer** 新 spawn；Platform 侧会话保持 `pending`，下轮 sync 再拉。

### 5. Platform 并发拒绝

创建远控时若 Runner 已有 ≥ `MC_MAX_REMOTE_SESSIONS_PER_RUNNER` 条 active 会话，返回 403。

## 运维建议（Sonic / STF 共识）

- 单 Managed Runner：**建议 ≤4 路 Android 同时远控**；8+ 台请拆 Runner 或错开打开。
- USB：**USB3 有线 hub**，避免无线 adb 占满带宽。
- iOS 多路：注意 Platform **MJPEG 中继**带宽；优先控制并发路数。

## 日志关键字

```
[runner] adb daemon ready
[runner] soft-prewarm android jar ready udid=...
[runner] remote capacity defer n=2 (active=4/4)
[runner] remote spawn sid=... (2/4)
```

## 相关代码

- `runner/remote/capacity.py` — 上限与 ColdStartGate
- `runner/remote/prewarm.py` — adb / soft prewarm / scrcpy prewarm
- `runner/remote/hub.py` — defer spawn
- `platform/services/remote/sessions.py` — prewarm hints + Platform 上限
