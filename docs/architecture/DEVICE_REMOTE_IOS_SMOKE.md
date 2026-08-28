# iOS 远控真机冒烟清单

前置：Android 远控 MVP 已可跑；本机 Runner 能 `IosDevicePrep.prepare()`（隧道 + WDA + 9100 MJPEG）。

1. Runner 心跳 capabilities 含 `ios` / `ios-remote`（或 `ios-wda`）
2. Web 占用一台 iOS 设备 → 卡片出现「远程调试」
3. 打开远控：会话 `pending` → Runner 拉令 → `ready` → 出现画面（`connected`）
4. 点击 / 滑动：设备有响应；关闭远控后占用仍在
5. 释放占用：远控会话自动关闭
6. 负向：非占用人无法 `media-poll` / 关闭他人会话

可选：`pytest tests/test_remote_link_whitebox.py tests/test_device_remote_sessions.py -q`
