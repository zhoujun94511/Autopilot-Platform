"""XAPK 解压与 Android 安装（Platform ap/ 切片）。"""

from __future__ import annotations

import os
import zipfile
from pathlib import Path
from unittest.mock import patch

from autopilot_platform.ap.mobile.xapk import (
    extract_xapk_apks,
    install_android_package,
    primary_apk_for_parse,
)


def test_extract_xapk_apks_nested(tmp_path: Path) -> None:
    xapk_path = tmp_path / "bundle.xapk"
    with zipfile.ZipFile(xapk_path, "w") as archive:
        archive.writestr("base.apk", b"base")
        archive.writestr("split/config.apk", b"split")
    apks = extract_xapk_apks(str(xapk_path), str(tmp_path / "work"))
    assert len(apks) == 2
    assert any(path.endswith("base.apk") for path in apks)


def test_install_android_package_xapk_uses_install_multiple(tmp_path: Path) -> None:
    xapk_path = tmp_path / "game.xapk"
    with zipfile.ZipFile(xapk_path, "w") as archive:
        archive.writestr("a.apk", b"a")
        archive.writestr("b.apk", b"b")

    calls: list[list[str]] = []

    def fake_run_adb(args, serial="", timeout=0):
        _ = serial, timeout
        calls.append(list(args))
        return "Success"

    with patch("autopilot_platform.ap.mobile.xapk.run_adb", fake_run_adb):
        out = install_android_package(str(xapk_path), serial="dev-1", replace=True)

    assert out == "Success"
    assert calls[0][0] == "install-multiple"
    assert "-r" in calls[0]
    assert "-t" in calls[0]


def test_primary_apk_for_parse_prefers_base(tmp_path: Path) -> None:
    xapk_path = tmp_path / "bundle.xapk"
    with zipfile.ZipFile(xapk_path, "w") as archive:
        archive.writestr("split.apk", b"x" * 20)
        archive.writestr("base.apk", b"y")

    with primary_apk_for_parse(str(xapk_path)) as parse_path:
        assert os.path.basename(parse_path) == "base.apk"
