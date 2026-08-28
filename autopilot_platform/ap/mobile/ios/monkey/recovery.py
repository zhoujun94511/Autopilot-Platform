"""App 前台检测与拉回（session caps 不绑 bundleId）。"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Callable

from .driver import IOSMonkeyDriver

if TYPE_CHECKING:
    from ....keywords.context import ExecutionContext


class MonkeyRecovery:
    def __init__(
        self,
        ctx: "ExecutionContext",
        driver: IOSMonkeyDriver,
        bundle_id: str,
        alert_handle: Callable[[], None] | None = None,
    ):
        self.ctx = ctx
        self.driver = driver
        self.bundle_id = bundle_id
        self.alert_handle = alert_handle

    def ensure_foreground(self) -> bool:
        if self.driver.is_app_foreground(self.bundle_id):
            return True
        self.ctx.log(f"Monkey：App 不在前台，尝试 activate {self.bundle_id}")
        # noinspection PyBroadException
        try:
            self.driver.activate_app(self.bundle_id)
        except Exception:
            # noinspection PyBroadException
            try:
                self.driver.launch_app(self.bundle_id)
            except Exception:
                return False
        time.sleep(0.8)
        if self.alert_handle:
            self.alert_handle()
        return self.driver.is_app_foreground(self.bundle_id)

    def relaunch(self) -> bool:
        self.ctx.log(f"Monkey：relaunch {self.bundle_id}")
        # noinspection PyBroadException
        try:
            self.driver.launch_app(self.bundle_id)
        except Exception:
            self.driver.activate_app(self.bundle_id)
        time.sleep(1.0)
        if self.alert_handle:
            self.alert_handle()
        return self.driver.is_app_foreground(self.bundle_id)

    def escape_stuck(self, same_count: int, *, serious_limit: int) -> None:
        if same_count >= serious_limit:
            self.relaunch()
            return
        direction = "UP" if same_count % 2 == 0 else "LEFT"
        # noinspection PyBroadException
        try:
            self.driver.swipe_direction(direction)
        except Exception:
            pass
