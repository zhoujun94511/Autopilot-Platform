"""Per-device 串行 ADB 命令执行，避免阻塞 WebRTC 事件循环与会话 poll 线程。"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Callable

_log = logging.getLogger(__name__)

_guard = threading.Lock()
_executors: dict[str, ThreadPoolExecutor] = {}

# 与 scrcpy 冷启动/重配共用 per-device 锁，避免 pm/dumpsys 与 jar push 交错。
_SHELL_HEAVY_PREFIXES = ("app.", "file.")


def _executor_for(device_id: str) -> ThreadPoolExecutor:
    key = device_id.strip()
    with _guard:
        pool = _executors.get(key)
        if pool is None:
            pool = ThreadPoolExecutor(
                max_workers=1,
                thread_name_prefix=f"adb-cmd-{key[:8]}",
            )
            _executors[key] = pool
        return pool


def _uses_scrcpy_lock(event_type: str) -> bool:
    return any(event_type.startswith(prefix) for prefix in _SHELL_HEAVY_PREFIXES)


def submit_adb_dispatch(
    device_id: str,
    *,
    event_type: str,
    work: Callable[[], None],
) -> None:
    """将会话/adb DataChannel 上的 dispatch 投递到设备专用 worker。"""

    def _run() -> None:
        try:
            if _uses_scrcpy_lock(event_type):
                from .scrcpyclients import _reconfigure_lock_for

                with _reconfigure_lock_for(device_id):
                    work()
            else:
                work()
        except Exception as exc:  # noqa: BLE001
            _log.exception(
                "adb dispatch failed device=%s type=%s: %s",
                device_id,
                event_type,
                exc,
            )

    _executor_for(device_id).submit(_run)


def flush(device_id: str, timeout: float = 30.0) -> None:
    """等待该设备队列中已提交任务完成（测试/诊断用）。"""
    future: Future[None] = _executor_for(device_id).submit(lambda: None)
    future.result(timeout=timeout)


def shutdown_device(device_id: str, *, wait: bool = False) -> None:
    key = device_id.strip()
    with _guard:
        pool = _executors.pop(key, None)
    if pool is None:
        return
    pool.shutdown(wait=wait, cancel_futures=not wait)
