"""iOS 无障碍快捷开关：对齐 WebAppFlaskauto-iOS ``ios assistivetouch|voiceover|zoom``。

go-ios 走 usbmux，不依赖 WDA / RSD 隧道。
"""

from __future__ import annotations

import json
from typing import Any

from autopilot_platform.ap.mobile.ios_bootstrap import resolve_go_ios
from autopilot_platform.ap.runtime.subproc import run as hidden_run

FEATURES = ("assistivetouch", "voiceover", "zoom")
ACTIONS = ("toggle", "enable", "disable", "get")


def _parse_enabled(stdout: str) -> bool | None:
    """go-ios 成功时 stdout 常带 JSON 行，键名含 Enabled（如 AssistiveTouchEnabled）。"""
    for line in reversed((stdout or "").strip().splitlines()):
        text = line.strip()
        if not text.startswith("{"):
            continue
        try:
            data = json.loads(text)
        except ValueError:
            continue
        if not isinstance(data, dict):
            continue
        for key, value in data.items():
            if "enabled" in str(key).lower():
                return bool(value)
    return None


def run(udid: str, feature: str, action: str = "toggle") -> dict[str, Any]:
    name = (feature or "").strip().lower()
    verb = (action or "toggle").strip().lower()
    if name not in FEATURES:
        raise ValueError(f"未知无障碍项 '{feature}'（{'/'.join(FEATURES)}）")
    if verb not in ACTIONS:
        raise ValueError(f"未知无障碍动作 '{action}'（{'/'.join(ACTIONS)}）")
    executable = resolve_go_ios()
    if executable is None:
        raise RuntimeError("未找到 go-ios，无法切换 iOS 无障碍")
    completed = hidden_run(
        [str(executable), "--udid", udid, name, verb],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
    )
    output = (completed.stdout or "").strip()
    err = (completed.stderr or "").strip()
    if completed.returncode != 0:
        raise RuntimeError(err or output or f"go-ios {name} {verb} 失败")
    return {
        "feature": name,
        "action": verb,
        "enabled": _parse_enabled(output),
        "ok": True,
    }
