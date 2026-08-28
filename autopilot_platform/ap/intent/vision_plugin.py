"""Intent LLM / Vision 定位插件：截图（真多模态）或 DOM 文本 → Chat Completions。

启用：``AUTOPILOT_INTENT_VISION=1``（默认 0）。
``AUTOPILOT_VISION_IMAGE_MODE=auto`` 时按厂商能力决定是否传 ``image_url``：
DeepSeek 仅 ``*vision*`` 型号识图（见 https://api-docs.deepseek.com/zh-cn/guides/vision ）；
``deepseek-v4-flash`` / ``v4-pro`` 仍走 DOM 摘要。传图前按控件 bounds 预裁剪。
上下文预算见 ``context_budget`` / ``config``。
"""

from __future__ import annotations

import base64
import json
import logging
import re
from typing import Any

from .config import (
    vision_accepts_images,
    vision_api_key,
    vision_base_url,
    vision_dom_enabled,
    vision_dom_max,
    vision_dom_mode,
    vision_image_detail,
    vision_image_enhanced,
    vision_image_max_kb,
    vision_image_mode,
    vision_image_short_side,
    vision_model,
    vision_provider_is_text_only,
    vision_screenshot_enabled,
    vision_timeout_sec,
)
from .context_budget import (
    CROP_ENHANCED_LONG_SIDE,
    CROP_MAX_KB,
    CROP_TARGET_LONG_SIDE,
    compress_screenshot,
    crop_focus_elements,
    filter_elements,
    image_profile,
    precrop_screenshot,
    serialize_elements,
    shift_element_bounds,
    strip_embedded_images_from_text,
    text_has_embedded_image,
)
from .provider_profile import detect_provider
from .manual_bind import default_keyword_id
from .ui_context import collect_ui_elements

log = logging.getLogger(__name__)

_VISION_PROMPT = """你是 UI 自动化定位助手。根据{context_hint}，给出 1～3 个可用定位符候选。
禁止输出 xpath 以外的框架关键字名；只给定位串。
注意：截图（若有）仅通过独立 image 通道提供；下列 JSON 不含截图 base64。

意图：action={action} target={target} value={value} platform={platform}

控件摘要 compact 字段：
pl=平台(a/i/w) t=类型 tx=文案 rid=resource-id cd=content-desc pkg=包名
nm=name lb=label vl=value l=定位串 p=x,y,w,h ck=可点 en=enabled ch=checked
{elements_json}

严格输出 JSON（不要 Markdown）：
{{
  "candidates": [
    {{
      "locator": "xpath:://*[@text='登录'] 或 id=xxx 或 accessibility_id=yyy",
      "confidence": 0.0到1.0,
      "reason": "简短理由"
    }}
  ]
}}

定位约定：
- web：优先 xpath:: / css:: / id=
- android：优先 id=<resource-id> 或 accessibility_id=<content-desc> 或 xpath:://*[@resource-id|@text|@content-desc=...]
- ios：优先 accessibility_id=<name> 或 id=<name> 或 xpath:://*[@name|@label=...]
若无法判断，返回空 candidates 数组。
"""

_UNSUPPORTED_IMAGE_MARKERS = (
    "[unsupported image]",
    "unsupported image",
    "unknown variant `image_url`",
    "unknown variant image_url",
    "expected text",
)


