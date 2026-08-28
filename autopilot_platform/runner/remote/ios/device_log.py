"""iOS 设备 syslog：独立 ``go-ios syslog --parse`` 子进程，不走画面/命令通道。"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from contextlib import suppress

_log = logging.getLogger(__name__)


def readable(line: str) -> str:
    """go-ios ``--parse`` 输出 JSON 时取 ``msg``。"""
    text = (line or "").rstrip("\r\n")
    if text.startswith("{"):
        with suppress(ValueError, TypeError):
            obj = json.loads(text)
            if isinstance(obj, dict):
                message = str(obj.get("msg") or obj.get("message") or text)
                level = str(obj.get("level") or obj.get("lvl") or "").strip()
                if level and f"<{level}>" not in message:
                    return f"<{level}> {message}"
                return message
    return text


def spawn(udid: str) -> subprocess.Popen[str]:
    from autopilot_platform.ap.mobile.ios_bootstrap import resolve_go_ios

    executable = resolve_go_ios()
    if executable is None:
        raise RuntimeError("未找到 go-ios")
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP
        no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        flags |= no_window
    _log.info("[device-log] ios syslog start %s", udid[:12])
    return subprocess.Popen(
        [str(executable), "--udid", udid, "syslog", "--parse"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        creationflags=flags,
    )
