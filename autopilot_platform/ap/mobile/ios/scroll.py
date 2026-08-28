"""滚动至元素可见（WDA element scroll / Appium ActionChains）。"""

from __future__ import annotations

import time
from typing import Any, Callable

from .runtime import is_wda_backend


def scroll_to_element(driver: Any, element: Any, backend: str = "") -> None:
    if is_wda_backend(backend, driver):
        if hasattr(element, "scroll_into_view"):
            element.scroll_into_view()
            return
        # 回退：按元素中心小幅滑动
        rect = getattr(element, "rect", None) or {}
        cx = int(rect.get("x", 0) + rect.get("width", 0) // 2)
        cy = int(rect.get("y", 0) + rect.get("height", 0) // 2)
        if cy > 0 and hasattr(driver, "swipe"):
            driver.swipe(cx, cy + 150, cx, cy - 150, 400)
        return
    # noinspection PyBroadException
    try:
        from selenium.webdriver.common.action_chains import ActionChains
        ActionChains(driver).move_to_element(element).perform()
        return
    except Exception:
        pass
    # noinspection PyBroadException
    try:
        driver.execute_script("arguments[0].scrollIntoView(true);", element)
    except Exception:
        pass


def scroll_until_element_found(
    driver: Any,
    backend: str,
    *,
    try_find: Callable[[], Any],
    swipe: Callable[[], None],
    max_attempts: int = 10,
    deadline: float | None = None,
    pause_s: float = 0.5,
) -> Any:
    """滑动直至定位成功；找到但不可见时尝试 scroll_into_view（iOS WDA）。"""
    attempts = max(1, int(max_attempts or 1))
    for i in range(attempts):
        if deadline is not None and time.time() >= deadline:
            break
        # noinspection PyBroadException
        try:
            el = try_find()
            # noinspection PyBroadException
            try:
                if hasattr(el, "is_displayed") and not el.is_displayed():
                    scroll_to_element(driver, el, backend)
            except Exception:
                pass
            return el
        except Exception:
            if deadline is not None and time.time() >= deadline:
                break
            swipe()
            if pause_s > 0:
                time.sleep(pause_s)
    return try_find()