def text_parts_only(parts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """去掉 image_url / image 块，仅保留文本。"""
    out: list[dict[str, Any]] = []
    for part in parts or []:
        if not isinstance(part, dict):
            continue
        ptype = str(part.get("type") or "").lower()
        if ptype in ("image_url", "image", "input_image"):
            continue
        out.append(part)
    return out


def flatten_text_content(parts: list[dict[str, Any]]) -> str:
    """纯文本厂商：user content 须为 Text string（DeepSeek 非 vision 型号）。"""
    chunks: list[str] = []
    for part in parts or []:
        if not isinstance(part, dict):
            continue
        if str(part.get("type") or "").lower() == "text":
            t = str(part.get("text") or "").strip()
            if t:
                chunks.append(t)
    return strip_embedded_images_from_text("\n\n".join(chunks).strip())


def looks_like_unsupported_image(text: str) -> bool:
    raw = (text or "").strip().lower()
    if not raw:
        return False
    return any(m in raw for m in _UNSUPPORTED_IMAGE_MARKERS)


def normalize_user_content(
    parts: list[dict[str, Any]],
    *,
    accepts_images: bool,
) -> str | list[dict[str, Any]]:
    """按厂商能力归一化 user content。

    - 真多模态（含 DeepSeek vision）：OpenAI 风格 parts（可含 image_url）
    - 纯文本型号：拼接为 string（官方 schema 要求 Text content）
    """
    usable = parts if accepts_images else text_parts_only(parts)
    if not accepts_images or vision_provider_is_text_only():
        return flatten_text_content(usable)
    return usable


def capture_screenshot_png(ctx: Any) -> bytes | None:
    """从 ExecutionContext 抓 PNG 字节。"""
    if ctx is None:
        return None

    def _try_driver(drv: Any) -> bytes | None:
        if drv is None:
            return None
        if hasattr(drv, "get_screenshot_as_png"):
            raw = drv.get_screenshot_as_png()
            if isinstance(raw, (bytes, bytearray)) and raw:
                return bytes(raw)
        return None

    # Appium
    try:
        mgr = getattr(ctx, "appium", None)
        if mgr is not None:
            shot = _try_driver(mgr.driver() if callable(getattr(mgr, "driver", None)) else None)
            if shot:
                return shot
    except (AttributeError, TypeError, RuntimeError, OSError):
        pass
    # Web
    try:
        web = getattr(ctx, "web", None)
        if web is not None:
            shot = _try_driver(web.driver() if callable(getattr(web, "driver", None)) else None)
            if shot:
                return shot
    except (AttributeError, TypeError, RuntimeError, OSError):
        pass
    # 直连 driver
    try:
        shot = _try_driver(getattr(ctx, "driver", None))
        if shot:
            return shot
    except (AttributeError, TypeError, RuntimeError, OSError):
        pass
    return None


def _strip_fence(text: str) -> str:
    s = (text or "").strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.IGNORECASE)
        s = re.sub(r"\s*```$", "", s)
    return s.strip()


def parse_vision_response(content: str) -> list[dict[str, Any]]:
    """解析模型 JSON → [{locator, confidence, reason}, ...]。"""
    raw = _strip_fence(content)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*}", raw)
        if not m:
            return []
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return []
    rows = data.get("candidates") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return []
    out: list[dict[str, Any]] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        loc = str(item.get("locator") or "").strip()
        if not loc:
            continue
        try:
            conf = float(item.get("confidence") if item.get("confidence") is not None else 0.5)
        except (TypeError, ValueError):
            conf = 0.5
        out.append(
            {
                "locator": loc,
                "confidence": max(0.0, min(1.0, conf)),
                "reason": str(item.get("reason") or "")[:200],
            }
        )
    return out


def candidates_from_hints(
    hints: list[dict[str, Any]],
    *,
    action: str,
    value: str,
    platform: str,
) -> list[dict[str, Any]]:
    """把视觉 hint 转成 IntentRuntime 候选。"""
    plat = (platform or "web").strip().lower() or "web"
    act = (action or "click").strip().lower() or "click"
    kid = default_keyword_id(plat, act)
    out: list[dict[str, Any]] = []
    for h in hints:
        loc = str(h.get("locator") or "").strip()
        if not loc:
            continue
        if loc.startswith("//") or loc.startswith("(//"):
            loc = f"xpath::{loc}"
        params: dict[str, Any] = {"locator": loc}
        if act == "type":
            params["text"] = value or ""
        if act == "open":
            params = {"url": loc}
        if act == "assert" and plat != "web":
            params["outVar"] = "__intent_assert__"
        score = 0.35 + 0.5 * float(h.get("confidence") or 0.5)
        out.append(
            {
                "keyword_id": kid,
                "params": params,
                "locator": loc if act != "open" else params.get("url", loc),
                "score": round(min(0.95, score), 3),
                "resolver": "vision",
                "reason": h.get("reason") or "",
            }
        )
    return out


