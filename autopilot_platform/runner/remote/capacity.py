"""远控容量与冷启动限流（对齐 STF / ws-scrcpy 分设备并行 + 冷启动队列）。"""

from __future__ import annotations

import os
import threading


def max_concurrent_remote() -> int:
    try:
        return max(1, min(32, int(os.getenv("AUTOPILOT_MAX_CONCURRENT_REMOTE", "4"))))
    except (TypeError, ValueError):
        return 4


def cold_start_limit() -> int:
    try:
        return max(1, min(8, int(os.getenv("AUTOPILOT_REMOTE_COLD_START_LIMIT", "2"))))
    except (TypeError, ValueError):
        return 2


class ColdStartGate:
    """限制同时进行的 scrcpy 冷启动数，避免多设备同时 push/建连打满 adb。"""

    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._sem: threading.Semaphore | None = None
        self._limit = 0

    def _ensure(self) -> threading.Semaphore:
        limit = cold_start_limit()
        with self._guard:
            if self._sem is None or self._limit != limit:
                self._limit = limit
                self._sem = threading.Semaphore(limit)
            return self._sem

    def acquire(self, *, timeout: float = 120.0) -> bool:
        sem = self._ensure()
        return sem.acquire(timeout=max(0.1, float(timeout)))

    def release(self) -> None:
        sem = self._sem
        if sem is not None:
            sem.release()


COLD_START_GATE = ColdStartGate()
