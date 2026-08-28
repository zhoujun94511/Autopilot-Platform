"""移动端后端选择：按「目标平台(Android/iOS) × 宿主系统(Windows/Mac/Linux)」分支。

会话层（元素/截图/滑动）：
  - Android：各宿主系统统一走 Appium(uiautomator2)。
  - iOS：
      - Mac：Appium(xcuitest) + go-ios 准备 WDA + webDriverAgentUrl 直连（golden 参考）。
      - Windows/Linux：Appium 的 iOS17+ RemoteXPC 隧道(appium-ios-remotexpc)不支持 Windows，
        故走「直连 WDA HTTP」后端（go-ios 隧道/runwda + pymobiledevice3 转发到本机 WDA）。

装/卸不在此模块：全平台统一走设备层（session.py 的 adb / ios_install_app），
与宿主 OS 无关，亦不依赖 Appium driver。详见 docs/setup/android.md、docs/setup/ios.md。

可用环境变量 IOS_BACKEND=appium|wda 强制覆盖 iOS 会话后端。
"""

from __future__ import annotations

import os
import platform as _platform

DEFAULT_BACKEND_MODE = "auto"
_VALID_BACKEND_MODES = {DEFAULT_BACKEND_MODE, "appium", "wda"}


def host_os() -> str:
    """宿主系统标识：windows / mac / linux。"""
    return {"Windows": "windows", "Darwin": "mac", "Linux": "linux"}.get(
        _platform.system(), "linux")


def is_ios(os_type: str) -> bool:
    return (os_type or "Android").lower().startswith("ios")


def normalize_backend_mode(mode: str = "") -> str:
    value = (mode or "").strip().lower()
    return value if value in _VALID_BACKEND_MODES else DEFAULT_BACKEND_MODE


def backend_mode_from_env() -> str:
    return normalize_backend_mode(os.getenv("IOS_BACKEND_MODE") or os.getenv("IOS_BACKEND") or "")


def resolve_backend_mode(os_type: str, mode: str = "") -> str:
    if not is_ios(os_type):
        return "appium"
    chosen = normalize_backend_mode(mode)
    if chosen != DEFAULT_BACKEND_MODE:
        return chosen
    env_mode = backend_mode_from_env()
    if env_mode != DEFAULT_BACKEND_MODE:
        return env_mode
    return DEFAULT_BACKEND_MODE


def select_backend(os_type: str, host: str = "", mode: str = "") -> str:
    """返回该 (目标平台, 宿主系统) 应使用的后端：'appium' 或 'wda'。"""
    host = host or host_os()
    if not is_ios(os_type):
        return "appium"                      # Android：全平台 Appium
    forced = resolve_backend_mode(os_type, mode=mode)
    if forced in ("appium", "wda"):
        return forced
    return "appium" if host == "mac" else "wda"   # iOS：Mac→Appium，Win/Linux→直连 WDA


def pretty_backend_name(backend: str) -> str:
    """UI 展示：appium → Appium，wda → WDA-direct。"""
    return {"appium": "Appium", "wda": "WDA-direct"}.get(
        (backend or "").strip().lower(), backend or "")


def pretty_backend_mode_name(mode: str) -> str:
    """UI 展示：auto/appium/wda 决策模式名称。"""
    return {"auto": "Auto", "appium": "Appium", "wda": "WDA-direct"}.get(
        normalize_backend_mode(mode), "Auto")


def effective_ios_backend_label(mode: str = "", host: str = "") -> str:
    """UI：iOS 在当前宿主与 backendMode 下实际会走 Appium 还是 WDA-direct。"""
    return pretty_backend_name(select_backend("ios", host=host, mode=mode))


def ios_uses_appium_backend(mode: str = "", host: str = "") -> bool:
    """iOS 是否走 Appium 会话后端（Mac + auto/appium）。

    检视快照与镜像控制共用此判断；与画面源（AVF/MJPEG/grab）正交。
    """
    return select_backend("ios", host=host or host_os(), mode=mode) == "appium"


def ios_inspector_uses_appium(mode: str = "", host: str = "") -> bool:
    """兼容别名，见 :func:`ios_uses_appium_backend`。"""
    return ios_uses_appium_backend(mode, host=host)


def ios_session_uses_wda(os_type: str = "", mode: str = "", host: str = "") -> bool:
    """True 表示 iOS 会话走 WDA-direct，无需启动 Appium server。"""
    if not is_ios(os_type):
        return False
    return select_backend(os_type, host=host or host_os(), mode=mode) == "wda"
