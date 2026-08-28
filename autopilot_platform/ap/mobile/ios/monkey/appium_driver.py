"""Appium iOS Monkey Driver 适配（最小实现，Win 主路径为 WDA）。"""

from __future__ import annotations

from typing import Any

from .driver import IOSMonkeyDriver


class AppiumMonkeyDriver(IOSMonkeyDriver):
    backend = "appium"

    def __init__(self, driver: Any):
        self._drv = driver

    def raw_driver(self) -> Any:
        return self._drv

    def _touch_action(self, x: int, y: int, *, pause_ms: int = 0) -> None:
        from selenium.webdriver.common.actions.action_builder import ActionBuilder
        from selenium.webdriver.common.actions.pointer_input import PointerInput

        finger = PointerInput("touch", "finger")
        actions = ActionBuilder(self._drv, mouse=finger)
        actions.pointer_action.move_to_location(int(x), int(y))
        actions.pointer_action.pointer_down()
        if pause_ms > 0:
            actions.pointer_action.pause(pause_ms / 1000.0)
        actions.pointer_action.pointer_up()
        actions.perform()

    def tap(self, x: int, y: int) -> None:
        self._touch_action(x, y)

    def swipe_direction(self, direction: str) -> str:
        w, h = self.window_size()
        cx, cy = w // 2, h // 2
        d = direction.upper()
        if d == "UP":
            self._drv.swipe(cx, int(h * 0.8), cx, int(h * 0.2), 300)
        elif d == "DOWN":
            self._drv.swipe(cx, int(h * 0.2), cx, int(h * 0.8), 300)
        elif d == "LEFT":
            self._drv.swipe(int(w * 0.8), cy, int(w * 0.2), cy, 300)
        elif d == "RIGHT":
            self._drv.swipe(int(w * 0.2), cy, int(w * 0.8), cy, 300)
        return "appium_swipe"

    def long_press(self, x: int, y: int, duration_ms: int = 800) -> None:
        self._touch_action(x, y, pause_ms=duration_ms)

    def screenshot_png(self) -> bytes:
        return self._drv.get_screenshot_as_png()

    def page_source(self) -> str:
        return str(self._drv.page_source or "")

    def window_size(self) -> tuple[int, int]:
        sz = self._drv.get_window_size()
        return int(sz["width"]), int(sz["height"])

    def launch_app(self, bundle_id: str) -> None:
        self._drv.activate_app(bundle_id)

    def activate_app(self, bundle_id: str) -> None:
        self._drv.activate_app(bundle_id)

    def app_state(self, bundle_id: str) -> int:
        # noinspection PyBroadException
        try:
            state = self._drv.execute_script(
                "mobile: queryAppState", {"bundleId": bundle_id},
            )
            if state is not None:
                return int(state)
        except Exception:
            pass
        # noinspection PyBroadException
        try:
            info = self._drv.execute_script("mobile: activeAppInfo") or {}
            if str(info.get("bundleId") or "") == bundle_id:
                return 4
        except Exception:
            pass
        return 0
