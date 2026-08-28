"""Appium iOS 系统 Alert 适配器（switch_to.alert）。"""

from __future__ import annotations

from typing import Any

from .model import AlertInfo


class AppiumAlertAdapter:
    backend = "appium"

    def __init__(self, driver: Any):
        self.driver = driver

    def _alert(self):
        return self.driver.switch_to.alert

    def is_open(self) -> bool:
        # noinspection PyBroadException
        try:
            self._alert()
            return True
        except Exception:
            return False

    def get_alert(self) -> AlertInfo:
        if not self.is_open():
            return AlertInfo(exists=False, backend=self.backend)
        # noinspection PyBroadException
        try:
            alert = self._alert()
            text = str(getattr(alert, "text", "") or "")
        except Exception:
            return AlertInfo(exists=False, backend=self.backend)
        return AlertInfo(
            exists=True,
            text=text,
            buttons=[],
            backend=self.backend,
            alert_kind="system",
        )

    def accept(self, _button_label: str = "") -> None:
        self._alert().accept()

    def dismiss(self, _button_label: str = "") -> None:
        self._alert().dismiss()

    def page_source(self) -> str:
        # noinspection PyBroadException
        try:
            return str(self.driver.page_source or "")
        except Exception:
            return ""

    def screenshot_png(self) -> bytes:
        # noinspection PyBroadException
        try:
            return self.driver.get_screenshot_as_png()
        except Exception:
            return b""
