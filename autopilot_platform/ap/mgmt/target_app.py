"""目标应用参数获取（真机 / 预设场景）。

设计生成 API 不含 packageName；转化自动化时需自行解析目标 App，
再写入 `mobile_app_start` 等会话前置。
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

from ..mobile.adb import run_adb


@dataclass(frozen=True)
class TargetAppParams:
    """转化自动化可用的目标应用参数。"""

    platform: str
    package_name: str
    udid: str = ""
    app_label: str = ""
    main_activity: str = ""
    version_name: str = ""
    source: str = ""  # preset|adb|explicit
    scenario: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def mobile_start_params(self) -> dict[str, str]:
        plat = (self.platform or "android").strip().lower()
        typ = "Android" if plat == "android" else "iOS"
        out = {"type": typ, "packageName": self.package_name}
        if self.main_activity and plat == "android":
            out["activityName"] = self.main_activity
        return out


# 内置场景：无需 APK，用系统应用做生成→转化联调
_SCENARIO_PRESETS: dict[str, dict[str, str]] = {
    "android_settings": {
        "platform": "android",
        "package_name": "com.android.settings",
        "app_label": "Settings",
        "requirement": (
            "在 Android 真机上打开系统设置应用，确认首页存在 Wi-Fi 或 WLAN 入口文案。"
            "只需 1 条用例：打开设置后断言 Wi-Fi/WLAN 可见。"
        ),
    },
}


def list_scenarios() -> list[str]:
    return sorted(_SCENARIO_PRESETS)


def scenario_requirement(scenario: str) -> str:
    key = (scenario or "").strip().lower()
    preset = _SCENARIO_PRESETS.get(key)
    if not preset:
        raise KeyError(f"unknown scenario: {scenario!r}; known={list_scenarios()}")
    return str(preset["requirement"])


def _adb(args: list[str], *, udid: str, timeout: int = 20) -> str:
    return run_adb(args, serial=(udid or "").strip(), timeout=timeout)


def _adb_soft(args: list[str], *, udid: str, timeout: int = 20) -> str:
    """adb 调用失败时返回空串（探测场景不向上抛）。"""
    import subprocess

    try:
        return _adb(args, udid=udid, timeout=timeout)
    except (RuntimeError, OSError, subprocess.TimeoutExpired):
        return ""


def _package_exists(udid: str, package: str) -> bool:
    out = _adb_soft(["shell", "pm", "path", package], udid=udid)
    if package in (out or "") and "package:" in (out or ""):
        return True
    out = _adb_soft(["shell", "pm", "list", "packages", package], udid=udid)
    return f"package:{package}" in (out or "").replace("\r", "")


def _resolve_settings_component(udid: str) -> tuple[str, str]:
    """通过打开 SETTINGS intent 解析真实包名/Activity（适配 MIUI 等）。"""
    _adb_soft(
        ["shell", "am", "start", "-a", "android.settings.SETTINGS", "-f", "0x10008000"],
        udid=udid,
    )
    import time

    time.sleep(0.8)
    dump = _adb_soft(["shell", "dumpsys", "window"], udid=udid, timeout=40)
    m = re.search(r"mCurrentFocus=Window\{[^}]*\s([^\s/]+)/([^\s}]+)", dump or "")
    if not m:
        dump = _adb_soft(
            ["shell", "dumpsys", "activity", "activities"], udid=udid, timeout=40
        )
        m = re.search(r"(?:mResumedActivity|topResumedActivity).*?\s([^\s/]+)/([^\s}]+)", dump or "")
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return "com.android.settings", ""


def _package_version(udid: str, package: str) -> str:
    out = _adb_soft(["shell", "dumpsys", "package", package], udid=udid, timeout=40)
    m = re.search(r"versionName=(\S+)", out or "")
    return (m.group(1) if m else "").strip()


def _resolve_wifi_label(udid: str) -> str:
    """根据 Settings 页面文案粗判 Wi-Fi / WLAN。"""
    _adb_soft(
        ["shell", "am", "start", "-a", "android.settings.SETTINGS", "-f", "0x10008000"],
        udid=udid,
    )
    _adb_soft(["shell", "uiautomator", "dump", "/sdcard/ap_target.xml"], udid=udid)
    xml = _adb_soft(["shell", "cat", "/sdcard/ap_target.xml"], udid=udid)
    if not xml:
        return "Wi-Fi"
    if "WLAN" in xml and "Wi-Fi" not in xml:
        return "WLAN"
    if "无线局域网" in xml:
        return "无线局域网"
    return "Wi-Fi"


def acquire_target_app(
    *,
    scenario: str = "android_settings",
    udid: str = "",
    package_name: str = "",
    platform: str = "",
    app_label: str = "",
    verify_installed: bool = True,
) -> TargetAppParams:
    """获取目标应用参数。

    优先级：显式 package_name > 场景预设；真机可校验已安装并补 version。
    android_settings 场景在 pm 探测失败时，会通过 SETTINGS intent 解析真实组件。
    """
    scen = (scenario or "").strip().lower() or "android_settings"
    preset = _SCENARIO_PRESETS.get(scen, {})
    plat = (platform or preset.get("platform") or "android").strip().lower()
    pkg = (package_name or preset.get("package_name") or "").strip()
    label = (app_label or preset.get("app_label") or "").strip()
    serial = (udid or "").strip()
    source = "explicit" if package_name.strip() else ("preset" if preset else "explicit")
    activity = ""

    if not pkg:
        raise ValueError("package_name 为空且场景无预设包名")

    version = ""
    if serial and plat == "android" and verify_installed:
        if not _package_exists(serial, pkg):
            if scen == "android_settings":
                resolved_pkg, resolved_act = _resolve_settings_component(serial)
                if resolved_pkg:
                    pkg = resolved_pkg
                    activity = resolved_act
                    source = f"{source}+intent"
                else:
                    raise RuntimeError(f"设备 {serial} 无法解析系统设置包名")
            else:
                raise RuntimeError(f"设备 {serial} 未安装目标包: {pkg}")
        else:
            source = f"{source}+adb"
        version = _package_version(serial, pkg)
        if scen == "android_settings" and not activity:
            _, activity = _resolve_settings_component(serial)

    return TargetAppParams(
        platform=plat,
        package_name=pkg,
        udid=serial,
        app_label=label or pkg,
        main_activity=activity,
        version_name=version,
        source=source,
        scenario=scen,
    )


def resolve_assert_target(udid: str, *, scenario: str = "android_settings") -> str:
    """为断言步解析本地化目标文案（Settings 场景）。"""
    if (scenario or "").strip().lower() != "android_settings":
        return "Wi-Fi"
    if not (udid or "").strip():
        return "Wi-Fi"
    try:
        return _resolve_wifi_label(udid.strip())
    except (RuntimeError, OSError, TypeError, ValueError):
        return "Wi-Fi"
