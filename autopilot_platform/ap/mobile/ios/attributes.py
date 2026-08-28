"""iOS / Android 原生控件属性读取（WDA-direct / Appium iOS 与 UiAutomator 别名对齐）。"""

from __future__ import annotations

from typing import Any

# 关键字 attribution 参数 → iOS 候选 WDA/XCUI 属性名（按优先级）
_IOS_ATTR_CANDIDATES: dict[str, tuple[str, ...]] = {
    "text": ("label", "name", "value"),
    "content-desc": ("label", "name", "value"),
    "resource-id": ("name", "identifier"),
    "class": ("type", "className"),
    "long-clickable": ("enabled",),
    "clickable": ("enabled",),
    "enabled": ("enabled",),
    "visible": ("visible",),
    "checked": ("value",),
    "selected": ("selected",),
}

# Android UiAutomator 专有别名 → 仍走 Android 分支
_ANDROID_ATTR_MAP: dict[str, str] = {
    "content-desc": "contentDescription",
    "resource-id": "resourceId",
    "long-clickable": "longClickable",
}


def _native_context(driver: Any) -> bool:
    # noinspection PyBroadException
    try:
        ctx_name = driver.context if hasattr(driver, "context") else "NATIVE_APP"
    except Exception:
        ctx_name = "NATIVE_APP"
    return str(ctx_name).startswith("NATIVE")


def ios_attr_candidates(attr: str) -> tuple[str, ...]:
    """将关键字 attribution 映射为 iOS 侧候选属性名。"""
    key = (attr or "").strip()
    if key in _IOS_ATTR_CANDIDATES:
        return _IOS_ATTR_CANDIDATES[key]
    if key:
        return (key,)
    return ()


def read_element_attribute(
    el: Any,
    attr: str,
    *,
    platform: str = "",
    driver: Any | None = None,
) -> str:
    """读取控件属性；platform=ios 时做 XCUI 别名映射，否则保持 Android 语义。"""
    key = (attr or "").strip()
    plat = (platform or "").strip().lower()

    if key == "height":
        return str(el.size["height"])
    if key == "width":
        return str(el.size["width"])
    if key == "locationX":
        return str(el.location["x"])
    if key == "locationY":
        return str(el.location["y"])

    if plat == "ios":
        if key == "text":
            txt = getattr(el, "text", None)
            if txt:
                return str(txt)
        if key == "class" and driver is not None and _native_context(driver):
            for name in ios_attr_candidates("class"):
                val = el.get_attribute(name)
                if val:
                    return str(val)
            return str(el.get_attribute("type") or el.get_attribute("className") or "")
        for name in ios_attr_candidates(key):
            val = el.get_attribute(name)
            if val is not None and str(val).strip() != "":
                return str(val)
        if key:
            val = el.get_attribute(key)
            return "" if val is None else str(val)
        return ""

    # Android / 默认
    if key == "text":
        return str(el.text or "")
    if key == "class" and driver is not None and _native_context(driver):
        return str(el.get_attribute("className") or "")
    mapped = _ANDROID_ATTR_MAP.get(key, key)
    val = el.get_attribute(mapped)
    return "" if val is None else str(val)


def resolve_verify_attribute_name(attr: str, *, _platform: str = "") -> str:
    """校验关键字 attribute 参数：iOS 仍用原始名，由 read_element_attribute 做映射。"""
    return (attr or "").strip()
