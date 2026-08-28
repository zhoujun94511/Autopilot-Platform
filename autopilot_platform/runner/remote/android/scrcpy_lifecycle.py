"""scrcpy 生命周期钩子（Platform 精简版）。

WebAppFlaskscrcpy 经 Socket.IO 广播 scrcpy_status；Platform 远控改由
DeviceRemoteSession 状态机表达，此处仅挂本地日志，避免死导入 ``services``。
"""

from __future__ import annotations

import logging
from typing import Any

from .scrcpyconst import EVENT_DISCONNECT, EVENT_INIT

_log = logging.getLogger(__name__)


def attach(client: Any, device_id: str) -> None:
    if client is None or not hasattr(client, "add_listener"):
        return

    def _on_init(_payload: Any = None) -> None:
        _log.info("scrcpy init device=%s", device_id)

    def _on_disconnect(_payload: Any = None) -> None:
        _log.warning("scrcpy disconnect device=%s", device_id)

    try:
        client.add_listener(EVENT_INIT, _on_init)
        client.add_listener(EVENT_DISCONNECT, _on_disconnect)
    except (AttributeError, TypeError, RuntimeError) as exc:
        _log.debug("scrcpy_lifecycle attach skipped: %s", exc)
