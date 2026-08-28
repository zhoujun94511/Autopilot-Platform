"""Vision / Intent 上下文预算：压缩截图与精简控件描述，降低多模态 token。

策略借鉴 Midscene（shrink×2 / JPEG / 图不进 DOM JSON）：
- 截图只走独立 ``image_url``，禁止把 base64 塞进文本 JSON（否则按字符计 token）
- 只裁「意图命中」的控件外包；小目标加少量 padding，绝不扩到整屏占比
- 裁后长边压到约 384（enhanced 512）；4K 未裁也先缩，避免把原图像素送给模型
- 控件用 compact signature；默认不传全量属性
"""

from __future__ import annotations

import logging
import re
from typing import Any

from .synonyms import expand_intent_tokens

log = logging.getLogger(__name__)

# Compact signature 字段（对齐 Midscene 缩写）
MAX_TEXT_LEN = 16
MAX_CLASS_COUNT = 3
FULL_TEXT_LEN = 80

_CLASS_KEYWORDS = (
    "btn", "icon", "title", "input", "nav", "tab", "menu", "button", "link",
    "form", "card", "header", "footer", "sidebar", "content", "modal",
    "dropdown", "search", "filter", "list", "item", "login", "submit",
)

_INTERACTIVE_TAGS = {
    "a", "button", "input", "select", "textarea", "option",
    "android.widget.button", "android.widget.edittext", "android.widget.imagebutton",
    "android.widget.checkbox", "android.widget.radiobutton", "android.widget.spinner",
    "android.widget.switch", "android.widget.togglebutton",
    "xcuielementtypebutton", "xcuielementtypetextfield", "xcuielementtypesecuretextfield",
    "xcuielementtypelink", "xcuielementtypeswitch", "xcuielementtypecell",
}


# DeepSeek 官方硬上限是 8192，那是拒收线，不是发送目标。
# Midscene mobile 建议 shrink×2；定位任务裁后长边 384 足够（约 1 个 vision tile）。
DEEPSEEK_VISION_MAX_SIDE = 8192
CROP_PAD_PX = 16
CROP_PAD_RATIO = 0.08
CROP_SKIP_COVER = 0.70
CROP_FOCUS_MAX = 3
CROP_TARGET_LONG_SIDE = 384
CROP_ENHANCED_LONG_SIDE = 512
CROP_MAX_KB = 96
UNCROPPED_MAX_SIDE = 512
DEEPSEEK_VISION_LOW_SIDE = CROP_TARGET_LONG_SIDE
DEEPSEEK_VISION_TARGET_LONG_SIDE = CROP_TARGET_LONG_SIDE


def parse_element_bounds(el: dict[str, Any]) -> tuple[int, int, int, int] | None:
    """归一化 ``bounds`` / ``rect`` / compact ``p`` 为 ``(x, y, w, h)``。"""
    if not isinstance(el, dict):
        return None
    bounds = el.get("bounds") or el.get("rect")
    if isinstance(bounds, (list, tuple)) and len(bounds) >= 4:
        try:
            x, y, w, h = (int(bounds[0]), int(bounds[1]), int(bounds[2]), int(bounds[3]))
        except (TypeError, ValueError):
            return None
        if w > 0 and h > 0:
            return x, y, w, h
    if isinstance(bounds, dict):
        try:
            x = int(bounds.get("x", 0))
            y = int(bounds.get("y", 0))
            w = int(bounds.get("w", bounds.get("width", 0)))
            h = int(bounds.get("h", bounds.get("height", 0)))
        except (TypeError, ValueError):
            return None
        if w > 0 and h > 0:
            return x, y, w, h
    pos = el.get("p")
    if isinstance(pos, str) and pos.count(",") >= 3:
        parts = pos.split(",")
        try:
            x, y, w, h = (int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3]))
        except (TypeError, ValueError):
            return None
        if w > 0 and h > 0:
            return x, y, w, h
    return None


