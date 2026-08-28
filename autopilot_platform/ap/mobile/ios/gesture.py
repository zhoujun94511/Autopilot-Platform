"""iOS / 双端坐标手势：点击、长按、元素/两点间滑动（WDA-direct / Appium 共用）。"""

from __future__ import annotations

from typing import Any

from .runtime import is_wda_backend

_DIR_CN = {
    "上": "UP", "下": "DOWN", "左": "LEFT", "右": "RIGHT",
    "up": "UP", "down": "DOWN", "left": "LEFT", "right": "RIGHT",
}
_DIR_WDA = {"UP": "up", "DOWN": "down", "LEFT": "left", "RIGHT": "right"}
_DIR_VEC = {
    "UP": (0, -1), "DOWN": (0, 1), "LEFT": (-1, 0), "RIGHT": (1, 0),
}


def _norm_direction(direction: str) -> str:
    d = str(direction or "UP").strip()
    return _DIR_CN.get(d, d.upper())


def swipe_between_points(
    driver: Any,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    duration_ms: int = 400,
    *,
    _backend: str = "",
) -> None:
    """两点间滑动；WDA / Appium driver.swipe 优先。"""
    dur = int(duration_ms or 400)
    # noinspection PyBroadException
    try:
        if hasattr(driver, "swipe"):
            driver.swipe(int(x1), int(y1), int(x2), int(y2), dur)
            return
    except Exception:
        pass
    # noinspection PyBroadException
    try:
        from selenium.webdriver.common.action_chains import ActionChains
        ActionChains(driver).move_by_offset(int(x2) - int(x1), int(y2) - int(y1)).perform()
    except Exception:
        pass


def swipe_element(
    driver: Any,
    element: Any,
    direction: str,
    *,
    backend: str = "",
    duration_ms: int = 400,
    distance_ratio: float = 1 / 3,
) -> None:
    """在元素上按方向滑动；WDA 优先 /element/{id}/swipe。"""
    d = _norm_direction(direction)
    if is_wda_backend(backend, driver) and getattr(element, "id", None):
        client = getattr(driver, "wda_client", None) or getattr(driver, "_c", None)
        wda_dir = _DIR_WDA.get(d)
        if client is not None and wda_dir and hasattr(client, "element_swipe"):
            # noinspection PyBroadException
            try:
                client.element_swipe(element.id, wda_dir)
                return
            except Exception:
                pass
    rect = element.rect
    cx = int(rect["x"] + rect["width"] // 2)
    cy = int(rect["y"] + rect["height"] // 2)
    vx, vy = _DIR_VEC.get(d, (0, -1))
    dist_x = int(rect["width"] * distance_ratio) * vx
    dist_y = int(rect["height"] * distance_ratio) * vy
    swipe_between_points(
        driver, cx, cy, cx + dist_x, cy + dist_y, duration_ms, _backend=backend,
    )


def swipe_element_horizontal(
    driver: Any,
    element: Any,
    *,
    backend: str = "",
    duration_ms: int = 400,
    inset: int = 10,
) -> None:
    """水平滑过元素（滑动登录/滑块场景）。"""
    loc = element.location
    size = element.size
    start_x = int(loc["x"]) + inset
    start_y = int(loc["y"] + size["height"] // 2)
    end_x = int(loc["x"] + size["width"])
    swipe_between_points(
        driver, start_x, start_y, end_x, start_y, duration_ms, _backend=backend,
    )


def tap_at(driver: Any, x: int, y: int, *, _backend: str = "") -> None:
    """坐标点击：W3C → driver.tap → mobile: clickGesture。"""
    # noinspection PyBroadException
    try:
        from selenium.webdriver.common.actions import interaction
        from selenium.webdriver.common.actions.action_builder import ActionBuilder
        from selenium.webdriver.common.actions.pointer_input import PointerInput
        pointer = PointerInput(interaction.POINTER_TOUCH, "touch")
        actions = ActionBuilder(driver, mouse=pointer)
        actions.pointer_action.move_to_location(x, y)
        actions.pointer_action.pointer_down()
        actions.pointer_action.pause(0.1)
        actions.pointer_action.pointer_up()
        actions.perform()
        return
    except Exception:
        pass
    # noinspection PyBroadException
    try:
        driver.tap([(int(x), int(y))])
        return
    except Exception:
        pass
    driver.execute_script("mobile: clickGesture", {"x": x, "y": y})


def long_press_at(driver: Any, x: int, y: int, duration_ms: int, *, _backend: str = "") -> None:
    """坐标长按。"""
    dur = max(100, int(duration_ms or 1000))
    # noinspection PyBroadException
    try:
        from selenium.webdriver.common.actions import interaction
        from selenium.webdriver.common.actions.action_builder import ActionBuilder
        from selenium.webdriver.common.actions.pointer_input import PointerInput
        pointer = PointerInput(interaction.POINTER_TOUCH, "touch")
        actions = ActionBuilder(driver, mouse=pointer)
        actions.pointer_action.move_to_location(x, y)
        actions.pointer_action.pointer_down()
        actions.pointer_action.pause(dur / 1000.0)
        actions.pointer_action.pointer_up()
        actions.perform()
        return
    except Exception:
        pass
    # noinspection PyBroadException
    try:
        driver.long_press(x, y, dur)
        return
    except Exception:
        pass
    driver.execute_script("mobile: longClickGesture", {"x": x, "y": y, "duration": dur})
