"""app_manager.list_packages 筛选与元数据。"""

from __future__ import annotations

import importlib
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


@pytest.fixture()
def app_manager(monkeypatch):
    monkeypatch.setitem(sys.modules, "adbutils", MagicMock())
    for key in list(sys.modules):
        if key.startswith("autopilot_platform.runner.remote.android"):
            del sys.modules[key]
    return importlib.import_module(
        "autopilot_platform.runner.remote.android.app_manager"
    )


class _FakeStat:
    size = 4096


class _FakeSync:
    @staticmethod
    def stat(_path: str) -> _FakeStat:
        return _FakeStat()


def test_list_packages_filters_third_party_and_enriches_version(monkeypatch, app_manager):
    calls: list[str] = []

    def fake_shell(_device_id: str, command: str, _timeout: float = 30.0) -> str:
        calls.append(command)
        if command == "pm list packages -f -3":
            return (
                "package:/data/app/user.apk=com.user.app\n"
                "package:/system/app/sys.apk=com.android.sys"
            )
        if command == "pm list packages -f -s":
            return "package:/system/app/sys.apk=com.android.sys"
        if command == "dumpsys package packages":
            return (
                "  Package [com.user.app]\n"
                "    versionName=2.1.0\n"
                "  Package [com.android.sys]\n"
                "    versionName=14"
            )
        raise AssertionError(f"unexpected shell: {command}")

    monkeypatch.setattr(app_manager, "_shell", fake_shell)
    monkeypatch.setattr(
        app_manager,
        "_device",
        lambda _device_id: SimpleNamespace(sync=_FakeSync()),
    )

    result = app_manager.list_packages("serial-1", "third_party")
    packages = {item["package"]: item for item in result["packages"]}

    assert "com.user.app" in packages
    assert "com.android.sys" not in packages
    assert packages["com.user.app"]["system"] is False
    assert packages["com.user.app"]["version_name"] == "2.1.0"
    assert packages["com.user.app"]["size"] == 0
    assert "pm list packages -f -3" in calls


def test_list_packages_system_scope(monkeypatch, app_manager):
    calls: list[str] = []

    def fake_shell(_device_id: str, command: str, _timeout: float = 30.0) -> str:
        calls.append(command)
        if command == "pm list packages -f -s":
            return "package:/system/app/sys.apk=com.android.sys"
        if command == "dumpsys package packages":
            return "  Package [com.android.sys]\n    versionName=14"
        raise AssertionError(f"unexpected shell: {command}")

    monkeypatch.setattr(app_manager, "_shell", fake_shell)
    monkeypatch.setattr(
        app_manager,
        "_device",
        lambda _device_id: SimpleNamespace(sync=_FakeSync()),
    )

    result = app_manager.list_packages("serial-1", "system")
    assert [item["package"] for item in result["packages"]] == ["com.android.sys"]
    assert result["packages"][0]["system"] is True
    assert result["scope"] == "system"
    # 系统 scope 不应再额外拉一遍 -s 做集合比对
    assert calls.count("pm list packages -f -s") == 1
