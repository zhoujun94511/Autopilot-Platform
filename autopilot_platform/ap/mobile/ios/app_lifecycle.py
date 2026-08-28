"""iOS 应用生命周期：terminate / activate / launch / reset（WDA-direct 与 Appium iOS 统一入口）。"""

from __future__ import annotations

from typing import Any, Callable, Optional

from .runtime import is_wda_backend


def current_bundle_id(driver: Any, backend: str = "") -> str:
    caps = getattr(driver, "capabilities", None) or {}
    bid = str(caps.get("bundleId") or caps.get("app") or "").strip()
    if bid:
        return bid
    if is_wda_backend(backend, driver):
        return str(getattr(driver, "_bundle_id", "") or "").strip()
    # noinspection PyBroadException
    try:
        return str(getattr(driver, "current_package", "") or "").strip()
    except Exception:
        return ""


def terminate_app(driver: Any, backend: str, bundle_id: str) -> None:
    if not bundle_id:
        return
    if is_wda_backend(backend, driver):
        driver.terminate_app(bundle_id)
        return
    # noinspection PyBroadException
    try:
        driver.terminate_app(bundle_id)
    except Exception:
        pass


def activate_app(driver: Any, backend: str, bundle_id: str) -> None:
    if not bundle_id:
        return
    if is_wda_backend(backend, driver):
        driver.activate_app(bundle_id)
        return
    driver.activate_app(bundle_id)


def launch_app(driver: Any, backend: str, bundle_id: str = "") -> None:
    bid = bundle_id or current_bundle_id(driver, backend)
    if is_wda_backend(backend, driver):
        if bid:
            driver.launch_app(bid)
        elif hasattr(driver, "launch_app"):
            driver.launch_app()
        return
    if bid:
        # noinspection PyBroadException
        try:
            driver.terminate_app(bid)
        except Exception:
            pass
        driver.activate_app(bid)
    elif hasattr(driver, "launch_app"):
        driver.launch_app()


def reset_app(
    driver: Any,
    backend: str,
    bundle_id: str = "",
    ctx: Any = None,
) -> None:
    bid = bundle_id or current_bundle_id(driver, backend)
    if not bid and ctx is not None:
        from .monkey.bundle import resolve_target_bundle_id
        bid = resolve_target_bundle_id(ctx)
    if bid:
        terminate_app(driver, backend, bid)
        activate_app(driver, backend, bid)
        return
    if is_wda_backend(backend, driver):
        from ...keywords.registry import KeywordError
        raise KeywordError(
            "WDA-direct 重启应用需已知 bundleId（请先 mobile_app_start / "
            "mobile_app_install_and_open，或设置变量 app_package；"
            "无 bundle 时请用 mobile_app_close + mobile_app_start）"
        )
    if hasattr(driver, "reset"):
        driver.reset()


def is_app_installed(
    bundle_id: str,
    *,
    udid: str = "",
    driver: Any = None,
    backend: str = "",
    device_check: Optional[Callable[[str, str], bool]] = None,
) -> bool:
    """WDA/Appium driver 优先；无 driver 或失败时走设备层 InstallationProxy。"""
    if not bundle_id:
        return False
    if driver is not None:
        if is_wda_backend(backend, driver) and hasattr(driver, "is_app_installed"):
            return bool(driver.is_app_installed(bundle_id))
        # noinspection PyBroadException
        try:
            if hasattr(driver, "is_app_installed"):
                return bool(driver.is_app_installed(bundle_id))
        except Exception:
            pass
    if device_check is not None:
        return bool(device_check(bundle_id, udid))
    return False