def text_has_embedded_image(text: str) -> bool:
    """文本 / DOM JSON 里是否误塞了 data URL 或超长 base64。"""
    raw = text or ""
    low = raw[:8000].lower()
    if "data:image/" in low or ";base64," in low:
        return True
    # 裸 PNG / JPEG 头出现在文本里也视为误嵌
    if "ivborw0k" in low or "/9j/" in low:
        return True
    return False


def strip_embedded_images_from_text(text: str) -> str:
    """从文本通道去掉误嵌的图片，避免按字符烧掉 token。"""
    if not text or not text_has_embedded_image(text):
        return text
    cleaned = re.sub(
        r"data:image/[a-zA-Z0-9.+-]+;base64,[A-Za-z0-9+/=\s]+",
        "[image omitted]",
        text,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r";base64,[A-Za-z0-9+/=\s]{80,}", ";base64,[omitted]", cleaned)
    return cleaned


def _nearest_cluster(
    elements: list[dict[str, Any]],
    *,
    max_count: int,
) -> list[dict[str, Any]]:
    """围绕分数最高的命中，只留空间上最近的几个，避免并集铺满整屏。"""
    scored: list[tuple[float, dict[str, Any], tuple[int, int, int, int]]] = []
    for el in elements:
        box = parse_element_bounds(el)
        if not box:
            continue
        score = 1.0
        if _is_interactive(el):
            score += 5.0
        area = max(1, box[2] * box[3])
        score += min(3.0, area / 20000.0)
        scored.append((score, el, box))
    if not scored:
        return []
    cap = max(1, int(max_count))
    scored.sort(key=lambda row: row[0], reverse=True)
    _anchor_score, anchor_el, anchor_box = scored[0]
    if len(scored) == 1 or cap == 1:
        return [anchor_el]
    ax = anchor_box[0] + anchor_box[2] // 2
    ay = anchor_box[1] + anchor_box[3] // 2
    rest: list[tuple[int, dict[str, Any]]] = []
    for _score, el, box in scored[1:]:
        cx = box[0] + box[2] // 2
        cy = box[1] + box[3] // 2
        dist = (cx - ax) * (cx - ax) + (cy - ay) * (cy - ay)
        rest.append((dist, el))
    rest.sort(key=lambda row: row[0])
    return [anchor_el] + [el for _dist, el in rest[: cap - 1]]


def crop_focus_elements(
    elements: list[dict[str, Any]],
    *,
    prompt: str = "",
    max_count: int = CROP_FOCUS_MAX,
) -> list[dict[str, Any]]:
    """只返回意图命中的控件。没有命中则空列表（不裁，走整图缩小）。

    旧逻辑把过滤后的整页控件并集当 ROI，等于几乎不裁，浪费 token。
    """
    usable = [
        el
        for el in (elements or [])
        if isinstance(el, dict) and parse_element_bounds(el)
    ]
    if not usable:
        return []
    tokens = _tokenize_prompt(prompt)
    if not tokens:
        return []
    hits = [el for el in usable if any(tok in _el_blob(el) for tok in tokens)]
    if not hits:
        return []
    return _nearest_cluster(hits, max_count=max_count)


def union_element_bounds(
    elements: list[dict[str, Any]],
    image_w: int,
    image_h: int,
    *,
    pad_ratio: float = CROP_PAD_RATIO,
    pad_px: int = CROP_PAD_PX,
    skip_cover: float = CROP_SKIP_COVER,
) -> tuple[int, int, int, int] | None:
    """意图控件外包 + 少量 padding。小目标保持小；铺满整屏则不裁。"""
    iw, ih = max(1, int(image_w)), max(1, int(image_h))
    boxes: list[tuple[int, int, int, int]] = []
    for el in elements or []:
        parsed = parse_element_bounds(el) if isinstance(el, dict) else None
        if parsed:
            boxes.append(parsed)
    if not boxes:
        return None
    x0 = min(b[0] for b in boxes)
    y0 = min(b[1] for b in boxes)
    x1 = max(b[0] + b[2] for b in boxes)
    y1 = max(b[1] + b[3] for b in boxes)
    roi_w = max(0, x1 - x0)
    roi_h = max(0, y1 - y0)
    pad_x = max(int(pad_px), int(roi_w * pad_ratio))
    pad_y = max(int(pad_px), int(roi_h * pad_ratio))
    x0 = max(0, x0 - pad_x)
    y0 = max(0, y0 - pad_y)
    x1 = min(iw, x1 + pad_x)
    y1 = min(ih, y1 + pad_y)
    w, h = x1 - x0, y1 - y0
    if w <= 0 or h <= 0:
        return None
    cover = (w * h) / float(iw * ih)
    if cover >= skip_cover:
        return None
    return int(x0), int(y0), int(w), int(h)


