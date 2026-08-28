"""iOS Monkey Driver 抽象与工厂。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ....keywords.context import ExecutionContext


class IOSMonkeyDriver(ABC):
    backend: str = ""

    @abstractmethod
    def tap(self, x: int, y: int) -> None: ...

    @abstractmethod
    def swipe_direction(self, direction: str) -> str: ...

    @abstractmethod
    def long_press(self, x: int, y: int, duration_ms: int = 800) -> None: ...

    @abstractmethod
    def screenshot_png(self) -> bytes: ...

    @abstractmethod
    def page_source(self) -> str: ...

    @abstractmethod
    def window_size(self) -> tuple[int, int]: ...

    @abstractmethod
    def launch_app(self, bundle_id: str) -> None: ...

    @abstractmethod
    def activate_app(self, bundle_id: str) -> None: ...

    @abstractmethod
    def app_state(self, bundle_id: str) -> int: ...

    def is_app_foreground(self, bundle_id: str) -> bool:
        return self.app_state(bundle_id) == 4

    @abstractmethod
    def raw_driver(self) -> Any: ...


def create_monkey_driver(ctx: "ExecutionContext") -> IOSMonkeyDriver:
    from ....keywords.mobile.driver import get_manager
    from ..runtime import driver_backend, is_wda_backend
    from .wda_driver import WdaMonkeyDriver
    from .appium_driver import AppiumMonkeyDriver

    mgr = get_manager(ctx)
    drv = mgr.driver()
    backend = driver_backend(drv, mgr.backend or str(ctx.get_var("__mobile_backend_mode__") or ""))
    if is_wda_backend(backend, drv):
        return WdaMonkeyDriver(drv)
    if backend == "appium":
        return AppiumMonkeyDriver(drv)
    raise RuntimeError(f"不支持的 iOS Monkey 后端: {backend or 'unknown'}")
