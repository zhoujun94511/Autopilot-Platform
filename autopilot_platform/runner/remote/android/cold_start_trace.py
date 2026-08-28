"""Android 远控冷启动耗时追踪（Runner 侧）。

日志前缀 ``[runner] remote-cold``，便于在 ``managed-runner.log`` 中 grep。
默认关闭；设置 ``MC_REMOTE_COLD_TRACE=1`` 开启。
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

_log = logging.getLogger(__name__)
_local = threading.local()


def enabled() -> bool:
    val = (os.environ.get("MC_REMOTE_COLD_TRACE") or "0").strip().lower()
    return val in ("1", "true", "yes", "on")


class ColdStartTrace:
    """单次远控会话的 monotonic 计时器。"""

    def __init__(self, session_id: str, udid: str) -> None:
        self.session_id = (session_id or "")[:12]
        self.udid = (udid or "")[:16]
        self._t0 = time.monotonic()
        self._last = self._t0
        self._marks: list[dict[str, Any]] = []

    def mark(self, phase: str, **detail: Any) -> None:
        if not enabled():
            return
        now = time.monotonic()
        step = now - self._last
        total = now - self._t0
        self._last = now
        entry: dict[str, Any] = {
            "phase": phase,
            "step_s": round(step, 3),
            "total_s": round(total, 3),
        }
        entry.update(detail)
        self._marks.append(entry)
        detail_s = " ".join(f"{k}={v}" for k, v in detail.items()) if detail else ""
        msg = (
            f"[runner] remote-cold sid={self.session_id} udid={self.udid} "
            f"+{total:.3f}s (Δ{step:.3f}s) {phase}"
        )
        if detail_s:
            msg += f" | {detail_s}"
        print(msg, flush=True)
        _log.info(msg)

    def summary(self, label: str = "connected", **detail: Any) -> None:
        if not enabled():
            return
        total = time.monotonic() - self._t0
        if not self._marks:
            return
        phases = " → ".join(str(m["phase"]) for m in self._marks)
        bottlenecks = sorted(self._marks, key=lambda m: float(m["step_s"]), reverse=True)[:3]
        top = ", ".join(
            f"{b['phase']}({float(b['step_s']):.3f}s)" for b in bottlenecks
        )
        msg = (
            f"[runner] remote-cold sid={self.session_id} udid={self.udid} "
            f"DONE {label} total={total:.3f}s | path={phases} | slowest={top}"
        )
        extra = " ".join(f"{k}={v}" for k, v in detail.items()) if detail else ""
        if extra:
            msg += f" | {extra}"
        print(msg, flush=True)
        _log.info(msg)


def set_active(trace: ColdStartTrace | None) -> None:
    _local.trace = trace


def get_active() -> ColdStartTrace | None:
    return getattr(_local, "trace", None)


def mark(phase: str, **detail: Any) -> None:
    """在活跃 trace 上打点；无 trace 时忽略（除非传入 udid 做设备级日志）。"""
    trace = get_active()
    if trace is not None:
        trace.mark(phase, **detail)
        return
    if not enabled():
        return
    udid = str(detail.get("udid") or "").strip()
    if not udid:
        return
    uid = udid[:16]
    detail_s = " ".join(f"{k}={v}" for k, v in detail.items() if k != "udid")
    msg = f"[runner] remote-cold udid={uid} {phase}"
    if detail_s:
        msg += f" | {detail_s}"
    print(msg, flush=True)
    _log.info(msg)
