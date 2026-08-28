"""Monkey 事件日志与异常现场。"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any

from .driver import IOSMonkeyDriver


class MonkeyRecorder:
    def __init__(
        self,
        base_dir: str,
        *,
        root: str = "",
        bundle_id: str,
        backend: str,
        seed: int,
        duration_sec: int = 0,
        policy: str = "balanced",
    ):
        if root:
            self.root = root
            os.makedirs(self.root, exist_ok=True)
        else:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.root = os.path.join(base_dir, "logs", "ios_monkey", ts)
            os.makedirs(self.root, exist_ok=True)
        self.events_path = os.path.join(self.root, "events.jsonl")
        self.errors_dir = os.path.join(self.root, "errors")
        os.makedirs(self.errors_dir, exist_ok=True)
        self.summary: dict[str, Any] = {
            "platform": "ios",
            "backend": backend,
            "bundleId": bundle_id,
            "seed": seed,
            "policy": policy,
            "plannedDurationSec": duration_sec,
            "durationSec": 0,
            "eventCount": 0,
            "errorCount": 0,
            "alertHandledCount": 0,
            "stuckRecoverCount": 0,
            "watchdogRecoverCount": 0,
            "result": "passed",
        }

    def merge_summary(self, extra: dict[str, Any]) -> None:
        self.summary.update(extra)

    def write_summary(self) -> None:
        path = os.path.join(self.root, "summary.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.summary, f, ensure_ascii=False, indent=2)

    def record_event(self, payload: dict[str, Any]) -> None:
        self.summary["eventCount"] = int(self.summary.get("eventCount", 0)) + 1
        with open(self.events_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def save_error(self, index: int, driver: IOSMonkeyDriver, exc: Exception,
                   *, context: dict[str, Any] | None = None) -> str:
        self.summary["errorCount"] = int(self.summary.get("errorCount", 0)) + 1
        folder = os.path.join(self.errors_dir, f"event_{index:04d}")
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "exception.txt"), "w", encoding="utf-8") as f:
            f.write(str(exc))
        if context:
            with open(os.path.join(folder, "context.json"), "w", encoding="utf-8") as f:
                json.dump(context, f, ensure_ascii=False, indent=2)
        xml = driver.page_source()
        if xml:
            with open(os.path.join(folder, "page_source.xml"), "w", encoding="utf-8") as f:
                f.write(xml)
        png = driver.screenshot_png()
        if png:
            with open(os.path.join(folder, "screenshot.png"), "wb") as f:
                f.write(png)
        return folder

    def bump_alert(self) -> None:
        self.summary["alertHandledCount"] = int(self.summary.get("alertHandledCount", 0)) + 1

    def bump_stuck(self) -> None:
        self.summary["stuckRecoverCount"] = int(self.summary.get("stuckRecoverCount", 0)) + 1

    def bump_watchdog(self) -> None:
        self.summary["watchdogRecoverCount"] = int(self.summary.get("watchdogRecoverCount", 0)) + 1

    def finalize(self, *, result: str = "passed", duration_sec: int = 0) -> dict[str, Any]:
        self.summary["result"] = result
        if duration_sec > 0:
            self.summary["durationSec"] = duration_sec
        self.write_summary()
        self.summary["reportDir"] = self.root
        return dict(self.summary)