def build_vision_payload(
    *,
    action: str,
    target: str,
    value: str,
    platform: str,
    ctx: Any = None,
    png: bytes | None = None,
    enhanced: bool | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """组装多模态 content parts + 调试元数据。

    ``enhanced=True``：升质（短边 720 / detail=high / DOM full），用于定位失败重试。
    无 DOM 时自动略升画质（detail=auto），降低纯图标页误识别。
    传图前按过滤控件 bounds 预裁剪，并把 DOM 坐标平移到裁后图。
    """
    plat = (platform or "web").strip().lower() or "web"
    prompt_key = f"{action} {target} {value}".strip()
    use_enhanced = bool(enhanced) if enhanced is not None else vision_image_enhanced()
    accepts_images = vision_accepts_images()
    elements_json = "[]"
    meta: dict[str, Any] = {
        "screenshot": False,
        "dom": False,
        "element_count": 0,
        "image_bytes": 0,
        "image_mime": "",
        "image_tier": "",
        "dom_mode": "",
        "accepts_images": accepts_images,
        "image_mode": vision_image_mode(),
        "image_skipped_reason": "",
        "text_only_provider": vision_provider_is_text_only(),
        "image_crop": {},
    }

    dom_mode = vision_dom_mode()
    filtered: list[dict[str, Any]] = []
    if vision_dom_enabled():
        filtered = filter_elements(
            collect_ui_elements(ctx, platform=plat),
            prompt=prompt_key,
            max_count=vision_dom_max(),
        )

    will_attach_image = bool(accepts_images and vision_screenshot_enabled())
    raw = None
    if will_attach_image:
        raw = png if png is not None else capture_screenshot_png(ctx)
        if raw:
            crop_src = crop_focus_elements(filtered, prompt=prompt_key)
            crop_side = (
                CROP_ENHANCED_LONG_SIDE if use_enhanced else CROP_TARGET_LONG_SIDE
            )
            raw, _, crop_meta = precrop_screenshot(
                raw, crop_src, max_side=crop_side
            )
            meta["image_crop"] = crop_meta
            box = crop_meta.get("box") if crop_meta.get("cropped") else None
            if isinstance(box, (list, tuple)) and len(box) >= 4:
                filtered = shift_element_bounds(
                    filtered, (int(box[0]), int(box[1]), int(box[2]), int(box[3]))
                )

    packed: list[dict[str, Any]] = []
    if vision_dom_enabled():
        # 先按配置 mode；enhanced 时升 full（对齐 Midscene compact→full）
        mode = "full" if use_enhanced else dom_mode
        packed = serialize_elements(filtered, mode=mode)
        elements_json = json.dumps(packed, ensure_ascii=False, separators=(",", ":"))
        meta["dom"] = bool(packed)
        meta["element_count"] = len(packed)
        meta["dom_mode"] = mode

    profile = image_profile(
        enhanced=use_enhanced,
        element_count=len(packed),
        short_side=vision_image_short_side(),
        max_kb=vision_image_max_kb(),
        detail=vision_image_detail() if not use_enhanced else "high",
    )
    # 环境变量显式指定的 short_side/max_kb 作为下限/覆盖：profile 用 env 值优先
    # （image_profile 已接收 short_side/max_kb；enhanced 时仍用 720/350 除非 env 更大）
    if use_enhanced:
        profile["short_side"] = max(int(profile["short_side"]), vision_image_short_side())
        profile["max_kb"] = max(int(profile["max_kb"]), vision_image_max_kb())
    max_long_side = CROP_TARGET_LONG_SIDE
    if use_enhanced:
        max_long_side = CROP_ENHANCED_LONG_SIDE
    if meta.get("image_crop", {}).get("cropped"):
        profile["short_side"] = min(int(profile["short_side"]), max_long_side)
        profile["max_kb"] = min(int(profile["max_kb"]), CROP_MAX_KB)
    elif detect_provider("", vision_model(), vision_base_url()) == "deepseek" and accepts_images:
        profile["short_side"] = min(int(profile["short_side"]), max_long_side)
    meta["image_tier"] = str(profile.get("tier") or "")

    context_hint = "截图与/或控件摘要" if will_attach_image else "控件摘要（当前型号为纯文本 API，不传截图）"
    if text_has_embedded_image(elements_json):
        log.warning("vision: DOM JSON contained embedded image; stripped")
        elements_json = strip_embedded_images_from_text(elements_json)
    prompt = _VISION_PROMPT.format(
        context_hint=context_hint,
        action=action or "custom",
        target=target or "",
        value=value or "",
        platform=plat,
        elements_json=elements_json,
    )
    if text_has_embedded_image(prompt):
        log.warning("vision: text prompt contained embedded image; stripped")
        prompt = strip_embedded_images_from_text(prompt)
    parts: list[dict[str, Any]] = [{"type": "text", "text": prompt}]

    if vision_screenshot_enabled() and not accepts_images:
        meta["image_skipped_reason"] = (
            "provider_text_only"
            if meta["text_only_provider"]
            else f"image_mode={vision_image_mode()}"
        )
        log.info(
            "vision: skip screenshot (%s); 当前型号不接受 image_url，走 DOM 摘要",
            meta["image_skipped_reason"],
        )
    elif vision_screenshot_enabled() and raw:
        img, mime = compress_screenshot(
            raw,
            target_short_side=int(profile["short_side"]),
            max_kb=int(profile["max_kb"]),
            quality=int(profile.get("quality") or 85),
            max_long_side=max_long_side,
        )
        if len(img) > max(int(profile["max_kb"]) * 1024 * 3, 600_000):
            log.warning("vision: screenshot still too large (%s), skip image", len(img))
            meta["image_skipped_reason"] = "image_too_large"
        else:
            b64 = base64.b64encode(img).decode("ascii")
            parts.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{mime};base64,{b64}",
                        "detail": str(profile.get("detail") or "low"),
                    },
                }
            )
            meta["screenshot"] = True
            meta["image_bytes"] = len(img)
            meta["image_mime"] = mime

    if len(parts) == 1 and elements_json == "[]":
        return [], meta
    return parts, meta


