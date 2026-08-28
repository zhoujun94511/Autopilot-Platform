"""iOS 镜像状态（Console Runner 无 IDE 镜像 UI）。

仅保留执行核需要的最小 API：``capture_active`` 影响 WDA 隧道是否强制重建；
无采集进程时恒为 False。settings 仍可读 ``ios_mirror_source`` 配置键。
"""

from __future__ import annotations

import os
import platform

MIRROR_MJPEG = "mjpeg"
MIRROR_AUTO = "auto"
_VALID_MIRROR_SOURCES = {MIRROR_MJPEG, MIRROR_AUTO}


def _host_os() -> str:
    system = platform.system()
    if system == "Darwin":
        return "mac"
    if system == "Windows":
        return "windows"
    return "linux"


def normalize_mirror_source(mode: str = "") -> str:
    value = (mode or "").strip().lower()
    if not value:
        return MIRROR_AUTO
    if value == "qvh":
        return MIRROR_AUTO
    return value if value in _VALID_MIRROR_SOURCES else MIRROR_AUTO


def mirror_source_from_env() -> str:
    raw = os.getenv("IOS_MIRROR_SOURCE", "").strip().lower()
    return normalize_mirror_source(raw) if raw else ""


def resolve_mirror_source(mode: str = "", host: str = "") -> str:
    env_mode = mirror_source_from_env()
    if env_mode:
        chosen = env_mode
    else:
        chosen = normalize_mirror_source(mode)
    host = host or _host_os()
    if chosen == MIRROR_AUTO and host != "mac":
        return MIRROR_MJPEG
    return chosen


def set_capture_active(active: bool) -> None:
    """Console 无镜像采集进程；保留 API 兼容，忽略写入。"""
    _ = bool(active)


def capture_active() -> bool:
    """无 IDE 镜像时恒为 False（不强制因采集而重建 WDA 隧道）。"""
    return False
