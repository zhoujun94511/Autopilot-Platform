"""Android SDK / adb 环境解析（供 Appium UiAutomator2 与真机工具）。"""

from __future__ import annotations

import os
from pathlib import Path

from ._paths import REPO_ROOT


def resolve_android_sdk_root() -> Path | None:
    """解析 ANDROID_SDK_ROOT（Appium UiAutomator2 必需）。"""
    for key in ("ANDROID_SDK_ROOT", "ANDROID_HOME"):
        raw = (os.getenv(key) or "").strip()
        if raw:
            p = Path(raw).expanduser()
            if p.is_dir():
                return p
    # macOS 默认 Android Studio 路径
    mac_default = Path.home() / "Library/Android/sdk"
    if mac_default.is_dir() and (mac_default / "platform-tools").is_dir():
        return mac_default
    # 项目内置 platform-tools（仅 adb，无 build-tools 时 UiAutomator2 可能仍失败）
    bundled = REPO_ROOT / "resources" / "runpath"
    if (bundled / "platform-tools").is_dir():
        return bundled
    return None


def apply_android_env() -> Path | None:
    """将 SDK/adb 写入当前进程环境（best-effort，供 Appium 子进程继承）。"""
    from .adb import ensure_adb

    sdk = resolve_android_sdk_root()
    if sdk is not None:
        os.environ.setdefault("ANDROID_HOME", str(sdk))
        os.environ.setdefault("ANDROID_SDK_ROOT", str(sdk))
    adb = ensure_adb()
    if adb is not None:
        os.environ.setdefault("ANDROID_ADB", str(adb))
        pt = adb.parent
        if pt.name == "platform-tools":
            cur = os.environ.get("PATH", "")
            if str(pt) not in cur.split(os.pathsep):
                os.environ["PATH"] = str(pt) + os.pathsep + cur
    return sdk
