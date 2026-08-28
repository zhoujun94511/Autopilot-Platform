"""XAPK 解压与 adb install / install-multiple 安装。"""

from __future__ import annotations

import os
import tempfile
import zipfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from autopilot_platform.appparse.errors import PackageError

from .adb import run_adb

ANDROID_PACKAGE_SUFFIXES = (".apk", ".apex", ".xapk")


def is_xapk_path(path: str) -> bool:
    return str(path or "").lower().endswith(".xapk")


def is_android_package_path(path: str) -> bool:
    return str(path or "").lower().endswith(ANDROID_PACKAGE_SUFFIXES)


def extract_xapk_apks(xapk_path: str, temp_dir: str) -> list[str]:
    """解压 XAPK（zip），递归收集其中全部 .apk 路径。"""
    extract_dir = os.path.join(temp_dir, Path(xapk_path).stem or "xapk")
    os.makedirs(extract_dir, exist_ok=True)
    with zipfile.ZipFile(xapk_path, "r") as archive:
        archive.extractall(extract_dir)
    apk_paths: list[str] = []
    for root, _dirs, files in os.walk(extract_dir):
        for name in files:
            if name.lower().endswith(".apk"):
                apk_paths.append(os.path.join(root, name))
    apk_paths.sort()
    if not apk_paths:
        raise PackageError("XAPK 中未包含 APK 文件")
    return apk_paths


def _pick_primary_apk(apk_paths: list[str]) -> str:
    for path in apk_paths:
        base = os.path.basename(path).lower()
        if base in ("base.apk", "master.apk"):
            return path
    return max(apk_paths, key=lambda p: os.path.getsize(p))


@contextmanager
def primary_apk_for_parse(package_path: str) -> Iterator[str]:
    """解析包名时，XAPK 会先解压到临时目录再取主 APK。"""
    if not is_xapk_path(package_path):
        yield package_path
        return
    with tempfile.TemporaryDirectory(prefix="autopilot_xapk_") as temp_dir:
        apks = extract_xapk_apks(package_path, temp_dir)
        yield _pick_primary_apk(apks)


def install_android_package(
    package_path: str,
    *,
    serial: str = "",
    replace: bool = False,
    timeout: int = 300,
) -> str:
    """安装 .apk / .apex / .xapk；XAPK 走 adb install-multiple。"""
    if is_xapk_path(package_path):
        with tempfile.TemporaryDirectory(prefix="autopilot_xapk_") as temp_dir:
            apk_paths = extract_xapk_apks(package_path, temp_dir)
            return _adb_install_paths(
                apk_paths, serial=serial, replace=replace, timeout=timeout
            )
    return _adb_install_paths(
        [package_path], serial=serial, replace=replace, timeout=timeout
    )


def _adb_install_paths(
    local_paths: list[str],
    *,
    serial: str,
    replace: bool,
    timeout: int,
) -> str:
    if not local_paths:
        raise PackageError("缺少待安装 APK")
    command: list[str] = [
        "install-multiple" if len(local_paths) > 1 else "install",
    ]
    if replace:
        command.append("-r")
    command.append("-t")
    command.extend(local_paths)
    return run_adb(command, serial=serial, timeout=timeout)
