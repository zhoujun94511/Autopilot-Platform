"""Android 设备 logcat：独立 ``adb logcat`` 子进程，不走 ADB worker / DataChannel。"""

from __future__ import annotations

import logging
import subprocess
import sys
from typing import Optional

_log = logging.getLogger(__name__)

_VALID_LEVELS = {"V", "D", "I", "W", "E", "F", "S"}


def build_filterspec(level: str, tag: Optional[str] = None) -> str:
    level = (level or "I").upper()
    if level not in _VALID_LEVELS:
        level = "I"
    if tag:
        tag = tag.replace(":", "_").replace(" ", "_")[:64]
        return f"{tag}:{level} *:S"
    return f"*:{level}"


def _adb_executable() -> str:
    try:
        from adbutils import adb  # type: ignore[import-untyped]

        path = str(adb.adb_path() or "").strip()
        if path:
            return path
    except Exception as exc:  # noqa: BLE001
        _log.debug("adb.adb_path: %s", exc)
    return "adb"


def spawn(device_id: str, level: str = "I", tag: str = "") -> subprocess.Popen[str]:
    filterspec = build_filterspec(level, tag or None)
    cmd = [
        _adb_executable(),
        "-s",
        device_id,
        "shell",
        "logcat",
        "-v",
        "threadtime",
        filterspec,
    ]
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP
        no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        flags |= no_window
    _log.info("[device-log] android start %s %s", device_id[:12], filterspec)
    return subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        creationflags=flags,
    )


def clear(device_id: str) -> bool:
    cmd = [_adb_executable(), "-s", device_id, "shell", "logcat", "-c"]
    try:
        completed = subprocess.run(
            cmd,
            check=False,
            timeout=10,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return completed.returncode == 0
    except (OSError, subprocess.TimeoutExpired) as exc:
        _log.warning("[device-log] android clear %s failed: %s", device_id[:12], exc)
        return False