def shift_element_bounds(
    elements: list[dict[str, Any]],
    box: tuple[int, int, int, int],
) -> list[dict[str, Any]]:
    """把控件坐标平移到预裁剪后的图坐标系，避免 DOM ``p`` 与截图错位。"""
    ox, oy = int(box[0]), int(box[1])
    out: list[dict[str, Any]] = []
    for el in elements or []:
        if not isinstance(el, dict):
            continue
        copied = dict(el)
        parsed = parse_element_bounds(copied)
        if parsed:
            x, y, w, h = parsed
            shifted = [x - ox, y - oy, w, h]
            copied["bounds"] = shifted
            if "rect" in copied:
                copied["rect"] = shifted
        out.append(copied)
    return out


def precrop_screenshot(
    image_bytes: bytes,
    elements: list[dict[str, Any]] | None = None,
    *,
    pad_ratio: float = CROP_PAD_RATIO,
    max_side: int = CROP_TARGET_LONG_SIDE,
) -> tuple[bytes, str, dict[str, Any]]:
    """按意图控件紧裁，再把长边压到 ``max_side``（默认 384，不是 8192）。

    没有焦点控件时不裁，只把整图缩到 ``UNCROPPED_MAX_SIDE``，对齐 Midscene shrink。

    Returns:
        ``(bytes, mime, meta)``。
    """
    meta: dict[str, Any] = {"cropped": False, "box": None, "reason": "skip"}
    if not image_bytes:
        return b"", "image/png", {**meta, "reason": "empty"}
    try:
        # noinspection PyPackageRequirements,PyUnresolvedReferences
        import cv2  # type: ignore[import-untyped]
        # noinspection PyPackageRequirements,PyUnresolvedReferences
        import numpy as np  # type: ignore[import-untyped]
    except ImportError:
        return image_bytes, "image/png", {**meta, "reason": "opencv_unavailable"}

    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        return image_bytes, "image/png", {**meta, "reason": "decode_failed"}

    src_h, src_w = img.shape[:2]
    crop_box = union_element_bounds(elements or [], src_w, src_h, pad_ratio=pad_ratio)
    cropped = img
    if crop_box is not None:
        x, y, cw, ch = crop_box
        roi = img[y : y + ch, x : x + cw]
        if roi.size == 0:
            meta["reason"] = "empty_crop"
        else:
            cropped = roi
            meta = {
                "cropped": True,
                "box": [x, y, cw, ch],
                "reason": "element_union",
                "src_wh": [src_w, src_h],
            }
    elif not elements:
        meta["reason"] = "no_elements"
    else:
        meta["reason"] = "full_frame_or_no_bounds"

    ch, cw = cropped.shape[:2]
    cap = max(64, int(max_side))
    if not meta.get("cropped"):
        cap = max(cap, UNCROPPED_MAX_SIDE)
    if max(ch, cw) > cap:
        scale = float(cap) / float(max(ch, cw))
        cropped = cv2.resize(
            cropped,
            (max(1, int(cw * scale)), max(1, int(ch * scale))),
            interpolation=cv2.INTER_AREA,
        )
        meta["clamped_side"] = cap
        if not meta.get("cropped"):
            meta["reason"] = "max_side"

    ok, buf = cv2.imencode(".png", cropped)
    if not ok:
        return image_bytes, "image/png", {**meta, "reason": "encode_failed", "cropped": False}
    meta["dst_wh"] = [int(cropped.shape[1]), int(cropped.shape[0])]
    return bytes(buf), "image/png", meta


