"""adb 引导与命令执行。

解析顺序：
1. 系统 PATH / 环境变量已有 adb → 直接用（尊重用户工具链）。
2. 已解压的 resources/runpath/ 下复用。
3. 按当前平台从 resources/re_adb/platform-tools-latest-<os>.zip 解压到 runpath 再用。
解析到的目录会前插到 PATH，供 appium/其它子进程继承。

mobile 关键字里凡依赖 adb 的，先 ensure_adb() 再 adb_shell()/run_adb()。
无 adb 资源或无设备时，调用方得到明确异常（而非静默 NOIMPL）。

AUD-2026-10（命令面）：
- ``adb_shell(command: str)`` 是**产品能力**（内部 API），无「任意 shell」公开关键字。
- 用例经关键字参数间接插值时，插值片段须 ``require_adb_shell_safe_token`` /
  ``require_android_package``；每次 shell 打审计日志。
- Intent / Authoring 默认拒绝 irreversible（卸载 / monkey / reset 等），勿向 NL 暴露 raw shell。
"""

from __future__ import annotations

import logging
import os
import platform
import re
import shutil
import stat
import subprocess
import zipfile
from pathlib import Path
from typing import Optional

from ._paths import REPO_ROOT as _REPO_ROOT

_log = logging.getLogger(__name__)

# getprop 键、组件名等：单 token，禁止空白与 shell 元字符
_SAFE_TOKEN_RE = re.compile(r"^[A-Za-z0-9._:/=@+\-]+$")
_ANDROID_PKG_RE = re.compile(r"^[A-Za-z][A-Za-z0-9._]*$")
_INPUT_META_RE = re.compile(r"[;&|`$<>\n\r]")
_BUNDLE_DIR = _REPO_ROOT / "resources" / "re_adb"
_EXTRACT_DIR = _REPO_ROOT / "resources" / "runpath"

_ZIPS = {
    "Windows": "platform-tools-latest-windows.zip",
    "Darwin": "platform-tools-latest-darwin.zip",
    "Linux": "platform-tools-latest-linux.zip",
}

_resolved_adb: Optional[Path] = None  # 进程内缓存


def _binary_name() -> str:
    return "adb.exe" if platform.system() == "Windows" else "adb"


def _scan_extracted() -> Optional[Path]:
    if not _EXTRACT_DIR.exists():
        return None
    for candidate in _EXTRACT_DIR.rglob(_binary_name()):
        if candidate.is_file():
            return candidate
    return None


