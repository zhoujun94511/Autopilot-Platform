"""将逻辑步骤文本规范化为 intent_steps（与 IDE normalize 对齐的轻量规则）。"""

from __future__ import annotations

import re
from typing import Any

_CLICK = re.compile(r"^(?:点击|单击|点选|按|tap|click)\s*(.+)$", re.IGNORECASE)
_TYPE = re.compile(
    r"^(?:输入|填写|键入|type|enter|input)\s*(.+?)(?:\s*[：:]\s*|\s+为\s+|\s+)(.+)$",
    re.IGNORECASE,
)
_ASSERT = re.compile(
    r"^(?:校验|验证|断言|检查|应显示|应看到|assert|verify|expect)\s*(.+)$",
    re.IGNORECASE,
)
_OPEN = re.compile(r"^(?:打开|打开页面|访问|navigate|open|goto)\s*(.+)$", re.IGNORECASE)
_WAIT = re.compile(r"^(?:等待|wait)\s*(.+)$", re.IGNORECASE)
_SWIPE = re.compile(r"^(?:滑动|swipe)\s*(.+)$", re.IGNORECASE)


def _one(text: str, *, sid: str) -> dict[str, Any]:
    t = (text or "").strip()
    if not t:
        return {
            "id": sid,
            "action": "custom",
            "target": "",
            "value": "",
            "platform_hint": "any",
            "text": "(空步骤)",
        }
    m = _TYPE.match(t)
    if m:
        return {
            "id": sid,
            "action": "type",
            "target": m.group(1).strip().strip("「」\"'"),
            "value": m.group(2).strip().strip("「」\"'"),
            "platform_hint": "any",
            "text": t,
        }
    for rx, action in (
        (_CLICK, "click"),
        (_ASSERT, "assert"),
        (_OPEN, "open"),
        (_WAIT, "wait"),
        (_SWIPE, "swipe"),
    ):
        m = rx.match(t)
        if m:
            return {
                "id": sid,
                "action": action,
                "target": m.group(1).strip().strip("「」\"'"),
                "value": "",
                "platform_hint": "any",
                "text": t,
            }
    return {
        "id": sid,
        "action": "custom",
        "target": t,
        "value": "",
        "platform_hint": "any",
        "text": t,
    }


def texts_to_intent_steps(
    logical_steps: list[str] | None,
    expected_results: list[str] | None = None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    n = 0
    for raw in logical_steps or []:
        t = str(raw).strip()
        if not t:
            continue
        n += 1
        out.append(_one(t, sid=f"s{n}"))
    for raw in expected_results or []:
        t = str(raw).strip()
        if not t:
            continue
        n += 1
        step = _one(t, sid=f"s{n}")
        if step["action"] == "custom":
            step["action"] = "assert"
            step["target"] = t
        out.append(step)
    if not out:
        out.append(
            {
                "id": "s1",
                "action": "custom",
                "target": "",
                "value": "",
                "platform_hint": "any",
                "text": "（空步骤，请补充）",
            }
        )
    return out