def _post_vision_chat(
    *,
    content: str | list[dict[str, Any]],
    key: str,
) -> tuple[str, dict[str, Any], dict[str, int]]:
    import httpx

    from .config import vision_reasoning_effort, vision_temperature, vision_verbosity
    from .provider_profile import (
        apply_max_output_tokens,
        apply_reasoning_to_body,
        apply_verbosity_to_body,
        detect_provider,
        should_omit_temperature,
    )
    from .usage import empty_usage, extract_usage, record_vision_usage

    model = vision_model()
    base = vision_base_url()
    provider = detect_provider("", model, base)
    url = f"{base.rstrip('/')}/chat/completions"
    body: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": content}],
    }
    apply_max_output_tokens(body, model, 800)
    apply_reasoning_to_body(
        body,
        provider=provider,
        model=model,
        effort=vision_reasoning_effort(),
        base_url=base,
    )
    apply_verbosity_to_body(
        body,
        provider=provider,
        model=model,
        verbosity=vision_verbosity(),
        base_url=base,
    )
    thinking_on = body.get("thinking") == {"type": "enabled"}
    if not should_omit_temperature(provider, model, thinking_enabled=bool(thinking_on)):
        body["temperature"] = vision_temperature()
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    with httpx.Client(timeout=vision_timeout_sec()) as client:
        resp = client.post(url, headers=headers, json=body)
        if resp.status_code >= 400:
            detail = (resp.text or "")[:500]
            raise RuntimeError(f"vision HTTP {resp.status_code}: {detail}")
        data = resp.json()
    if not isinstance(data, dict):
        raise ValueError(f"vision 响应结构异常: {data!r}")
    try:
        usage = extract_usage(data)
        record_vision_usage(usage, model=vision_model())
    except (TypeError, ValueError, KeyError, OSError):
        usage = empty_usage()
    try:
        text = str(data["choices"][0]["message"]["content"] or "")
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError(f"vision 响应结构异常: {data!r}") from exc
    return text, data, usage


