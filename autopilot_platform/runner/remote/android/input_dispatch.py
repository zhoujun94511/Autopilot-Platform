"""DataChannel JSON → scrcpy ControlSender（自 WebAppFlaskscrcpy 精简，无 sync）。"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Callable, Optional

_log = logging.getLogger(__name__)

ReplyFn = Callable[[dict[str, Any]], None]


def dispatch(
    client: Any,
    msg: str,
    reply: Optional[ReplyFn] = None,
    device_id: Optional[str] = None,
) -> None:
    _ = device_id  # reserved for adaptive quality / multi-device routing
    try:
        evt = json.loads(msg)
    except (ValueError, TypeError):
        return
    t = evt.get("t")
    try:
        if t == "touch":
            client.control.touch(evt["x"], evt["y"], evt["action"])
        elif t == "key":
            client.control.keycode(evt["code"], evt["action"])
        elif t == "scroll":
            client.control.scroll(
                evt["x"],
                evt["y"],
                int(evt.get("h", 0)),
                int(evt.get("v", 0)),
            )
        elif t == "text":
            client.control.text(evt["text"])
        elif t == "swipe":
            sx, sy = evt["startX"], evt["startY"]
            ex, ey = evt["endX"], evt["endY"]
            dur = evt.get("duration", 200)

            def _run_swipe() -> None:
                try:
                    client.control.swipe(sx, sy, ex, ey, duration_ms=dur)
                except (OSError, AttributeError, RuntimeError) as worker_exc:
                    _log.warning("swipe worker failed: %s", worker_exc)

            threading.Thread(
                target=_run_swipe, name="swipe-worker", daemon=True
            ).start()
        elif t == "power":
            client.control.set_screen_power_mode(int(evt.get("mode", 2)))
        elif t == "expandNotification":
            client.control.expand_notification_panel()
        elif t == "expandSettings":
            client.control.expand_settings_panel()
        elif t == "collapse":
            client.control.collapse_panels()
        elif t == "rotate":
            client.control.rotate_device()
        elif t == "clipboard.set":
            seq = int(time.time_ns() & 0xFFFFFFFFFFFFFFFF)
            ok = client.control.set_clipboard(
                evt.get("text", ""),
                paste=bool(evt.get("paste", False)),
                sequence=seq,
            )
            if reply is not None:
                reply({"t": "clipboard.ack", "ok": bool(ok), "sequence": seq})
        elif t == "clipboard.get":
            text = client.control.get_clipboard()
            if reply is not None:
                reply({"t": "clipboard.value", "text": text})
    except (KeyError, ValueError, TypeError, AttributeError) as exc:
        _log.warning("input dispatch error (%s): %s", t, exc)
