"""iOS Monkey 最近报告指针（供 UI / CLI 打开；支持多设备并行）。"""

from __future__ import annotations

import json
import os
from typing import Any


LATEST_FILE = "latest.json"


def _latest_path(project_dir: str) -> str:
    return os.path.join(project_dir or ".", "logs", "ios_monkey", LATEST_FILE)


def _read_file(project_dir: str) -> dict[str, Any]:
    path = _latest_path(project_dir)
    if not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, dict) else {}


def _resolve_entry(data: dict[str, Any], udid: str = "") -> dict[str, Any]:
    if udid:
        devices = data.get("devices")
        if isinstance(devices, dict) and udid in devices:
            entry = devices[udid]
            return entry if isinstance(entry, dict) else {}
    last = data.get("last")
    if isinstance(last, dict):
        return last
    if data.get("reportDir"):
        return data
    return {}


def write_latest_pointer(
    project_dir: str,
    report_dir: str,
    html_path: str = "",
    udid: str = "",
) -> str:
    root = os.path.join(project_dir or ".", "logs", "ios_monkey")
    os.makedirs(root, exist_ok=True)
    path = _latest_path(project_dir)
    entry = {
        "reportDir": os.path.abspath(report_dir),
        "reportHtml": os.path.abspath(html_path) if html_path else "",
        "udid": udid,
    }
    data = _read_file(project_dir)
    devices = data.get("devices")
    if not isinstance(devices, dict):
        devices = {}
    if udid:
        devices[udid] = entry
    payload = {"devices": devices, "last": entry}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return path


def read_latest(project_dir: str, udid: str = "") -> dict[str, Any]:
    return _resolve_entry(_read_file(project_dir), udid)


def latest_report_dir(project_dir: str, udid: str = "") -> str:
    return str(read_latest(project_dir, udid).get("reportDir") or "").strip()


def latest_report_html(project_dir: str, udid: str = "") -> str:
    info = read_latest(project_dir, udid)
    html = str(info.get("reportHtml") or "").strip()
    if html and os.path.isfile(html):
        return html
    report_dir = str(info.get("reportDir") or "").strip()
    candidate = os.path.join(report_dir, "report.html")
    return candidate if os.path.isfile(candidate) else ""
