# Android 远控真机冒烟清单（Phase 1）

## 前置

1. Platform API 已迁移：`alembic upgrade head`（含 `device_remote_sessions`）
2. Runner 安装远控依赖：`pip install -e ".[runner,runner_remote]"`
3. 本机 `adb devices` 可见目标 Android，并允许 USB 调试
4. Runner 心跳上报该设备；管理台设备卡可见

## 步骤

1. 登录 Platform Web → 设备台
2. 对目标机点 **占用设备**（用途可选「远控预留」或「手工调试」）
3. 卡片出现 **远程调试** → 点击
4. 面板状态依次：创建远控会话 → 等待 Runner → 已连接
5. 画面可见；在画面上点击/滑动，设备有触控响应
6. 关闭远控面板：会话结束，**占用仍保持**
7. 点 **停止占用**：占用释放；若远控未关应一并关闭

## 负面用例

| 场景 | 期望 |
|------|------|
| 未占用直接调 API 开远控 | 403 |
| Job 占用中的设备 | 无法占用 / 无法远控 |
| 非占用人 | 403 |
| 未装 aiortc 的 Runner | 会话 `failed`，错误信息可读 |

## 不验收（本期）

- 跨 NAT（无 TURN）稳定连通
- 多 viewer / 强踢（见 [REMOTE_PHASE3.md](../REMOTE_PHASE3.md) 人工清单）
