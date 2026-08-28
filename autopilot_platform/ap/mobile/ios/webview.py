"""WebView / H5 能力（URL、JS 点击）—— WDA-direct 与 Appium iOS 统一入口。"""

from __future__ import annotations

from typing import Any

from .runtime import is_wda_backend


def get_current_url(driver: Any, backend: str = "") -> str:
    if is_wda_backend(backend, driver) and hasattr(driver, "current_url"):
        return str(driver.current_url or "")
    return str(getattr(driver, "current_url", "") or "")


def js_click_element(driver: Any, backend: str, element: Any) -> None:
    """WebView 内 JS 点击；WDA 失败时回退原生 click。"""
    if is_wda_backend(backend, driver):
        # noinspection PyBroadException
        try:
            driver.execute_script("arguments[0].click();", element)
            return
        except Exception:
            element.click()
            return
    driver.execute_script("arguments[0].click();", element)