def compress_screenshot(
    image_bytes: bytes,
    *,
    target_short_side: int = 480,
    max_kb: int = 200,
    quality: int = 85,
    min_quality: int = 40,
    max_long_side: int | None = None,
) -> tuple[bytes, str]:
    """缩放到短边并压成 JPEG。无 OpenCV 时原样返回 PNG。

    ``max_long_side``：裁后/整图再压一次长边（默认约 384，不是厂商 8192 上限）。

    Returns:
        (bytes, mime) 例如 ``(jpeg_bytes, "image/jpeg")``
    """
    if not image_bytes:
        return b"", "image/png"
    # 已够小：仍尽量转 JPEG（视觉 token 按图计，体积越小越好），失败则原样
    try:
        # opencv-python-headless 提供 cv2；IDE 检查器常认不出包名映射
        # noinspection PyPackageRequirements,PyUnresolvedReferences
        import cv2  # type: ignore[import-untyped]
        # noinspection PyPackageRequirements,PyUnresolvedReferences
        import numpy as np  # type: ignore[import-untyped]
    except ImportError:
        log.debug("context_budget: opencv unavailable, keep raw screenshot")
        return image_bytes, "image/png"

    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        return image_bytes, "image/png"

    h, w = img.shape[:2]
    if max_long_side:
        long = max(h, w)
        cap = max(64, int(max_long_side))
        if long > cap:
            scale = float(cap) / float(long)
            w, h = max(1, int(w * scale)), max(1, int(h * scale))
            img = cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA)
    short = min(h, w)
    if short > max(64, int(target_short_side)):
        scale = float(target_short_side) / float(short)
        nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
        img = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA)

    limit = max(16, int(max_kb)) * 1024
    q = max(min_quality, min(95, int(quality)))
    enc = None
    while q >= min_quality:
        ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), q])
        if not ok:
            break
        enc = bytes(buf)
        if len(enc) <= limit:
            break
        q -= 10
    if not enc:
        return image_bytes, "image/png"
    log.debug(
        "context_budget: screenshot %sB → %sB jpeg q=%s",
        len(image_bytes),
        len(enc),
        q,
    )
    return enc, "image/jpeg"


def _filter_classes(raw: Any, *, max_count: int = MAX_CLASS_COUNT) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, str):
        parts = raw.split()
    elif isinstance(raw, (list, tuple)):
        parts = [str(x) for x in raw]
    else:
        parts = []
    kept: list[str] = []
    for cls in parts:
        low = cls.lower()
        if any(k in low for k in _CLASS_KEYWORDS):
            kept.append(cls)
        if len(kept) >= max_count:
            break
    return kept


def _best_locator(el: dict[str, Any]) -> str:
    """返回执行引擎可直接解析的定位串（``id::`` / ``name::`` / ``xpath::`` …）。

    历史上用过 ``i:`` / ``a:`` 压缩前缀，模型会原样填进关键字参数，而
    ``ExecutionContext.resolve`` 只认 ``::`` 形式，最终被当成裸 XPath 失败。
    """
    loc = el.get("locators") if isinstance(el.get("locators"), dict) else {}
    plat = str(el.get("platform") or "").lower()
    if plat == "ios":
        order = (
            ("accessibility_id", "name::"),
            ("label", "name::"),
            ("id", "name::"),
            ("xpath", "xpath::"),
        )
    elif plat == "android":
        order = (
            ("id", "id::"),
            ("id_short", "id::"),
            ("accessibility_id", "name::"),
            ("xpath", "xpath::"),
        )
    else:
        order = (
            ("id", "id::"),
            ("css", "css::"),
            ("testid", "css::"),
            ("xpath", "xpath::"),
            ("accessibility_id", "name::"),
            ("label", "name::"),
        )
    for key, prefix in order:
        val = str(loc.get(key) or "").strip()
        if val:
            # testid 常是属性值，尽量收成可点的 css；已带选择器前缀则原样
            if key == "testid" and not val.startswith(("#", ".", "[", "css::")):
                val = f'[data-testid="{val}"]'
            return f"{prefix}{val[:80]}"
    rid = str(el.get("resource_id") or el.get("resource-id") or "").strip()
    if rid:
        return f"id::{rid[:80]}"
    name = str(el.get("name") or "").strip()
    if name:
        return f"name::{name[:80]}"
    return ""


