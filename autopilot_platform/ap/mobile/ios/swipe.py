"""iOS WDA 滑屏策略（分页 ScrollView / 普通拖拽 / W3C 回退）。

W3C pointerMove 匀速 drag 在 UIPageViewController 上常见「滑 80% 又弹回」；
优先 XCUIElement swipeLeft/Right 或 dragFromToForDuration（XCTest 原生速度）。
"""

from __future__ import annotations

from typing import Any

_WDA_DIR = {
    "UP": "up", "DOWN": "down", "LEFT": "left", "RIGHT": "right",
}
_CHAIN_SCROLL = (
    "**/XCUIElementTypeScrollView",
    "**/XCUIElementTypeCollectionView",
    "**/XCUIElementTypeTable",
)


def _client(drv: Any):
    return getattr(drv, "wda_client", None) or getattr(drv, "_c", None)


def _win_size(drv: Any) -> tuple[int, int]:
    sz = drv.get_window_size()
    return int(sz["width"]), int(sz["height"])


def _find_scroll_container(client) -> Any | None:
    best = None
    best_area = 0
    for chain in _CHAIN_SCROLL:
        # noinspection PyBroadException
        try:
            els = client.find_elements("-ios class chain", chain)
        except Exception:
            continue
        for el in els:
            # noinspection PyBroadException
            try:
                if not el.is_displayed():
                    continue
                r = el.rect
                area = int(r.get("width", 0)) * int(r.get("height", 0))
                if area > best_area:
                    best_area = area
                    best = el
            except Exception:
                continue
    return best


def _try_element_swipe(client, direction: str) -> bool:
    wda_dir = _WDA_DIR.get(direction)
    if not wda_dir:
        return False
    el = _find_scroll_container(client)
    if el is None:
        return False
    # noinspection PyBroadException
    try:
        client.element_swipe(el.id, wda_dir)
        return True
    except Exception:
        return False


def _try_drag_fling(client, w: int, h: int, cx_ratio: float, cy_ratio: float,
                    direction: str) -> bool:
    y = int(h * cy_ratio)
    x = int(w * cx_ratio)
    # noinspection PyBroadException
    try:
        if direction == "LEFT":
            client.drag_from_to_for_duration(int(w * 0.92), y, int(w * 0.08), y)
        elif direction == "RIGHT":
            client.drag_from_to_for_duration(int(w * 0.08), y, int(w * 0.92), y)
        elif direction == "UP":
            client.drag_from_to_for_duration(x, int(h * 0.82), x, int(h * 0.18))
        elif direction == "DOWN":
            client.drag_from_to_for_duration(x, int(h * 0.18), x, int(h * 0.82))
        else:
            return False
        return True
    except Exception:
        return False


def _w3c_swipe(drv, w: int, h: int, cx_ratio: float, cy_ratio: float, direction: str,
               size_ratio: float, duration_ms: int) -> None:
    cx, cy = int(w * cx_ratio), int(h * cy_ratio)
    dx = dy = 0
    if direction == "UP":
        dy = -int(h * size_ratio)
    elif direction == "DOWN":
        dy = int(h * size_ratio)
    elif direction == "LEFT":
        dx = -int(w * size_ratio)
    elif direction == "RIGHT":
        dx = int(w * size_ratio)
    ex = min(max(cx + dx, 1), w - 1)
    ey = min(max(cy + dy, 1), h - 1)
    gesture_ms = min(max(80, int(duration_ms)), 250)
    drv.swipe(cx, cy, ex, ey, gesture_ms)


def wda_swipe_by_ratio(drv, direction: str, cx_ratio: float, cy_ratio: float,
                       size_ratio: float, duration_ms: int = 800,
                       *, strategy: str = "auto") -> str:
    """iOS WDA 滑屏。返回实际使用的策略名（scrollview|xctest|w3c）。"""
    d = str(direction).strip()
    for zh, en in (("上", "UP"), ("下", "DOWN"), ("左", "LEFT"), ("右", "RIGHT")):
        if d == zh:
            d = en
            break
    d = d.upper()
    client = _client(drv)
    w, h = _win_size(drv)
    mode = (strategy or "auto").strip().lower()

    if client is not None and mode in ("auto", "scrollview"):
        if mode != "xctest" and _try_element_swipe(client, d):
            return "scrollview"
    if client is not None and mode in ("auto", "xctest"):
        if _try_drag_fling(client, w, h, cx_ratio, cy_ratio, d):
            return "xctest"
    _w3c_swipe(drv, w, h, cx_ratio, cy_ratio, d, size_ratio, duration_ms)
    return "w3c"
