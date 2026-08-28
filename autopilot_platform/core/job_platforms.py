"""运行目标平台：Job / IDE / Runner 共用判定。

web / http 都不绑定移动 UDID，按 Runner 能力路由。
"""

from __future__ import annotations

from typing import Any

PLATFORM_ANDROID = "android"
PLATFORM_IOS = "ios"
PLATFORM_WEB = "web"
PLATFORM_HTTP = "http"

JOB_PLATFORMS = frozenset(
    {PLATFORM_ANDROID, PLATFORM_IOS, PLATFORM_WEB, PLATFORM_HTTP}
)
DEVICELESS_PLATFORMS = frozenset({PLATFORM_WEB, PLATFORM_HTTP})
CAPABILITY_HTTP = "http"

#: 与管理台 runTargetOptions.ts 的 WEB_BROWSER_VALUES / MOBILE_BACKEND_FORCED 对齐
WEB_BROWSER_MODES = frozenset({"chrome", "edge", "firefox", "headless"})
MOBILE_BACKEND_MODES = frozenset({"uia2", "wda", "appium"})
HTTP_BUILTIN_PROFILES = ("auto", "dev", "staging", "prod")
#: HTTP profile / 浏览器 / 移动后端共用；旧库 String(32) 会截断长 profile
BACKEND_MODE_MAX_LEN = 64


def normalize_job_platform(raw: str) -> str:
    return (raw or "").strip().lower()


def is_job_platform(raw: str) -> bool:
    return normalize_job_platform(raw) in JOB_PLATFORMS


def is_deviceless_platform(raw: str) -> bool:
    return normalize_job_platform(raw) in DEVICELESS_PLATFORMS


def is_http_platform(raw: str) -> bool:
    return normalize_job_platform(raw) == PLATFORM_HTTP


def is_web_platform(raw: str) -> bool:
    return normalize_job_platform(raw) == PLATFORM_WEB


def normalize_stored_backend_mode(raw: str | None) -> str:
    """写入 Job / 计划前的规范化：去空白，空则 auto，超长拒绝。"""
    name = str(raw or "").strip()
    if not name:
        return "auto"
    if len(name) > BACKEND_MODE_MAX_LEN:
        raise ValueError(
            f"backend_mode 最长 {BACKEND_MODE_MAX_LEN} 字符，收到 {len(name)}"
        )
    return name


def coerce_backend_mode(
    platform: str,
    current: str,
    *,
    extra_http_profiles: list[str] | tuple[str, ...] | None = None,
) -> str:
    """切平台时清掉对端残留的 backend_mode。

    对齐管理台 ``applyPlatformSideEffects``：
    - HTTP：uia2/wda/appium/chrome/… → auto；yaml profile 名保留；
    - Web：移动后端 → auto；浏览器类型保留；
    - 移动：浏览器类型或其它非后端值 → auto。
    """
    plat = normalize_job_platform(platform)
    cur = str(current or "").strip()
    mode = cur.lower()
    if not mode:
        return "auto"
    if is_http_platform(plat):
        if mode in MOBILE_BACKEND_MODES or mode in WEB_BROWSER_MODES:
            return "auto"
        if extra_http_profiles is not None:
            allowed = {"auto", *(str(x).strip() for x in extra_http_profiles if str(x).strip())}
            allowed.update(HTTP_BUILTIN_PROFILES)
            if cur not in allowed and mode not in {x.lower() for x in allowed}:
                return "auto"
        return cur
    if is_web_platform(plat):
        if mode in MOBILE_BACKEND_MODES:
            return "auto"
        if mode in WEB_BROWSER_MODES or mode == "auto":
            return mode
        return "auto"
    if mode in MOBILE_BACKEND_MODES or mode == "auto":
        return mode
    return "auto"


def apply_platform_side_effects(form: dict[str, Any], platform: str) -> dict[str, Any]:
    """字典表单版切平台副作用，对齐 FE ``applyPlatformSideEffects``。"""
    plat = normalize_job_platform(platform)
    if is_deviceless_platform(plat):
        form["device_udids"] = ""
        if "app_build_id" in form:
            form["app_build_id"] = ""
        form["parallel"] = False
        form["parallel_workers"] = 0
        form["wda_bundle"] = ""
        if is_web_platform(plat):
            form["web_engine"] = form.get("web_engine") or "selenium"
        else:
            form["web_engine"] = "selenium"
    form["backend_mode"] = coerce_backend_mode(
        plat, str(form.get("backend_mode") or "auto")
    )
    return form


def apply_deviceless_run_target(obj: Any) -> None:
    """web / http：就地剥移动字段（UDID / 并行 / WDA / 应用包）。

    HTTP 额外把 web_engine 打回 selenium。Web 保留 playwright。
    backend_mode：清掉对端残留（uia2/chrome），保留 HTTP profile / Web 浏览器类型。
    """
    plat = normalize_job_platform(str(getattr(obj, "platform", "") or ""))
    if not is_deviceless_platform(plat):
        return
    if hasattr(obj, "device_udids"):
        obj.device_udids = []
    if hasattr(obj, "parallel"):
        obj.parallel = False
    if hasattr(obj, "parallel_workers"):
        obj.parallel_workers = 0
    if hasattr(obj, "wda_bundle"):
        obj.wda_bundle = ""
    if hasattr(obj, "app_build_id"):
        obj.app_build_id = None
    if hasattr(obj, "web_engine") and not is_web_platform(plat):
        obj.web_engine = "selenium"
    if hasattr(obj, "backend_mode"):
        obj.backend_mode = coerce_backend_mode(
            plat, str(getattr(obj, "backend_mode", "") or "")
        )


__all__ = [
    "PLATFORM_ANDROID",
    "PLATFORM_IOS",
    "PLATFORM_WEB",
    "PLATFORM_HTTP",
    "JOB_PLATFORMS",
    "DEVICELESS_PLATFORMS",
    "CAPABILITY_HTTP",
    "WEB_BROWSER_MODES",
    "MOBILE_BACKEND_MODES",
    "HTTP_BUILTIN_PROFILES",
    "BACKEND_MODE_MAX_LEN",
    "normalize_stored_backend_mode",
    "normalize_job_platform",
    "is_job_platform",
    "is_deviceless_platform",
    "is_http_platform",
    "is_web_platform",
    "coerce_backend_mode",
    "apply_platform_side_effects",
    "apply_deviceless_run_target",
]