def compact_signature(el: dict[str, Any]) -> dict[str, Any]:
    """AI 侧 compact 控件描述（短 key / 截断文本；含 Android/iOS 关键字段）。"""
    plat = str(el.get("platform") or "").lower()
    text = str(
        el.get("text")
        or el.get("content_desc")
        or el.get("content-desc")
        or el.get("label")
        or el.get("name")
        or el.get("placeholder")
        or ""
    ).strip()
    tag = str(el.get("tag") or el.get("type") or el.get("class") or "").strip()
    classes = _filter_classes(el.get("class") or el.get("className") or "")
    pos = ""
    bounds = el.get("bounds") or el.get("rect")
    if isinstance(bounds, (list, tuple)) and len(bounds) >= 4:
        x, y, w, h = (int(bounds[0]), int(bounds[1]), int(bounds[2]), int(bounds[3]))
        pos = f"{x},{y},{w},{h}"
    elif isinstance(bounds, dict):
        pos = (
            f"{int(bounds.get('x', 0))},"
            f"{int(bounds.get('y', 0))},"
            f"{int(bounds.get('w', bounds.get('width', 0)))},"
            f"{int(bounds.get('h', bounds.get('height', 0)))}"
        )
    out: dict[str, Any] = {}
    if plat in ("android", "ios", "web"):
        out["pl"] = plat[0]  # a/i/w
    if tag:
        out["t"] = tag.split(".")[-1].replace("XCUIElementType", "")[:40]
    if text:
        out["tx"] = text[:MAX_TEXT_LEN]
    # Android：resource-id / content-desc / 短 class（FQCN 不做 web 语义 class 过滤）
    rid = str(el.get("resource_id") or el.get("resource-id") or "").strip()
    if rid:
        out["rid"] = rid[-48:] if len(rid) > 48 else rid
    cd = str(el.get("content_desc") or el.get("content-desc") or "").strip()
    if cd and cd != text:
        out["cd"] = cd[:MAX_TEXT_LEN]
    pkg = str(el.get("package") or "").strip()
    if pkg:
        out["pkg"] = pkg.split(".")[-1][:24]
    if plat == "android" and tag:
        # 移动端 class 本身就是控件类型
        out["t"] = tag.split(".")[-1][:40]
    elif classes:
        out["cls"] = classes[0][:40]
    # iOS：name / label / value
    name = str(el.get("name") or "").strip()
    label = str(el.get("label") or "").strip()
    value = str(el.get("value") or "").strip()
    if name and name != text:
        out["nm"] = name[:MAX_TEXT_LEN]
    if label and label not in (text, name):
        out["lb"] = label[:MAX_TEXT_LEN]
    if value and value not in (text, name, label) and not el.get("password"):
        out["vl"] = value[:MAX_TEXT_LEN]
    loc = _best_locator(el)
    if loc:
        out["l"] = loc
    if pos:
        out["p"] = pos
    if el.get("clickable") in (True, "true", "True", 1, "1"):
        out["ck"] = 1
    if el.get("editable") in (True, "true", "True", 1, "1"):
        out["ed"] = 1
    if el.get("enabled") in (False, "false", "False", 0, "0"):
        out["en"] = 0
    if el.get("checked") in (True, "true", "True", 1, "1"):
        out["ch"] = 1
    return out


