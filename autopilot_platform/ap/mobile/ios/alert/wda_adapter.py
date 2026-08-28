"""WDA-direct 系统 Alert 适配器（主路径：/alert/text + /alert/accept）。"""

from __future__ import annotations

import re
from typing import Any

from .model import AlertInfo
from .rules import _decode_xml_entities


def alert_button_labels(client: Any) -> list[str]:
    """从 page_source 取 Alert 内按钮 label。"""
    # noinspection PyBroadException
    try:
        xml = client.source()
    except Exception:
        return []
    if "XCUIElementTypeAlert" not in xml:
        return []
    labels: list[str] = []
    for m in re.finditer(r'type="XCUIElementTypeButton"[^>]*label="([^"]*)"', xml):
        lb = m.group(1)
        if len(lb) > 200:
            continue
        labels.append(lb)
    wlan = [lb for lb in labels if "WLAN" in lb]
    return wlan if wlan else labels


def alert_is_open(client: Any) -> bool:
    # noinspection PyBroadException
    try:
        client.alert_text()
        return True
    except Exception:
        return False


class WdaAlertAdapter:
    backend = "wda"

    def __init__(self, client: Any):
        self.client = client

    def is_open(self) -> bool:
        return alert_is_open(self.client)

    def get_alert(self) -> AlertInfo:
        if not self.is_open():
            return AlertInfo(exists=False, backend=self.backend)
        # noinspection PyBroadException
        try:
            text = str(self.client.alert_text() or "")
        except Exception:
            return AlertInfo(exists=False, backend=self.backend)
        buttons = [_decode_xml_entities(lb) for lb in alert_button_labels(self.client)]
        return AlertInfo(
            exists=True,
            text=text,
            buttons=buttons,
            backend=self.backend,
            alert_kind="system",
        )

    def accept(self, button_label: str = "") -> None:
        self.client.alert_accept(button_label)

    def dismiss(self, button_label: str = "") -> None:
        self.client.alert_dismiss(button_label)

    def page_source(self) -> str:
        # noinspection PyBroadException
        try:
            return str(self.client.source() or "")
        except Exception:
            return ""

    def screenshot_png(self) -> bytes:
        # noinspection PyBroadException
        try:
            return self.client.screenshot()
        except Exception:
            return b""
