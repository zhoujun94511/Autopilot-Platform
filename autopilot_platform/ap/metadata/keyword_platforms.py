"""关键字目标平台元数据（Phase 1：XML platforms + 类目回退，驱动库灰显与用例 lint）。

规则：
  - 关键字 XML 显式 platforms 优先
  - WebUI 类目 → 仅 web
  - Mobile 类目 → android + ios（无 platforms 时）
  - Http / Public → 平台无关（空集表示任意平台可用）
"""

from __future__ import annotations

from .keyword_meta import KeywordMeta

# 已写入 mobile.xml platforms="android" 的关键字 id（供测试/文档引用，非运行时回退）
ANDROID_ONLY_KEYWORD_IDS: frozenset[str] = frozenset({
    "mobile_toast_verify",
    "mobile_element_adb_input_text",
    "mobile_element_text_input_adb",
    "installAdbkeyboard",
    "installUtf7Ime",
    "performance_data_capture",
    "intentToMiniProgram",
    "mobile_app_reset_saveinfo",
    "mobile_get_current_activity",
    "mobile_start_activity",
    "mobile_activity_switch",
    "mobile_app_open_and_jump",
    "mobile_pull_file_to_mobile",
    "Shelter",
    "backToTab",
    "mobile_SDK_ergodic",
    "mobile_set_network",
    "mobile_browser_open",
    "mobile_browser_close",
    "mobile_browser_locate",
})

# 已写入 mobile.xml platforms="ios" 的关键字 id
IOS_ONLY_KEYWORD_IDS: frozenset[str] = frozenset({
    "ios_alert_handle",
    "ios_alert_exists",
    "ios_alert_set_policy",
    "ios_alert_set_enabled",
})

_PLATFORM_LABEL = {
    "android": "Android",
    "ios": "iOS",
    "web": "Web",
    "http": "HTTP / API",
}


def target_platforms(meta: KeywordMeta) -> frozenset[str]:
    """关键字适用平台；空集表示任意平台。"""
    if meta.platforms:
        return frozenset(meta.platforms)
    if meta.category == "WebUI":
        return frozenset({"web"})
    if meta.category == "Mobile":
        return frozenset({"android", "ios"})
    return frozenset()


def _format_platforms(platforms: frozenset[str]) -> str:
    return " / ".join(_PLATFORM_LABEL.get(p, p) for p in sorted(platforms))


def platform_mismatch_reason(target: str, meta: KeywordMeta) -> str:
    """当前目标平台与关键字不适用时返回悬停/提示文案，否则空串。"""
    if meta.unsupported:
        return meta.unsupported_reason or "平台专有，不支持"
    plat = (target or "").strip().lower()
    if plat not in ("android", "ios", "web", "http"):
        return ""
    allowed = target_platforms(meta)
    if not allowed or plat in allowed:
        return ""
    if plat == "ios" and allowed == frozenset({"android"}):
        return "Android 专有（当前为 iOS 工程/用例）"
    if plat == "android" and allowed == frozenset({"ios"}):
        return "iOS 专有（当前为 Android 工程/用例）"
    if plat == "android" and allowed == frozenset({"web"}):
        return "Web 专有（当前为 Android 工程/用例）"
    if plat == "web" and "web" not in allowed:
        return f"不适用于 Web（仅 {_format_platforms(allowed)}）"
    if plat == "http" and "http" not in allowed:
        return f"不适用于 HTTP / API（仅 {_format_platforms(allowed)}）"
    return f"不适用于 {_PLATFORM_LABEL.get(plat, plat)}（仅 {_format_platforms(allowed)}）"


def apply_platform_metadata(catalog) -> None:
    """加载目录后为每条 meta 写入 target_platforms（便于 UI 直接读）。"""
    for meta in catalog.by_id.values():
        meta.target_platforms = target_platforms(meta)
