"""iOS 远控「控制」页：系统弹窗 / 键入 / 截图（WDA，对齐 Flask ControlPanel）。"""

from __future__ import annotations

import base64
from typing import Any

from autopilot_platform.ap.keywords.registry import KeywordError

_KEYS = {
    "backspace": "\b",
    "delete": "\b",
    "enter": "\n",
    "return": "\n",
    "tab": "\t",
    "space": " ",
}


def get_alert(wda: Any) -> dict[str, Any]:
    try:
        text = str(wda.alert_text() or "")
    except KeywordError:
        # 无系统弹窗时 WDA GET /alert/text 返回错误，不是会话故障。
        text = ""
    present = bool(text.strip())
    buttons: list[str] = []
    if present:
        try:
            buttons = [str(item) for item in (wda.alert_buttons() or [])]
        except KeywordError:
            buttons = []
    return {"present": present, "text": text, "buttons": buttons}


def alert_action(wda: Any, action: str) -> dict[str, Any]:
    verb = (action or "").strip().lower()
    if verb == "accept":
        wda.alert_accept()
    elif verb == "dismiss":
        wda.alert_dismiss()
    else:
        raise ValueError(f"未知弹窗动作 '{action}'（accept/dismiss）")
    return {"action": verb, "ok": True}


def input_text(wda: Any, text: str) -> dict[str, Any]:
    payload = str(text or "")
    if not payload:
        raise ValueError("输入文本为空")
    wda.send_keys(payload)
    return {"ok": True, "length": len(payload)}


def input_key(wda: Any, name: str) -> dict[str, Any]:
    key = (name or "").strip().lower()
    char = _KEYS.get(key)
    if char is None:
        raise ValueError(f"未知按键 '{name}'（backspace/enter/tab/space）")
    wda.send_keys(char)
    return {"ok": True, "key": key}


def screenshot(wda: Any) -> dict[str, Any]:
    png = wda.screenshot_png()
    if not png:
        raise RuntimeError("WDA 截图为空")
    b64 = base64.b64encode(png).decode("ascii")
    return {"image": f"data:image/png;base64,{b64}", "mime": "image/png"}
