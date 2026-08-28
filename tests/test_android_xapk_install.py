"""Android XAPK 安装单元测试。"""

from __future__ import annotations

import importlib
import os
import sys
import zipfile
from unittest.mock import MagicMock

import pytest


@pytest.fixture()
def android_modules(monkeypatch):
    monkeypatch.setitem(sys.modules, "adbutils", MagicMock())
    for key in list(sys.modules):
        if key.startswith("autopilot_platform.runner.remote.android"):
            del sys.modules[key]
    app_manager = importlib.import_module(
        "autopilot_platform.runner.remote.android.app_manager"
    )
    file_transfer = importlib.import_module(
        "autopilot_platform.runner.remote.android.file_transfer"
    )
    return app_manager, file_transfer


def test_extract_xapk_apks_finds_nested_apks(tmp_path, android_modules):
    app_manager, _ = android_modules
    xapk_path = tmp_path / "bundle.xapk"
    with zipfile.ZipFile(xapk_path, "w") as archive:
        archive.writestr("base.apk", b"base")
        archive.writestr("split/config.apk", b"split")
    apks = app_manager.extract_xapk_apks(str(xapk_path), str(tmp_path / "work"))
    assert len(apks) == 2
    assert any(path.endswith("base.apk") for path in apks)
    assert any(path.endswith(os.path.join("split", "config.apk")) for path in apks)


def test_install_local_apk_xapk_uses_install_multiple(
    monkeypatch, tmp_path, android_modules
):
    app_manager, _ = android_modules
    xapk_path = tmp_path / "game.xapk"
    with zipfile.ZipFile(xapk_path, "w") as archive:
        archive.writestr("a.apk", b"a")
        archive.writestr("b.apk", b"b")

    commands: list[list[str]] = []

    def fake_install(device_id: str, local_paths: list[str]) -> str:
        assert device_id == "serial-1"
        assert len(local_paths) == 2
        commands.append(local_paths)
        return "Success"

    monkeypatch.setattr(app_manager, "_install_local_paths", fake_install)
    result = app_manager.install_local_apk("serial-1", str(xapk_path))
    assert result["ok"] is True
    assert result["filename"] == "game.xapk"
    assert result["split_count"] == 2
    assert commands


def test_file_transfer_end_installs_xapk(android_modules):
    import base64

    _, file_transfer = android_modules
    installed: list[str] = []

    def fake_install(local_path: str, force: bool) -> dict[str, object]:
        installed.append(f"{local_path}:{force}")
        return {"ok": True, "action": "install", "filename": "demo.xapk"}

    replies: list[dict] = []
    event = {
        "id": "transfer-xapk",
        "name": "demo.xapk",
        "size": 3,
        "remote": "/sdcard/Download/",
    }
    file_transfer.begin(event, replies.append)
    file_transfer.chunk(
        {
            "id": event["id"],
            "seq": 0,
            "data": base64.b64encode(b"xpk").decode(),
        },
        replies.append,
    )
    file_transfer.end(
        {"id": event["id"], "install": True},
        object(),
        replies.append,
        install_apk=fake_install,
    )
    assert installed
    assert replies[-1]["t"] == "file.done"


def test_extract_xapk_empty_raises(tmp_path, android_modules):
    app_manager, _ = android_modules
    xapk_path = tmp_path / "empty.xapk"
    with zipfile.ZipFile(xapk_path, "w") as archive:
        archive.writestr("readme.txt", b"no apk here")
    with pytest.raises(ValueError, match="未包含 APK"):
        app_manager.extract_xapk_apks(str(xapk_path), str(tmp_path / "work"))


def test_is_installable_package(android_modules):
    app_manager, _ = android_modules
    assert app_manager.is_installable_package("game.xapk") is True
    assert app_manager.is_installable_package("game.apk") is True
    assert app_manager.is_installable_package("readme.txt") is False
