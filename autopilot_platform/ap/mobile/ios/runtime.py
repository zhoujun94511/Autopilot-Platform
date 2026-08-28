"""识别当前 iOS driver 后端类型。"""

from __future__ import annotations

from typing import Any


def is_wda_backend(backend: str = "", driver: Any = None) -> bool:
    if (backend or "").strip().lower() == "wda":
        return True
    caps = getattr(driver, "capabilities", None) or {}
    return caps.get("automationName") == "WDA-Direct"


def is_ios_driver(driver: Any) -> bool:
    caps = getattr(driver, "capabilities", None) or {}
    return str(caps.get("platformName", "")).lower() == "ios"


def driver_backend(driver: Any, mgr_backend: str = "") -> str:
    """返回 wda / appium / 空（非 iOS 或未识别）。"""
    if is_wda_backend(mgr_backend, driver):
        return "wda"
    if is_ios_driver(driver):
        return "appium" if (mgr_backend or "").lower() != "wda" else "wda"
    return (mgr_backend or "").strip().lower()
