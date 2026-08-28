"""未知 iOS 系统弹框采集（截图 + XML + JSON）。"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any

from .model import AlertDecision, AlertInfo


class AlertRecorder:
    def __init__(self, base_dir: str = ""):
        self.base_dir = base_dir or os.getcwd()

    def _logs_root(self) -> str:
        return os.path.join(self.base_dir, "logs", "ios_alerts")

    def save(
        self,
        info: AlertInfo,
        decision: AlertDecision,
        adapter: Any,
        *,
        stage: str = "",
    ) -> str:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        folder = os.path.join(self._logs_root(), ts)
        os.makedirs(folder, exist_ok=True)

        meta = {
            "stage": stage,
            "text": info.text,
            "buttons": info.buttons,
            "backend": info.backend,
            "alert_kind": info.alert_kind,
            "decision": {
                "action": decision.action,
                "button": decision.button,
                "reason": decision.reason,
            },
        }
        with open(os.path.join(folder, "alert.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

        xml = adapter.page_source() if adapter is not None else ""
        if xml:
            with open(os.path.join(folder, "page_source.xml"), "w", encoding="utf-8") as f:
                f.write(xml)

        png = adapter.screenshot_png() if adapter is not None else b""
        if png:
            with open(os.path.join(folder, "screenshot.png"), "wb") as f:
                f.write(png)
        return folder