def _extract_bundle() -> Optional[Path]:
    system = platform.system()
    zip_name = _ZIPS.get(system)
    if zip_name is None:
        _log.warning("adb: 无该平台的 bundle: %s", system)
        return None
    archive = _BUNDLE_DIR / zip_name
    if not archive.exists():
        _log.warning("adb: bundle 缺失: %s", archive)
        return None
    _EXTRACT_DIR.mkdir(parents=True, exist_ok=True)
    from autopilot_platform.ap.runtime.safe_zip import safe_extractall

    with zipfile.ZipFile(archive) as zf:
        safe_extractall(zf, _EXTRACT_DIR)
    found = _scan_extracted()
    if found is not None and system != "Windows":
        # POSIX zip 不保留可执行位，补回
        for f in [found, *found.parent.glob("fastboot"), *found.parent.glob("mke2fs*")]:
            try:
                f.chmod(f.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            except OSError:
                pass
    if found is not None and system == "Darwin":
        try:
            subprocess.run(["xattr", "-dr", "com.apple.quarantine", str(found.parent)],
                           check=False, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            pass
    return found


def _prepend_path(adb_dir: str) -> None:
    cur = os.environ.get("PATH", "")
    parts = cur.split(os.pathsep) if cur else []
    if adb_dir not in parts:
        os.environ["PATH"] = adb_dir + os.pathsep + cur


def ensure_adb() -> Optional[Path]:
    """解析可用 adb 二进制（必要时解压 bundle）。返回绝对路径或 None。"""
    global _resolved_adb
    if _resolved_adb is not None and _resolved_adb.exists():
        return _resolved_adb
    # (1) 环境变量 / PATH
    env_adb = os.getenv("ADBUTILS_ADB_PATH") or os.getenv("ADB_PATH")
    if env_adb and Path(env_adb).exists():
        _resolved_adb = Path(env_adb)
        return _resolved_adb
    on_path = shutil.which("adb")
    if on_path:
        _resolved_adb = Path(on_path)
        return _resolved_adb
    # (2) 已解压复用 (3) 解压 bundle
    found = _scan_extracted() or _extract_bundle()
    if found is None:
        _log.error("adb: PATH 无 adb 且 bundle 解压失败")
        return None
    _prepend_path(str(found.parent))
    _resolved_adb = found
    return found


def adb_available() -> bool:
    return ensure_adb() is not None


def require_adb_shell_safe_token(value: str, *, what: str = "参数") -> str:
    """校验将插入 ``adb shell`` 字符串的单 token（AUD-2026-10）。"""
    s = str(value or "").strip()
    if not s:
        raise ValueError(f"adb shell {what} 不能为空（AUD-2026-10）")
    if not _SAFE_TOKEN_RE.fullmatch(s):
        raise ValueError(
            f"adb shell {what} 含非法字符或空白（AUD-2026-10）: {s[:80]!r}"
        )
    return s


def require_android_package(value: str) -> str:
    """校验 Android 包名（用于 force-stop / monkey -p / uninstall）。"""
    s = str(value or "").strip()
    if not s or not _ANDROID_PKG_RE.fullmatch(s):
        raise ValueError(f"非法 Android 包名（AUD-2026-10）: {s[:80]!r}")
    return s


def require_adb_input_safe_text(value: str) -> str:
    """``input text`` 载荷：允许空格（转 %s），拒绝 shell 元字符。"""
    s = "" if value is None else str(value)
    if _INPUT_META_RE.search(s):
        raise ValueError(
            f"adb 输入文本含 shell 元字符（AUD-2026-10）: {s[:80]!r}"
        )
    return s


def audit_adb_shell(command: str, *, serial: str = "", via: str = "adb_shell") -> None:
    """审计模型：记录将执行的 shell（截断），不记录设备侧 stdout。"""
    _log.info(
        "AUD-2026-10 %s serial=%s cmd=%s",
        via,
        serial or "-",
        (command or "")[:240],
    )


_HOST_ADB_CMDS = frozenset({"devices", "start-server", "version", "help", "reconnect"})
_FORBIDDEN_ADB_CMDS = frozenset({"kill-server"})


def assert_adb_invocation(args: list[str], serial: str = "") -> None:
    """禁止 kill-server；设备向命令必须带 serial 或 args 内已有 -s。"""
    tokens = [str(a) for a in (args or [])]
    if any(t in _FORBIDDEN_ADB_CMDS for t in tokens):
        raise RuntimeError(
            "禁止 adb kill-server：会中断本机全部 Android 设备（全机共用一个 adb-server）"
        )
    if (serial or "").strip() or "-s" in tokens:
        return
    head = tokens[0] if tokens else ""
    if head in _HOST_ADB_CMDS:
        return
    raise RuntimeError(
        "adb 设备向命令必须指定 serial（-s UDID），避免多机时打到默认设备: "
        + " ".join(tokens[:8])
    )


def run_adb(args: list[str], serial: str = "", timeout: int = 30) -> str:
    """执行 adb 命令，返回 stdout 文本。无 adb 时抛 RuntimeError。"""
    exe = ensure_adb()
    if exe is None:
        raise RuntimeError("未找到 adb，且 resources/re_adb 无当前平台的 platform-tools")
    assert_adb_invocation(args, serial)
    cmd = [str(exe)]
    if serial:
        cmd += ["-s", serial]
    cmd += args
    proc = subprocess.run(cmd, capture_output=True, timeout=timeout)
    out = proc.stdout.decode("utf-8", "replace")
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", "replace")
        raise RuntimeError(f"adb 命令失败({proc.returncode}): {' '.join(args)}\n{err or out}")
    return out


def adb_shell(command: str, serial: str = "", timeout: int = 30) -> str:
    """执行 adb shell（内部产品能力；无公开「任意 shell」关键字）。"""
    cmd = (command or "").strip()
    if not cmd:
        raise RuntimeError("adb shell 命令为空")
    audit_adb_shell(cmd, serial=serial, via="adb_shell")
    return run_adb(["shell", cmd], serial=serial, timeout=timeout)
