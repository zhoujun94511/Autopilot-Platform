"""被测 App 前台监视：启动后记住包名，失败时探测是否意外退出。

探测失败不得抛错，不能影响关键字执行。
"""

from __future__ import annotations

from typing import Any

TARGET_VAR = "__target_package__"

_LAUNCHERS = frozenset({
    "com.android.launcher",
    "com.android.launcher3",
    "com.google.android.apps.nexuslauncher",
    "com.miui.home",
    "com.huawei.android.launcher",
    "com.sec.android.app.launcher",
    "com.apple.springboard",
    "com.apple.PreBoard",
})

_CRASH_MSG_HINTS = (
    "instrumentation process is not running",
    "app crashed",
    "application crash",
    "has died",
    "process crash",
    "crashlytics",
    "fatal exception",
)


def remember_target_package(ctx: Any, package: str) -> None:
    pkg = str(package or "").strip()
    if not pkg or ctx is None:
        return
    setter = getattr(ctx, "set_var", None)
    if callable(setter):
        setter(TARGET_VAR, pkg)


def expected_package(ctx: Any) -> str:
    if ctx is None:
        return ""
    getter = getattr(ctx, "get_var", None)
    if not callable(getter):
        return ""
    try:
        return str(getter(TARGET_VAR) or "").strip()
    except (AttributeError, TypeError, RuntimeError):
        return ""


def probe_foreground_package(ctx: Any) -> str:
    """当前前台包名 / Bundle ID；取不到返回空串。"""
    if ctx is None:
        return ""
    mgr = getattr(ctx, "appium", None)
    if mgr is None:
        return ""
    try:
        drv = None
        optional = getattr(mgr, "optional_driver", None)
        if callable(optional):
            drv = optional()
        if drv is None:
            driver_fn = getattr(mgr, "driver", None)
            if callable(driver_fn):
                drv = driver_fn()
        if drv is None:
            return ""
        pkg = str(getattr(drv, "current_package", "") or "").strip()
        if pkg:
            return pkg
        plat = str(getattr(mgr, "platform", "") or "").strip().lower()
        if plat == "ios":
            from ..mobile.ios import current_bundle_id, driver_backend

            backend = driver_backend(drv, getattr(mgr, "backend", "") or "")
            return str(current_bundle_id(drv, backend) or "").strip()
    except (OSError, RuntimeError, AttributeError, TypeError, ValueError):
        return ""
    return ""


def looks_like_launcher(package: str) -> bool:
    pkg = str(package or "").strip().lower()
    if not pkg:
        return False
    if pkg in _LAUNCHERS:
        return True
    return pkg.endswith(".launcher") or pkg.endswith(".springboard")


def unexpected_exit(expected: str, current: str) -> bool:
    """目标包已记录，但前台变成桌面/启动器（疑似崩溃）。"""
    exp = str(expected or "").strip()
    cur = str(current or "").strip()
    if not exp:
        return False
    if not cur:
        return False
    if cur.lower() == exp.lower():
        return False
    return looks_like_launcher(cur)


def message_suggests_crash(message: str) -> bool:
    blob = str(message or "").lower()
    return any(hint in blob for hint in _CRASH_MSG_HINTS)


def detect_crash_on_fail(ctx: Any, message: str = "") -> str:
    """失败时若判定崩溃，返回期望包名；否则空串。"""
    if message_suggests_crash(message):
        return expected_package(ctx) or "unknown"
    exp = expected_package(ctx)
    if not exp:
        return ""
    current = probe_foreground_package(ctx)
    if unexpected_exit(exp, current):
        return exp
    return ""