def full_signature(el: dict[str, Any]) -> dict[str, Any]:
    """失败补全用的完整一点描述（仍截断，非 page_source dump）。"""
    compact = compact_signature(el)
    text = str(
        el.get("text") or el.get("content_desc") or el.get("label") or el.get("name") or ""
    ).strip()
    if text:
        compact["tx"] = text[:FULL_TEXT_LEN]
    attrs = el.get("attrs") if isinstance(el.get("attrs"), dict) else {}
    keep = {}
    for k in (
        "id",
        "name",
        "type",
        "role",
        "placeholder",
        "resource-id",
        "content-desc",
        "text",
        "label",
        "value",
        "href",
        "class",
        "package",
        "clickable",
        "enabled",
        "checkable",
        "checked",
        "scrollable",
        "long-clickable",
        "focusable",
        "focused",
        "selected",
        "visible",
        "password",
        "x",
        "y",
        "width",
        "height",
        "bounds",
        "index",
    ):
        v = attrs.get(k) if k in attrs else el.get(k)
        if v not in (None, ""):
            keep[k] = str(v)[:80]
    if keep:
        compact["attrs"] = keep
    locators = el.get("locators") if isinstance(el.get("locators"), dict) else {}
    if locators:
        compact["loc"] = {k: str(v)[:120] for k, v in locators.items() if v}
    return compact


def image_profile(
    *,
    enhanced: bool = False,
    element_count: int = 0,
    short_side: int | None = None,
    max_kb: int | None = None,
    detail: str | None = None,
) -> dict[str, Any]:
    """截图画质档位（借鉴 Midscene：首轮省 token，失败/无 DOM 时升质）。

    - standard：短边约 560（≈手机 shrink×2）、≤220KB、detail=low
    - no_dom：无控件摘要时略升，detail=auto
    - enhanced：短边 720、≤350KB、detail=high（定位失败重试）
    """
    ss = int(short_side) if short_side else None
    mk = int(max_kb) if max_kb else None
    if enhanced:
        return {
            "tier": "enhanced",
            "short_side": max(ss or 720, 720),
            "max_kb": max(mk or 350, 350),
            "detail": detail or "high",
            "dom_mode": "full",
            "quality": 90,
        }
    if element_count <= 0:
        return {
            "tier": "no_dom",
            "short_side": max(ss or 640, 640),
            "max_kb": max(mk or 280, 280),
            "detail": detail if detail in ("high", "auto", "original") else "auto",
            "dom_mode": None,
            "quality": 85,
        }
    return {
        "tier": "standard",
        "short_side": ss or 560,
        "max_kb": mk or 220,
        "detail": detail or "low",
        "dom_mode": None,
        "quality": 85,
    }


def _tokenize_prompt(prompt: str) -> set[str]:
    raw = (prompt or "").strip().lower()
    if not raw:
        return set()
    parts = [p for p in re.split(r"[\s,，。；;|/\\_+-]+", raw) if p]
    tokens = {p for p in parts if len(p) >= 2}
    # 「点击登录」整词匹配不上控件 tx=登录；补汉字二字组
    for part in parts or [raw]:
        chars = list(part)
        if len(chars) >= 2 and any("\u4e00" <= ch <= "\u9fff" for ch in chars):
            for i in range(len(chars) - 1):
                gram = "".join(chars[i : i + 2])
                if len(gram.strip()) >= 2:
                    tokens.add(gram)
    return expand_intent_tokens(tokens, raw)


def _is_interactive(el: dict[str, Any]) -> bool:
    if el.get("clickable") in (True, "true", "True", 1, "1"):
        return True
    if el.get("checkable") in (True, "true", "True", 1, "1"):
        return True
    tag = str(el.get("tag") or el.get("type") or el.get("class") or "").strip().lower()
    short = tag.split(".")[-1].replace("xcuielementtype", "")
    if tag in _INTERACTIVE_TAGS or short in _INTERACTIVE_TAGS:
        return True
    if any(
        h in short
        for h in (
            "button",
            "edittext",
            "textfield",
            "checkbox",
            "switch",
            "radiobutton",
            "spinner",
            "cell",
            "link",
        )
    ):
        return True
    role = str(el.get("role") or "").lower()
    if role in ("button", "link", "textbox", "checkbox", "radio", "menuitem", "tab"):
        return True
    if el.get("tabindex") not in (None, "", "-1"):
        return True
    # 有稳定 id / name 的节点也视为定位价值高
    if el.get("resource_id") or el.get("name") or el.get("content_desc"):
        return True
    return False


