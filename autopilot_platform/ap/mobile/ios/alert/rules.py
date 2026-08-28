"""iOS 系统弹框规则库：通用按钮文案与权限类弹窗匹配。"""

from __future__ import annotations

import re
from typing import Any

ACCEPT_BUTTONS: tuple[str, ...] = (
    "允许",
    "Allow",
    "OK",
    "Ok",
    "好",
    "Continue",
    "继续",
    "WLAN & Cellular",
    "无线局域网与蜂窝网络",
    "WLAN &amp; Cellular",
)

DISMISS_BUTTONS: tuple[str, ...] = (
    "Don't Allow",
    "Don't allow",
    "不允许",
    "Cancel",
    "取消",
    "Not Now",
    "稍后",
)

IOS_ALERT_RULES: tuple[dict[str, Any], ...] = (
    {
        "id": "local_network",
        "match_text": ("WLAN", "wireless", "local network", "本地网络", "无线局域网"),
        "action": "accept",
        "button_priority": (
            "WLAN & Cellular",
            "WLAN &amp; Cellular",
            "无线局域网与蜂窝网络",
            "Allow",
            "允许",
        ),
    },
    {
        "id": "notification",
        "match_text": ("notification", "通知", "推送"),
        "action": "accept",
        "button_priority": ("Allow", "允许", "OK"),
    },
    {
        "id": "tracking",
        "match_text": ("track", "跟踪", "追踪", "广告"),
        "action": "accept",
        "button_priority": ("Allow", "允许", "Ask App Not to Track", "要求App不跟踪"),
    },
    {
        "id": "camera",
        "match_text": ("camera", "相机", "摄像头"),
        "action": "accept",
        "button_priority": ("Allow", "允许", "OK"),
    },
    {
        "id": "photos",
        "match_text": ("photo", "相册", "照片"),
        "action": "accept",
        "button_priority": ("Allow", "允许", "Select Photos", "选择照片"),
    },
    {
        "id": "location",
        "match_text": ("location", "位置", "定位"),
        "action": "accept",
        "button_priority": ("Allow While Using App", "使用App期间允许", "Allow", "允许"),
    },
    {
        "id": "microphone",
        "match_text": ("microphone", "麦克风"),
        "action": "accept",
        "button_priority": ("Allow", "允许", "OK"),
    },
)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _text_matches(text: str, needles: tuple[str, ...]) -> bool:
    hay = _norm(text)
    for needle in needles:
        if _norm(needle) in hay:
            return True
    return False


def pick_button(buttons: list[str], priorities: tuple[str, ...]) -> str:
    """按优先级在可见按钮中选第一个匹配项。"""
    if not buttons:
        return ""
    decoded = [_decode_xml_entities(b) for b in buttons]
    for pri in priorities:
        p = _decode_xml_entities(pri)
        for btn in decoded:
            if btn == p or p.lower() in btn.lower() or btn.lower() in p.lower():
                return btn
    return ""


def pick_accept_button(buttons: list[str]) -> str:
    return pick_button(buttons, ACCEPT_BUTTONS)


def pick_dismiss_button(buttons: list[str]) -> str:
    return pick_button(buttons, DISMISS_BUTTONS)


def match_rule(text: str) -> dict[str, Any] | None:
    for rule in IOS_ALERT_RULES:
        if _text_matches(text, tuple(rule.get("match_text", ()))):
            return rule
    return None


def _decode_xml_entities(s: str) -> str:
    return (s.replace("&amp;", "&").replace("&quot;", '"')
            .replace("&lt;", "<").replace("&gt;", ">"))
