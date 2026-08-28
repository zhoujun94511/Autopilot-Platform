"""浏览器 input JSON → WDA 触控。"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any, Callable

from ..shared.coords import map_display_to_device

_log = logging.getLogger(__name__)


def _home_indicator_swipe(wda: Any) -> None:
    """Face ID 机型上 pressButton(home) 偶发空操作时，补一次从底边上滑回桌面。"""
    size = wda.window_size() if hasattr(wda, "window_size") else {}
    try:
        width = int((size or {}).get("width") or 0)
        height = int((size or {}).get("height") or 0)
    except (TypeError, ValueError, AttributeError):
        width, height = 0, 0
    if width <= 0 or height <= 0:
        width, height = 390, 844
    start_x = max(1, width // 2)
    start_y = max(8, height - 4)
    end_y = max(1, int(height * 0.55))
    if hasattr(wda, "drag_from_to_for_duration"):
        wda.drag_from_to_for_duration(start_x, start_y, start_x, end_y, 0.12)
        return
    if hasattr(wda, "swipe"):
        wda.swipe(start_x, start_y, start_x, end_y, duration_ms=180)


# 对齐 WebAppFlaskauto-iOS ios_control_service.button：
# home → pressButton("home")；lock/unlock → 顶层 /wda/lock|/wda/unlock（不是 pressButton）。
_WDA_PRESS_NAMES = {
    "home": "home",
    "volumeup": "volumeUp",
    "volumedown": "volumeDown",
    "volume_up": "volumeUp",
    "volume_down": "volumeDown",
    "snapshot": "snapshot",
}
_INPUT_TYPES = frozenset(
    {
        "touch",
        "double_tap",
        "text",
        "home",
        "lock",
        "unlock",
        "press_button",
        "clipboard.get",
        "clipboard.set",
        "swipe",
        "scroll",
    }
)


def _unwrap_input(evt: dict[str, Any]) -> dict[str, Any]:
    nested = evt.get("payload")
    if evt.get("t") or not isinstance(nested, dict):
        return evt
    if nested.get("t"):
        return dict(nested)
    return evt


def _event_display_size(
    evt: dict[str, Any], display_w: float, display_h: float
) -> tuple[float, float]:
    dw = evt.get("display_width")
    dh = evt.get("display_height")
    try:
        box_w = float(dw) if dw is not None else float(display_w)
        box_h = float(dh) if dh is not None else float(display_h)
    except (TypeError, ValueError):
        return float(display_w), float(display_h)
    if box_w <= 0 or box_h <= 0:
        return float(display_w), float(display_h)
    return box_w, box_h


def coerce_input_event(msg: dict[str, Any]) -> dict[str, Any] | None:
    """兼容 WS 信封 type=event/name=input、以及拆开后顶层 {t: home}。"""
    candidates: list[dict[str, Any]] = [msg]
    nested = msg.get("payload")
    if isinstance(nested, dict):
        candidates.append(nested)
        inner = nested.get("payload")
        if isinstance(inner, dict):
            candidates.append(inner)
    for item in candidates:
        if str(item.get("t") or "") in _INPUT_TYPES:
            return item
    kind = str(msg.get("type") or msg.get("name") or "")
    if kind == "input" and isinstance(nested, dict):
        return nested
    return None


def press_wda_button(wda: Any, name: str) -> None:
    key = (name or "").strip()
    mapped = _WDA_PRESS_NAMES.get(key.lower(), key)

    def _run(*, swallow: bool) -> None:
        try:
            if mapped == "lock" and hasattr(wda, "lock"):
                wda.lock()
                return
            if mapped == "unlock" and hasattr(wda, "unlock"):
                wda.unlock()
                return
            if mapped == "home":
                try:
                    if hasattr(wda, "press_button"):
                        wda.press_button("home")
                        return
                    if hasattr(wda, "home"):
                        wda.home()
                        return
                except Exception as home_exc:  # noqa: BLE001
                    _log.warning("ios wda pressButton home: %s", home_exc)
                    print(
                        f"[runner] remote ios button home press failed, swipe: {home_exc}",
                        flush=True,
                    )
                _home_indicator_swipe(wda)
                return
            if mapped and hasattr(wda, "press_button"):
                wda.press_button(mapped)
        except Exception as exc:  # noqa: BLE001
            _log.warning("ios wda button %s: %s", key or mapped, exc)
            print(
                f"[runner] remote ios button {key or mapped}: {exc}",
                flush=True,
            )
            if not swallow:
                raise

    # 锁屏 WDA 可能堵 15s；Flask 的 Home 是另一条 HTTP，不能排在锁屏后面。
    if mapped in ("lock", "unlock"):
        threading.Thread(
            target=lambda: _run(swallow=True),
            name=f"ios-btn-{mapped}",
            daemon=True,
        ).start()
        return
    _run(swallow=False)


def _press_wda_button(wda: Any, name: str) -> None:
    press_wda_button(wda, name)


class TouchState:
    """将 action 0/1/2 序列收敛为 tap / swipe / long_press。"""

    def __init__(self) -> None:
        self._down: tuple[float, float] | None = None
        self._last: tuple[float, float] | None = None
        self._moved = False
        self._t0 = 0.0

    def reset(self) -> None:
        self._down = None
        self._last = None
        self._moved = False
        self._t0 = 0.0

    def feed(
        self, action: int, x: float, y: float
    ) -> tuple[str, float, float, float, float] | None:
        """返回 (kind, x0, y0, x1, y1)；kind 为 tap|swipe|long_press。"""
        import time

        if action == 0:
            self._down = (x, y)
            self._last = (x, y)
            self._moved = False
            self._t0 = time.monotonic()
            return None
        if action == 2:
            if self._down is None:
                self._down = (x, y)
                self._t0 = time.monotonic()
            self._last = (x, y)
            if self._down is not None:
                dx = abs(x - self._down[0])
                dy = abs(y - self._down[1])
                if dx > 8 or dy > 8:
                    self._moved = True
            return None
        if action == 1:
            start = self._down or self._last or (x, y)
            end = (x, y)
            moved = self._moved
            held = (time.monotonic() - self._t0) if self._t0 else 0.0
            self.reset()
            if moved:
                return "swipe", start[0], start[1], end[0], end[1]
            if held >= 0.55:
                return "long_press", start[0], start[1], end[0], end[1]
            return "tap", start[0], start[1], end[0], end[1]
        return None


def dispatch_input(
    wda: Any,
    raw: dict[str, Any] | str,
    *,
    touch_state: TouchState,
    display_w: float,
    display_h: float,
    device_w: float,
    device_h: float,
    reply: Callable[[dict[str, Any]], None] | None = None,
) -> None:
    try:
        evt = json.loads(raw) if isinstance(raw, str) else dict(raw)
    except (TypeError, ValueError):
        return
    evt = _unwrap_input(evt)
    t = evt.get("t")
    try:
        if t == "touch":
            x = float(evt["x"])
            y = float(evt["y"])
            action = int(evt.get("action", 0))
            result = touch_state.feed(action, x, y)
            if result is None:
                return
            kind, x0, y0, x1, y1 = result
            sx, sy = map_display_to_device(
                x0,
                y0,
                display_w=display_w,
                display_h=display_h,
                device_w=device_w,
                device_h=device_h,
            )
            ex, ey = map_display_to_device(
                x1,
                y1,
                display_w=display_w,
                display_h=display_h,
                device_w=device_w,
                device_h=device_h,
            )
            if kind == "tap":
                wda.tap(sx, sy)
            elif kind == "long_press":
                if hasattr(wda, "long_press"):
                    wda.long_press(sx, sy, duration_ms=800)
                else:
                    wda.tap(sx, sy)
            else:
                dur = int(evt.get("duration", 300))

                def _swipe() -> None:
                    try:
                        wda.swipe(sx, sy, ex, ey, duration_ms=dur)
                    except Exception as swipe_err:  # noqa: BLE001
                        _log.warning("wda swipe: %s", swipe_err)

                threading.Thread(target=_swipe, name="ios-swipe", daemon=True).start()
        elif t == "double_tap":
            x = float(evt["x"])
            y = float(evt["y"])
            sx, sy = map_display_to_device(
                x,
                y,
                display_w=display_w,
                display_h=display_h,
                device_w=device_w,
                device_h=device_h,
            )
            if hasattr(wda, "double_tap"):
                wda.double_tap(sx, sy)
            else:
                wda.tap(sx, sy)
        elif t == "text":
            text = str(evt.get("text") or "")
            if text and hasattr(wda, "send_keys"):
                wda.send_keys(text)
        elif t == "home":
            _press_wda_button(wda, "home")
        elif t in ("lock", "unlock"):
            _press_wda_button(wda, str(t))
        elif t == "press_button":
            _press_wda_button(wda, str(evt.get("name") or ""))
        elif t == "clipboard.get":
            text = wda.get_pasteboard()
            if reply is not None:
                reply(
                    {
                        "t": "clipboard.value",
                        "text": text,
                        "request_id": str(evt.get("request_id") or ""),
                    }
                )
        elif t == "clipboard.set":
            wda.set_pasteboard(str(evt.get("text") or ""))
            if reply is not None:
                reply(
                    {
                        "t": "clipboard.ack",
                        "ok": True,
                        "request_id": str(evt.get("request_id") or ""),
                    }
                )
        elif t == "swipe":
            box_w, box_h = _event_display_size(evt, display_w, display_h)
            sx, sy = map_display_to_device(
                float(evt["startX"]),
                float(evt["startY"]),
                display_w=box_w,
                display_h=box_h,
                device_w=device_w,
                device_h=device_h,
            )
            ex, ey = map_display_to_device(
                float(evt["endX"]),
                float(evt["endY"]),
                display_w=box_w,
                display_h=box_h,
                device_w=device_w,
                device_h=device_h,
            )
            wda.swipe(sx, sy, ex, ey, duration_ms=int(evt.get("duration", 300)))
        elif t == "scroll":
            x = float(evt["x"])
            y = float(evt["y"])
            h = int(evt.get("h", 0))
            v = int(evt.get("v", 0))
            sx, sy = map_display_to_device(
                x,
                y,
                display_w=display_w,
                display_h=display_h,
                device_w=device_w,
                device_h=device_h,
            )
            ex = sx + h
            ey = sy + v
            dur = int(evt.get("duration", 120))

            def _scroll_swipe() -> None:
                try:
                    wda.swipe(int(sx), int(sy), int(ex), int(ey), duration_ms=dur)
                except Exception as scroll_err:  # noqa: BLE001
                    _log.warning("ios scroll swipe: %s", scroll_err)

            threading.Thread(
                target=_scroll_swipe, name="ios-scroll", daemon=True
            ).start()
    except Exception as exc:  # noqa: BLE001
        # KeywordError / httpx 超时等原先会穿出 _run，Hub 整段 respawn。
        _log.warning("ios input dispatch (%s): %s", t, exc)
