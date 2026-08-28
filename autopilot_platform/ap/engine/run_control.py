"""用例执行流控：协作式停止与暂停（在步骤/壳边界生效）。

- 停止：置位 cancel_event，并清除暂停以便等待中的线程退出。
- 暂停：置位 pause_event，执行线程在 checkpoint 处阻塞，不开始下一步。
- 无法强杀正在运行的单步关键字（与 cancel 相同限制）；长步骤（如 Monkey）需在步骤内
  主动调用 interrupt.flow_checkpoint / adb_shell_cancellable 等方可协作中断。
"""

from __future__ import annotations

import threading
import time

PAUSE_POLL_SEC = 0.05


def checkpoint(
    cancel_event: threading.Event | None,
    pause_event: threading.Event | None,
) -> bool:
    """步骤边界检查。若已取消返回 True；若暂停则阻塞直到恢复或取消。"""
    if cancel_event is not None and cancel_event.is_set():
        return True
    if pause_event is None:
        return False
    while pause_event.is_set():
        if cancel_event is not None and cancel_event.is_set():
            return True
        time.sleep(PAUSE_POLL_SEC)
    return cancel_event is not None and cancel_event.is_set()


class RunControl:
    """UI / Worker 侧持有的执行控制句柄。"""

    def __init__(self) -> None:
        self.cancel_event = threading.Event()
        self.pause_event = threading.Event()

    def request_stop(self) -> None:
        self.pause_event.clear()
        self.cancel_event.set()

    @staticmethod
    def terminate_children(ctx) -> None:
        """终止 ctx 上登记的可中断子进程（Monkey adb 等）。"""
        from .interrupt import terminate_child_procs
        if ctx is not None:
            terminate_child_procs(ctx)

    def request_pause(self) -> None:
        self.pause_event.set()

    def request_resume(self) -> None:
        self.pause_event.clear()

    @property
    def is_cancelled(self) -> bool:
        return self.cancel_event.is_set()

    @property
    def is_paused(self) -> bool:
        return self.pause_event.is_set()

    def checkpoint(self) -> bool:
        return checkpoint(self.cancel_event, self.pause_event)
