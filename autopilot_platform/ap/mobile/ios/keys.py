"""iOS 物理键：WDA pressButton / Appium keycode 映射。"""

from __future__ import annotations

import time
from typing import Any

from .runtime import is_ios_driver, is_wda_backend

# 关键字 oKeys → WDA /wda/pressButton name
_WDA_BUTTON = {
    "home": "home",
    "back": "home",          # iOS 无系统返回，近似回主屏
    "menu": "home",
    "enter": "home",
    "volumeup": "volumeUp",
    "volumedown": "volumeDown",
    "snapshot": "snapshot",
}

# Android keycode（Appium Android / 误用在 iOS Appium 时回退）
_ANDROID_KEYCODE = {"home": 3, "back": 4, "menu": 82, "enter": 66}


def press_delete_keys(
    driver: Any,
    backend: str,
    count: int = 1,
) -> None:
    """密码框等场景：逐次发送退格（WDA / Appium iOS 可用）。"""
    n = max(0, int(count or 0))
    if n <= 0:
        return
    if is_wda_backend(backend, driver):
        if hasattr(driver, "press_delete"):
            driver.press_delete(n)
            return
        client = getattr(driver, "wda_client", None) or getattr(driver, "_c", None)
        if client is not None and hasattr(client, "press_delete"):
            client.press_delete(n)
            return
    if is_ios_driver(driver):
        for _ in range(n):
            # noinspection PyBroadException
            try:
                driver.execute_script("mobile: pressKey", {"key": "delete"})
            except Exception:
                # noinspection PyBroadException
                try:
                    driver.execute_script("mobile: pressButton", {"name": "delete"})
                except Exception:
                    pass
        return
    if hasattr(driver, "press_keycode"):
        for _ in range(n):
            driver.press_keycode(67)
    elif hasattr(driver, "keyevent"):
        for _ in range(n):
            driver.keyevent(67)


def press_physical_key(
    driver: Any,
    backend: str,
    key: str,
    *,
    count: int = 1,
    pause_sec: float = 1.0,
) -> None:
    name = str(key or "home").strip().lower()
    n = max(1, int(count or 1))
    if is_wda_backend(backend, driver):
        btn = _WDA_BUTTON.get(name, "home")
        for _ in range(n):
            driver.press_button(btn)
            if pause_sec > 0:
                time.sleep(pause_sec)
        return
    if is_ios_driver(driver):
        btn = _WDA_BUTTON.get(name, "home")
        for _ in range(n):
            # noinspection PyBroadException
            try:
                driver.execute_script("mobile: pressButton", {"name": btn})
            except Exception:
                pass
            if pause_sec > 0:
                time.sleep(pause_sec)
        return
    code = _ANDROID_KEYCODE.get(name, 3)
    for _ in range(n):
        driver.press_keycode(code)
        if pause_sec > 0:
            time.sleep(pause_sec)
