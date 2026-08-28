"""从 ExecutionContext 采集可交互控件（Web / Android / iOS 分平台属性）。

Android / iOS 属性白名单对齐 Appium Inspector 重要字段、DroidBot dump、
本仓 inspector.tree / ios monkey；不做 page_source 全量上传。
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

# Web：可交互可见 + 属性白名单（Midscene selenium 思路）
_WEB_EXTRACT_JS = r"""
return (function() {
  const SEL = 'a,button,input:not([type=hidden]),select,textarea,[tabindex],[onclick],' +
    '[role=button],[role=link],[role=textbox],[role=checkbox],[role=menuitem],[role=tab]';
  const ATTRS = ['id','class','type','name','href','value','placeholder','role','tabindex',
    'aria-label','title','data-testid','data-test','data-qa'];
  function visible(el) {
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) return false;
    const st = window.getComputedStyle(el);
    if (st.visibility === 'hidden' || st.display === 'none' || Number(st.opacity) === 0) return false;
    if (el.disabled) return false;
    return true;
  }
  function xpath(el) {
    if (el.id) return '//*[@id="' + el.id + '"]';
    const parts = [];
    while (el && el.nodeType === 1 && parts.length < 6) {
      let ix = 1;
      let sib = el.previousElementSibling;
      while (sib) { if (sib.tagName === el.tagName) ix++; sib = sib.previousElementSibling; }
      parts.unshift(el.tagName.toLowerCase() + '[' + ix + ']');
      el = el.parentElement;
    }
    return '//' + parts.join('/');
  }
  const out = [];
  const seen = new Set();
  document.querySelectorAll(SEL).forEach(function(el) {
    if (!visible(el)) return;
    const r = el.getBoundingClientRect();
    const key = el.tagName + '|' + Math.round(r.x) + '|' + Math.round(r.y) + '|' + (el.id||'');
    if (seen.has(key)) return;
    seen.add(key);
    const text = (el.innerText || el.value || el.getAttribute('aria-label') || '').trim().slice(0, 80);
    const css = el.id ? ('#' + CSS.escape(el.id)) : '';
    const tag = el.tagName.toLowerCase();
    const role = el.getAttribute('role') || '';
    const editable = tag === 'input' || tag === 'textarea' || tag === 'select'
      || role === 'textbox' || role === 'searchbox' || !!el.isContentEditable;
    out.push({
      platform: 'web',
      tag: tag,
      text: text,
      placeholder: el.getAttribute('placeholder') || '',
      role: role,
      class: String(el.className || '').slice(0, 160),
      id: el.id || '',
      clickable: true,
      editable: editable,
      enabled: !el.disabled,
      bounds: [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)],
      locators: {
        id: el.id || '',
        css: css,
        xpath: xpath(el),
        testid: el.getAttribute('data-testid') || el.getAttribute('data-test') || ''
      }
    });
  });
  return out.slice(0, 300);
})()
"""

# Android：Appium uiautomator dump / Inspector 重要属性
_ANDROID_ATTR_KEYS = (
    "resource-id",
    "content-desc",
    "text",
    "class",
    "package",
    "bounds",
    "clickable",
    "enabled",
    "checkable",
    "checked",
    "scrollable",
    "long-clickable",
    "focusable",
    "focused",
    "selected",
    "password",
    "index",
)

# iOS：WDA page_source / monkey / Inspector 重要属性
_IOS_ATTR_KEYS = (
    "name",
    "label",
    "value",
    "type",
    "enabled",
    "visible",
    "x",
    "y",
    "width",
    "height",
    "index",
)

_ANDROID_INTERACTIVE_HINTS = (
    "button",
    "edittext",
    "imagebutton",
    "checkbox",
    "radiobutton",
    "spinner",
    "switch",
    "togglebutton",
    "checkedtextview",
    "seekbar",
    "chip",
)

#: 值得保留进摘要的 iOS 类型（含常作可点标签的 StaticText / Image）
_IOS_INTERACTIVE_TYPES = {
    "xcuielementtypebutton",
    "xcuielementtypetextfield",
    "xcuielementtypesecuretextfield",
    "xcuielementtypetextview",
    "xcuielementtypesearchfield",
    "xcuielementtypelink",
    "xcuielementtypeswitch",
    "xcuielementtypecell",
    "xcuielementtypecollectionview",
    "xcuielementtypestatictext",  # 常作可点标签
    "xcuielementtypeimage",
}

#: 真正的可交互控件类型。StaticText / Image 也常能点，但把它们一律标成 clickable
#: 会让摘要里所有控件都是 ``ck:1``，等于没有信息量，模型只能靠名字猜。
_IOS_CLICKABLE_TYPES = {
    "xcuielementtypebutton",
    "xcuielementtypetextfield",
    "xcuielementtypesecuretextfield",
    "xcuielementtypetextview",
    "xcuielementtypesearchfield",
    "xcuielementtypelink",
    "xcuielementtypeswitch",
    "xcuielementtypecell",
}

#: 可输入文本的类型：模型要区分「点开搜索入口」和「直接输入」
_IOS_EDITABLE_TYPES = {
    "xcuielementtypetextfield",
    "xcuielementtypesecuretextfield",
    "xcuielementtypetextview",
    "xcuielementtypesearchfield",
}


def _truthy_attr(attrs: dict[str, Any], *keys: str) -> bool:
    for k in keys:
        v = attrs.get(k)
        if str(v or "").strip().lower() in ("true", "1", "yes"):
            return True
    return False


def _short_class(class_name: str) -> str:
    s = (class_name or "").strip()
    if not s:
        return ""
    return s.split(".")[-1][:48]


def driver_from_ctx(ctx: Any) -> Any | None:
    """从 ctx 取底层 driver（移动/Web/裸 driver 三种挂法）。"""
    if ctx is None:
        return None
    for path in (
        lambda: getattr(getattr(ctx, "appium", None), "driver", None),
        lambda: getattr(getattr(ctx, "web", None), "driver", None),
        lambda: getattr(ctx, "driver", None),
    ):
        try:
            obj = path()
            drv = obj() if callable(obj) else obj
            if drv is not None:
                return drv
        except (AttributeError, TypeError, RuntimeError, OSError):
            continue
    return None


#: 历史内部名，保留以免旧调用点断裂
_driver_from_ctx = driver_from_ctx


def _collect_web(drv: Any) -> list[dict[str, Any]]:
    # noinspection PyBroadException
    try:
        rows = drv.execute_script(_WEB_EXTRACT_JS)
    except Exception as exc:  # noqa: BLE001
        log.debug("ui_context web extract failed: %s", exc)
        return []
    if not isinstance(rows, list):
        return []
    return [r for r in rows if isinstance(r, dict)]


def _android_node_to_el(node: Any) -> dict[str, Any] | None:
    attrs = getattr(node, "attrs", None) or {}
    if not isinstance(attrs, dict):
        attrs = {}
    tag = str(getattr(node, "tag", "") or attrs.get("class") or "")
    class_name = str(attrs.get("class") or tag)
    short = _short_class(class_name)
    text = str(attrs.get("text") or "").strip()
    desc = str(attrs.get("content-desc") or "").strip()
    rid = str(attrs.get("resource-id") or "").strip()
    clickable = _truthy_attr(attrs, "clickable")
    enabled = _truthy_attr(attrs, "enabled") if "enabled" in attrs else True
    checkable = _truthy_attr(attrs, "checkable")
    focusable = _truthy_attr(attrs, "focusable")
    scrollable = _truthy_attr(attrs, "scrollable")
    long_clickable = _truthy_attr(attrs, "long-clickable")
    interactive = clickable or checkable or long_clickable or any(
        h in short.lower() for h in _ANDROID_INTERACTIVE_HINTS
    )
    # 纯布局容器且无文案/无 id：丢弃
    if not interactive and not text and not desc and not rid:
        low = class_name.lower()
        if "layout" in low or low.endswith("viewgroup") or "viewpager" in low:
            return None
    if not enabled and not text and not desc and not rid:
        return None

    bounds = getattr(node, "bounds", None)
    rect = list(bounds) if isinstance(bounds, tuple) and len(bounds) == 4 else None
    if rect and (rect[2] <= 0 or rect[3] <= 0):
        return None

    kept = {
        k: str(attrs.get(k))[:120]
        for k in _ANDROID_ATTR_KEYS
        if attrs.get(k) not in (None, "")
    }
    # password：只留布尔，不传真实输入值
    if "password" in kept and str(kept.get("password")).lower() in ("true", "1"):
        kept["password"] = "true"
        kept.pop("text", None)

    locators: dict[str, str] = {}
    if rid:
        locators["id"] = rid
        # Appium 常用 resource-id 末段
        if "/" in rid:
            locators["id_short"] = rid.rsplit("/", 1)[-1]
    if desc:
        locators["accessibility_id"] = desc
    if text:
        locators["xpath"] = f'//*[@text="{text[:60]}"]'
    elif desc:
        locators["xpath"] = f'//*[@content-desc="{desc[:60]}"]'
    elif rid:
        locators["xpath"] = f'//*[@resource-id="{rid[:80]}"]'

    low_short = short.lower()
    editable = any(h in low_short for h in ("edittext", "autocompletetextview", "searchview"))
    # clickable：优先系统属性；无属性时才用类型推断，避免整页 ck:1 失去区分度
    return {
        "platform": "android",
        "tag": short or class_name,
        "class": class_name,
        "text": text,
        "content_desc": desc,
        "resource_id": rid,
        "package": str(attrs.get("package") or ""),
        "clickable": clickable if "clickable" in attrs else interactive,
        "editable": editable,
        "enabled": enabled,
        "checkable": checkable,
        "checked": _truthy_attr(attrs, "checked"),
        "scrollable": scrollable,
        "focusable": focusable,
        "bounds": rect,
        "attrs": kept,
        "locators": locators,
    }


def _ios_node_to_el(node: Any) -> dict[str, Any] | None:
    attrs = getattr(node, "attrs", None) or {}
    if not isinstance(attrs, dict):
        attrs = {}
    etype = str(attrs.get("type") or getattr(node, "tag", "") or "")
    name = str(attrs.get("name") or "").strip()
    label = str(attrs.get("label") or "").strip()
    value = str(attrs.get("value") or "").strip()
    enabled = _truthy_attr(attrs, "enabled") if "enabled" in attrs else True
    visible = _truthy_attr(attrs, "visible") if "visible" in attrs else True
    if not visible:
        return None
    if not enabled and not (name or label or value):
        return None

    low_type = etype.lower()
    interactive = low_type in _IOS_INTERACTIVE_TYPES or bool(name or label)
    # 过滤无语义的 Other 空壳
    if low_type == "xcuielementtypeother" and not (name or label or value):
        return None
    if not interactive and low_type not in _IOS_INTERACTIVE_TYPES:
        # 仍保留带 name/label 的节点（常可点）
        if not (name or label):
            return None

    bounds = getattr(node, "bounds", None)
    rect = list(bounds) if isinstance(bounds, tuple) and len(bounds) == 4 else None
    if rect is None and {"x", "y", "width", "height"} <= set(attrs):
        try:
            rect = [
                int(float(attrs["x"])),
                int(float(attrs["y"])),
                int(float(attrs["width"])),
                int(float(attrs["height"])),
            ]
        except (TypeError, ValueError):
            rect = None
    if rect and (rect[2] <= 1 or rect[3] <= 1):
        return None

    kept = {
        k: str(attrs.get(k))[:120]
        for k in _IOS_ATTR_KEYS
        if attrs.get(k) not in (None, "")
    }
    locators: dict[str, str] = {}
    if name:
        locators["accessibility_id"] = name
        locators["id"] = name
    if label and label != name:
        locators["label"] = label
    if name:
        locators["xpath"] = f'//*[@name="{name[:60]}"]'
    elif label:
        locators["xpath"] = f'//*[@label="{label[:60]}"]'

    return {
        "platform": "ios",
        "tag": etype.replace("XCUIElementType", "") or etype,
        "type": etype,
        "text": label or name or value,
        "name": name,
        "label": label,
        "value": value[:80] if value else "",
        "clickable": low_type in _IOS_CLICKABLE_TYPES,
        "editable": low_type in _IOS_EDITABLE_TYPES,
        "enabled": enabled,
        "visible": visible,
        "bounds": rect,
        "attrs": kept,
        "locators": locators,
    }


def _node_to_el(node: Any, *, platform: str) -> dict[str, Any] | None:
    if platform == "android":
        return _android_node_to_el(node)
    if platform == "ios":
        return _ios_node_to_el(node)
    return None


def _load_mobile_tree_parsers():
    """加载 page_source 解析器：兼容 IDE 包名与 Platform ap 切片。"""
    import importlib

    # 先本仓可达路径，再另一仓可选名（均为 try/except，非硬依赖）
    candidates = (
        "autopilot.inspector.tree",
        "autopilot_platform.ap.inspector.tree",
    )
    # 若当前包已是 Platform ap，优先本切片，避免开发机同时 editable 安装 IDE 时误绑
    pkg = __package__ or ""
    if pkg.startswith("autopilot_platform"):
        candidates = (
            "autopilot_platform.ap.inspector.tree",
            "autopilot.inspector.tree",
        )
    errors: list[str] = []
    for name in candidates:
        try:
            mod = importlib.import_module(name)
            return mod.parse_android, mod.parse_ios
        except (ImportError, ModuleNotFoundError, AttributeError) as exc:
            errors.append(f"{name}: {exc}")
    try:
        from ..inspector.tree import parse_android, parse_ios

        return parse_android, parse_ios
    except (ImportError, ModuleNotFoundError, AttributeError) as exc:
        errors.append(f"relative: {exc}")
    log.debug("ui_context inspector.tree unavailable: %s", "; ".join(errors))
    return None, None


def _collect_mobile(drv: Any, platform: str) -> list[dict[str, Any]]:
    # noinspection PyBroadException
    try:
        src = drv.page_source
    except Exception as exc:  # noqa: BLE001
        log.debug("ui_context page_source failed: %s", exc)
        return []
    if not src:
        return []
    parse_android, parse_ios = _load_mobile_tree_parsers()
    if parse_android is None or parse_ios is None:
        return []
    # noinspection PyBroadException
    try:
        root = parse_android(src) if platform == "android" else parse_ios(src)
    except Exception as exc:  # noqa: BLE001
        log.debug("ui_context parse failed: %s", exc)
        return []
    out: list[dict[str, Any]] = []
    for node in root.iter_all():
        el = _node_to_el(node, platform=platform)
        if el:
            out.append(el)
        if len(out) >= 400:
            break
    return out


def collect_ui_elements(ctx: Any, *, platform: str) -> list[dict[str, Any]]:
    """采集可交互控件；失败返回空列表（不阻断 Vision）。"""
    drv = _driver_from_ctx(ctx)
    if drv is None:
        return []
    plat = (platform or "web").strip().lower()
    if plat == "web":
        return _collect_web(drv)
    if plat in ("android", "ios"):
        return _collect_mobile(drv, plat)
    return []
