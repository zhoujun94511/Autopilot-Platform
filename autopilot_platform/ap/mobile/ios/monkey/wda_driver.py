"""WDA-direct iOS Monkey Driver 适配。"""

from __future__ import annotations

from typing import Any

from ..swipe import wda_swipe_by_ratio
from .driver import IOSMonkeyDriver


class WdaMonkeyDriver(IOSMonkeyDriver):
    backend = "wda"

    def __init__(self, driver: Any):
        self._drv = driver
        self._client = getattr(driver, "wda_client", None) or getattr(driver, "_c", None)

    def raw_driver(self) -> Any:
        return self._drv

    def tap(self, x: int, y: int) -> None:
        # WdaDriver.tap 接受 [(x,y)]；WdaClient 直接 tap
        tap_fn = getattr(self._drv, "tap", None)
        if callable(tap_fn):
            try:
                tap_fn([(int(x), int(y))])
                return
            except TypeError:
                tap_fn(int(x), int(y))
                return
        if self._client is not None:
            self._client.tap(int(x), int(y))

    def swipe_direction(self, direction: str) -> str:
        return wda_swipe_by_ratio(
            self._drv, direction, 0.5, 0.5, 0.6, duration_ms=300, strategy="auto",
        )

    def long_press(self, x: int, y: int, duration_ms: int = 800) -> None:
        lp = getattr(self._drv, "long_press", None)
        if callable(lp):
            lp(int(x), int(y), int(duration_ms))
            return
        if self._client is not None:
            self._client.long_press(int(x), int(y), int(duration_ms))

    def screenshot_png(self) -> bytes:
        if hasattr(self._drv, "get_screenshot_as_png"):
            return self._drv.get_screenshot_as_png()
        if self._client is not None:
            return self._client.screenshot_png()
        return b""

    def page_source(self) -> str:
        src = getattr(self._drv, "page_source", None)
        if isinstance(src, str):
            return src
        if callable(src):
            return str(src() or "")
        if self._client is not None:
            return str(self._client.source() or "")
        return ""

    def window_size(self) -> tuple[int, int]:
        sz = self._drv.get_window_size()
        return int(sz["width"]), int(sz["height"])

    def launch_app(self, bundle_id: str) -> None:
        self._drv.launch_app(bundle_id)

    def activate_app(self, bundle_id: str) -> None:
        self._drv.activate_app(bundle_id)

    def app_state(self, bundle_id: str) -> int:
        if self._client is None:
            return 0
        return int(self._client.app_state(bundle_id))
