"""从 page_source 解析可点击控件。"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .policy import is_blacklisted

_CLICKABLE_TYPES = frozenset({
    "XCUIElementTypeButton",
    "XCUIElementTypeCell",
    "XCUIElementTypeStaticText",
    "XCUIElementTypeImage",
    "XCUIElementTypeTextField",
    "XCUIElementTypeTextView",
    "XCUIElementTypeOther",
})

_TAG = re.compile(r"<XCUIElementType\w+[^>]*/?>", re.IGNORECASE)


def _attr(tag: str, name: str, default: str = "") -> str:
    m = re.search(rf'\b{re.escape(name)}="([^"]*)"', tag)
    return m.group(1) if m else default


@dataclass
class MonkeyElement:
    type: str
    name: str
    label: str
    value: str
    enabled: bool
    visible: bool
    x: int
    y: int
    width: int
    height: int

    @property
    def center(self) -> tuple[int, int]:
        return self.x + self.width // 2, self.y + self.height // 2

    @property
    def display_text(self) -> str:
        return self.label or self.name or self.value


def parse_elements(xml: str, *, screen_w: int, screen_h: int) -> list[MonkeyElement]:
    if not xml:
        return []
    out: list[MonkeyElement] = []
    for tag in _TAG.findall(xml):
        etype = _attr(tag, "type")
        if etype not in _CLICKABLE_TYPES:
            continue
        if not _attr(tag, "x") or not _attr(tag, "y"):
            continue
        enabled = _attr(tag, "enabled", "true").lower() != "false"
        visible = _attr(tag, "visible", "true").lower() != "false"
        x, y = int(_attr(tag, "x")), int(_attr(tag, "y"))
        w, h = int(_attr(tag, "width", "0")), int(_attr(tag, "height", "0"))
        if not enabled or not visible or w <= 5 or h <= 5:
            continue
        if x + w < 0 or y + h < 0 or x > screen_w or y > screen_h:
            continue
        out.append(MonkeyElement(
            type=etype,
            name=_attr(tag, "name"),
            label=_attr(tag, "label"),
            value=_attr(tag, "value"),
            enabled=enabled,
            visible=visible,
            x=x, y=y, width=w, height=h,
        ))
    return out


def pick_random_element(elements: list[MonkeyElement], rng, *,
                        allow_dangerous: bool) -> MonkeyElement | None:
    pool = [e for e in elements if not is_blacklisted(e.display_text, allow_dangerous=allow_dangerous)]
    if not pool:
        return None
    return rng.choice(pool)