def _el_blob(el: dict[str, Any]) -> str:
    bits = [
        str(el.get("tag") or ""),
        str(el.get("text") or ""),
        str(el.get("content_desc") or el.get("content-desc") or ""),
        str(el.get("label") or ""),
        str(el.get("name") or ""),
        str(el.get("value") or ""),
        str(el.get("placeholder") or ""),
        str(el.get("id") or ""),
        str(el.get("resource_id") or el.get("resource-id") or ""),
        str(el.get("package") or ""),
        str(el.get("class") or ""),
        str(el.get("type") or ""),
    ]
    return " ".join(bits).lower()


def filter_elements(
    elements: list[dict[str, Any]],
    *,
    prompt: str = "",
    max_count: int = 50,
) -> list[dict[str, Any]]:
    """三层过滤：必选可交互 → 与意图相关 → 尺寸补充，硬顶 max_count。"""
    if not elements:
        return []
    cap = max(1, min(200, int(max_count)))
    tokens = _tokenize_prompt(prompt)

    mandatory: list[dict[str, Any]] = []
    scored: list[tuple[float, dict[str, Any]]] = []
    for el in elements:
        if not isinstance(el, dict):
            continue
        # 丢弃明显不可见
        bounds = el.get("bounds") or el.get("rect")
        if isinstance(bounds, (list, tuple)) and len(bounds) >= 4:
            if int(bounds[2]) <= 0 or int(bounds[3]) <= 0:
                continue
        blob = _el_blob(el)
        score = 0.0
        if _is_interactive(el):
            score += 5.0
            mandatory.append(el)
        for tok in tokens:
            if tok in blob:
                score += 3.0
        if isinstance(bounds, (list, tuple)) and len(bounds) >= 4:
            area = max(0, int(bounds[2])) * max(0, int(bounds[3]))
            score += min(2.0, area / 50000.0)
            # 偏左上略加分（常见主操作区）
            score += max(0.0, 1.0 - (int(bounds[0]) + int(bounds[1])) / 2000.0)
        scored.append((score, el))

    out: list[dict[str, Any]] = []
    seen: set[int] = set()
    for el in mandatory:
        i = id(el)
        if i in seen:
            continue
        seen.add(i)
        out.append(el)
        if len(out) >= cap:
            return out[:cap]

    scored.sort(key=lambda x: x[0], reverse=True)
    for score, el in scored:
        if score < 0.5 and len(out) >= max(8, cap // 2):
            continue
        i = id(el)
        if i in seen:
            continue
        seen.add(i)
        out.append(el)
        if len(out) >= cap:
            break
    return out[:cap]


def _sanitize_signature(sig: dict[str, Any]) -> dict[str, Any]:
    """DOM 摘要里丢掉任何看起来像截图的字段。"""
    out: dict[str, Any] = {}
    for key, val in sig.items():
        if isinstance(val, str) and text_has_embedded_image(val):
            continue
        if isinstance(val, dict):
            nested = _sanitize_signature(val)
            if nested:
                out[key] = nested
            continue
        out[key] = val
    return out


def serialize_elements(
    elements: list[dict[str, Any]],
    *,
    mode: str = "compact",
) -> list[dict[str, Any]]:
    mode_l = (mode or "compact").strip().lower()
    if mode_l in ("off", "none", "0", "false"):
        return []
    if mode_l == "full":
        rows = [full_signature(el) for el in elements if compact_signature(el)]
    else:
        rows = [c for el in elements if (c := compact_signature(el))]
    return [_sanitize_signature(row) for row in rows if row]
