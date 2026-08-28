"""后端标签与 Job backend_mode 匹配（Platform claim / Runner 跑前共用）。"""

from __future__ import annotations

from autopilot_platform.core.constants import (
    BACKEND_ANDROID_APPIUM,
    BACKEND_IOS_APPIUM,
    BACKEND_IOS_WDA,
)


def required_backends(platform: str, backend_mode: str) -> set[str] | None:
    """Job 所需后端标签集合；None 表示 auto。"""
    mode = (backend_mode or "auto").strip().lower()
    plat = (platform or "").strip().lower()
    if mode in ("", "auto"):
        return None
    if mode in ("uia2", "android-appium"):
        return {BACKEND_ANDROID_APPIUM}
    if mode in ("wda", "ios-wda"):
        return {BACKEND_IOS_WDA}
    if mode == "ios-appium":
        return {BACKEND_IOS_APPIUM}
    if mode == "appium":
        if plat == "ios":
            return {BACKEND_IOS_APPIUM}
        if plat == "android":
            return {BACKEND_ANDROID_APPIUM}
        return {BACKEND_ANDROID_APPIUM, BACKEND_IOS_APPIUM}
    return {mode}


def backends_ok(
    device_backends: list[str] | tuple[str, ...] | None,
    *,
    platform: str,
    backend_mode: str,
) -> bool:
    """旧 Runner 未上报 backends 时放行；有上报则须与 Job 要求有交集。"""
    backends = {str(x).strip() for x in (device_backends or []) if str(x).strip()}
    required = required_backends(platform, backend_mode)
    plat = (platform or "").strip().lower()
    if required is None:
        if not backends:
            return True
        if plat == "android":
            return BACKEND_ANDROID_APPIUM in backends
        if plat == "ios":
            return bool(backends & {BACKEND_IOS_APPIUM, BACKEND_IOS_WDA})
        return True
    if not backends:
        return True
    return bool(backends & required)