def call_vision_api(
    *,
    png: bytes | None = None,
    action: str,
    target: str,
    value: str,
    platform: str,
    ctx: Any = None,
    content_parts: list[dict[str, Any]] | None = None,
    enhanced: bool | None = None,
    payload_meta: dict[str, Any] | None = None,
) -> str:
    """调用 Chat Completions，返回 content 文本。

    DeepSeek 非 vision 型号走纯文本（string content + DOM）；vision / 其它多模态传 image_url。
    若误传图片导致 400 / ``[Unsupported Image]``，自动降级为文本重试一次。
    """
    key = vision_api_key()
    if not key:
        raise RuntimeError("vision api key not configured")

    parts = content_parts
    meta: dict[str, Any] = dict(payload_meta or {})
    if parts is None:
        parts, built = build_vision_payload(
            action=action,
            target=target,
            value=value,
            platform=platform,
            ctx=ctx,
            png=png,
            enhanced=enhanced,
        )
        meta = dict(built or {})
    if not parts:
        raise RuntimeError("vision context empty (screenshot/dom both unavailable)")

    accepts = vision_accepts_images()
    has_image = any(
        isinstance(p, dict) and str(p.get("type") or "").lower() in ("image_url", "image")
        for p in parts
    )
    content = normalize_user_content(parts, accepts_images=accepts and has_image)
    if isinstance(content, str) and not content.strip():
        raise RuntimeError("vision context empty after stripping images")

    used_image = bool(has_image and accepts)
    try:
        text, _data, usage = _post_vision_chat(content=content, key=key)
    except RuntimeError as exc:
        err = str(exc).lower()
        if has_image and looks_like_unsupported_image(err):
            log.warning("vision: image rejected by provider, retry text-only: %s", exc)
            text_only = flatten_text_content(text_parts_only(parts))
            if not text_only:
                raise
            text, _data, usage = _post_vision_chat(content=text_only, key=key)
            used_image = False
        else:
            raise

    if has_image and looks_like_unsupported_image(text):
        log.warning(
            "vision: response indicates unsupported image (%r); retry text-only",
            text[:120],
        )
        text_only = flatten_text_content(text_parts_only(parts))
        if text_only:
            text, _data, usage = _post_vision_chat(content=text_only, key=key)
            used_image = False

    if ctx is not None and hasattr(ctx, "set_var"):
        try:
            ctx.set_var("__last_vision_usage__", dict(usage or {}))
            ctx.set_var(
                "__last_vision_used_screenshot__",
                bool(used_image and meta.get("screenshot")),
            )
            if meta.get("element_count") is not None:
                n = int(meta.get("element_count") or 0)
                ctx.set_var("__last_ui_elements_count__", n)
        except (AttributeError, TypeError, ValueError):
            pass
    return text


def propose_candidates(
    *,
    action: str,
    target: str,
    value: str,
    platform: str,
    ctx: Any = None,
    enhanced: bool | None = None,
) -> list[dict[str, Any]]:
    """Vision 钩子入口（由 vision.vision_candidates 调用）。"""
    parts, meta = build_vision_payload(
        action=action,
        target=target,
        value=value,
        platform=platform,
        ctx=ctx,
        enhanced=enhanced,
    )
    if not parts:
        log.debug("vision: empty context meta=%s", meta)
        return []
    log.debug(
        "vision: tier=%s screenshot=%s (%sB %s) skip=%s dom=%s mode=%s els=%s text_only=%s",
        meta.get("image_tier"),
        meta.get("screenshot"),
        meta.get("image_bytes"),
        meta.get("image_mime"),
        meta.get("image_skipped_reason") or "-",
        meta.get("dom"),
        meta.get("dom_mode"),
        meta.get("element_count"),
        meta.get("text_only_provider"),
    )
    try:
        content = call_vision_api(
            action=action,
            target=target,
            value=value,
            platform=platform,
            ctx=ctx,
            content_parts=parts,
            enhanced=enhanced,
            payload_meta=meta,
        )
    except (RuntimeError, ValueError, OSError, TypeError, KeyError) as exc:
        log.warning("vision API failed: %s", exc)
        return []
    hints = parse_vision_response(content)
    return candidates_from_hints(hints, action=action, value=value, platform=platform)
