"""aapt 引导与 APK badging 解析（作为 pyaxmlparser 的回退方案）。

解析顺序：系统 PATH 上的 aapt → 已解压复用 → 从 Console ``resources/re_aapt`` 按平台解压。
"""

from __future__ import annotations

import platform
import re
import shutil
import stat
import subprocess
import zipfile
from pathlib import Path
from typing import Optional

# autopilot_platform/appparse/aapt.py → Console 仓库根
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_BUNDLE_DIR = _REPO_ROOT / "resources" / "re_aapt"
_EXTRACT_DIR = _REPO_ROOT / "resources" / "runpath_aapt"

_ZIPS = {
    "Windows": "aapt-windows.zip",
    "Darwin": "aapt-macos.zip",
    "Linux": "aapt-linux.zip",
}

_resolved: Optional[Path] = None


def _binary_name() -> str:
    return "aapt.exe" if platform.system() == "Windows" else "aapt"


def _scan(directory: Path) -> Optional[Path]:
    if not directory.exists():
        return None
    for c in directory.rglob(_binary_name()):
        if c.is_file():
            return c
    return None


def _extract_bundle() -> Optional[Path]:
    zip_name = _ZIPS.get(platform.system())
    if zip_name is None:
        return None
    archive = _BUNDLE_DIR / zip_name
    if not archive.exists():
        return None
    _EXTRACT_DIR.mkdir(parents=True, exist_ok=True)
    from autopilot_platform.core.safe_zip import safe_extractall

    with zipfile.ZipFile(archive) as zf:
        safe_extractall(zf, _EXTRACT_DIR)
    found = _scan(_EXTRACT_DIR)
    if found is not None and platform.system() != "Windows":
        try:
            found.chmod(found.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        except OSError:
            pass
    return found


def ensure_aapt() -> Optional[Path]:
    """解析可用 aapt 二进制（必要时解压 bundle）。返回路径或 None。"""
    global _resolved
    if _resolved is not None and _resolved.exists():
        return _resolved
    on_path = shutil.which("aapt")
    if on_path:
        _resolved = Path(on_path)
        return _resolved
    _resolved = _scan(_EXTRACT_DIR) or _extract_bundle()
    return _resolved


def available() -> bool:
    return ensure_aapt() is not None


_RE_PKG = re.compile(r"package: name='([^']+)'")
_RE_VN = re.compile(r"versionName='([^']*)'")
_RE_VC = re.compile(r"versionCode='([^']*)'")
_RE_ACT = re.compile(r"launchable-activity: name='([^']+)'")
_RE_LABEL = re.compile(r"application-label(?:-\w+)?:'([^']*)'")
_RE_MIN_SDK = re.compile(r"sdkVersion:'(\d+)'")
_RE_TARGET_SDK = re.compile(r"targetSdkVersion:'(\d+)'")
_RE_MAX_SDK = re.compile(r"maxSdkVersion:'(\d+)'")
_RE_PERMISSION = re.compile(r"uses-permission(?:-sdk-\d+)?: name='([^']+)'")
_RE_NATIVE = re.compile(r"native-code: (.+)")


def dump_badging(apk_path: str, timeout: int = 60) -> dict:
    """调用 aapt dump badging 并解析关键字段。无 aapt 时返回 {}。"""
    exe = ensure_aapt()
    if exe is None:
        return {}
    proc = subprocess.run(
        [str(exe), "dump", "badging", apk_path],
        capture_output=True,
        timeout=timeout,
    )
    text = proc.stdout.decode("utf-8", "replace")
    out: dict = {}
    if m := _RE_PKG.search(text):
        out["package"] = m.group(1)
    if m := _RE_VN.search(text):
        out["version_name"] = m.group(1)
    if m := _RE_VC.search(text):
        out["version_code"] = m.group(1)
    if m := _RE_ACT.search(text):
        out["main_activity"] = m.group(1)
    if m := _RE_LABEL.search(text):
        out["app_name"] = m.group(1)
    if m := _RE_MIN_SDK.search(text):
        out["min_sdk"] = m.group(1)
    if m := _RE_TARGET_SDK.search(text):
        out["target_sdk"] = m.group(1)
    if m := _RE_MAX_SDK.search(text):
        out["max_sdk"] = m.group(1)
    perms = sorted({m.group(1) for m in _RE_PERMISSION.finditer(text)})
    if perms:
        out["permissions"] = perms
    if m := _RE_NATIVE.search(text):
        out["native_abis"] = [x.strip("'") for x in m.group(1).split() if x.strip("'")]
    return out
