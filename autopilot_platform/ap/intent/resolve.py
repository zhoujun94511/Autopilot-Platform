"""按平台将意图解析为 keyword_id + params 候选。"""

from __future__ import annotations

import re
from typing import Any

from .heal_attr import looks_like_http_intent
from .risk import filter_safe_candidates
from .synonyms import target_aliases

_HTTP_METHODS = ("get", "post", "put", "patch", "delete", "head", "options")
_METHOD_RE = re.compile(
    r"\b(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\b",
    re.IGNORECASE,
)
_URL_RE = re.compile(
    r"(https?://[^\s\"'<>]+|/[A-Za-z0-9_./\-?&=%~:+]+)",
    re.IGNORECASE,
)
_STATUS_RE = re.compile(
    r"(?:status|状态码|响应码)\s*[=:]?\s*(\d{3}(?:\s*-\s*\d{3})?)",
    re.IGNORECASE,
)


def detect_platform(ctx: Any) -> str:
    """web | android | ios。"""
    plat = str(
        getattr(ctx, "get_var", lambda *_a, **_k: "")("__inspect_platform__")
        or getattr(ctx, "get_var", lambda *_a, **_k: "")("__run_platform__")
        or ""
    ).strip().lower()
    if plat in ("web", "android", "ios"):
        return plat
    # Appium manager
    mgr = getattr(ctx, "appium", None)
    if mgr is not None:
        p = str(getattr(mgr, "platform", "") or "").strip().lower()
        if p in ("android", "ios"):
            return p
    if getattr(ctx, "driver", None) is not None and mgr is None:
        return "web"
    return "web"


def _xpath_string_literal(value: str) -> str:
    """把任意文本安全嵌入 XPath 1.0 字符串字面量（含引号时用 concat）。"""
    s = (value or "").replace("\x00", "")
    if "'" not in s and '"' not in s:
        return f"'{s}'"
    if "'" not in s:
        return f"'{s}'"
    if '"' not in s:
        return f'"{s}"'
    parts: list[str] = []
    chunks = s.split("'")
    for i, chunk in enumerate(chunks):
        if chunk:
            parts.append(f"'{chunk}'")
        if i < len(chunks) - 1:
            parts.append('"\'"')
    return "concat(" + ", ".join(parts) + ")" if parts else "''"


def _or_contains(expr: str, terms: list[str]) -> str:
    """``contains(expr, 'a') or contains(expr, 'b')``。"""
    bits: list[str] = []
    seen: set[str] = set()
    for term in terms:
        raw = (term or "").strip()
        if not raw or raw.lower() in seen:
            continue
        seen.add(raw.lower())
        bits.append(f"contains({expr},{_xpath_string_literal(raw)})")
    return " or ".join(bits) if bits else f"contains({expr},{_xpath_string_literal('')})"


def _web_candidates(action: str, target: str, value: str) -> list[dict[str, Any]]:
    t = (target or "").strip()
    v = (value or "").strip()
    terms = target_aliases(t)
    text_or = _or_contains("normalize-space(.)", terms)
    value_or = _or_contains("@value", terms)
    cands: list[dict[str, Any]] = []
    if action == "open":
        url = v or t
        cands.append(
            {
                "keyword_id": "web_browser_locate",
                "params": {"url": url},
                "locator": url,
                "score": 0.99,
            }
        )
        return cands
    if action == "wait":
        cands.append(
            {
                "keyword_id": "web_common_sleep",
                "params": {"millis": "1000"},
                "locator": "",
                "score": 0.5,
            }
        )
        return cands
    if not t and action != "custom":
        return cands
    # 文本/占位启发式 xpath（字面量已转义；含中英同义）
    xp_text = f"xpath:://*[{text_or}]"
    xp_btn = (
        f"xpath:://button[{text_or}]"
        f"|//a[{text_or}]"
        f"|//*[{value_or}]"
    )
    if action == "click":
        cands.append(
            {
                "keyword_id": "web_element_click",
                "params": {"locator": xp_btn},
                "locator": xp_btn,
                "score": 0.8,
            }
        )
        cands.append(
            {
                "keyword_id": "web_element_click",
                "params": {"locator": xp_text},
                "locator": xp_text,
                "score": 0.55,
            }
        )
    elif action == "type":
        ph_or = _or_contains("@placeholder", terms)
        xp_input = (
            f"xpath:://input[{ph_or}]"
            f"|//textarea[{ph_or}]"
            f"|//label[{text_or}]/following::input[1]"
        )
        cands.append(
            {
                "keyword_id": "web_element_text_input",
                "params": {"locator": xp_input, "text": v},
                "locator": xp_input,
                "score": 0.75,
            }
        )
        cands.append(
            {
                "keyword_id": "web_element_text_input",
                "params": {"locator": xp_text, "text": v},
                "locator": xp_text,
                "score": 0.45,
            }
        )
    elif action == "assert":
        cands.append(
            {
                "keyword_id": "web_verify_element_existed",
                "params": {"locator": xp_text},
                "locator": xp_text,
                "score": 0.7,
            }
        )
    else:
        cands.append(
            {
                "keyword_id": "web_element_click",
                "params": {"locator": xp_text},
                "locator": xp_text,
                "score": 0.3,
            }
        )
    return cands


def _mobile_candidates(
    action: str, target: str, value: str, *, platform: str
) -> list[dict[str, Any]]:
    t = (target or "").strip()
    v = (value or "").strip()
    terms = target_aliases(t)
    cands: list[dict[str, Any]] = []
    if action == "wait":
        cands.append(
            {
                "keyword_id": "web_common_sleep",
                "params": {"millis": "1000"},
                "locator": "",
                "score": 0.5,
            }
        )
        return cands
    if action == "open":
        # 移动端「打开」通常已在会话里；降级为等待
        cands.append(
            {
                "keyword_id": "web_common_sleep",
                "params": {"millis": "500"},
                "locator": "",
                "score": 0.4,
            }
        )
        return cands
    if not t:
        return cands
    if platform == "ios":
        xp = f"xpath:://*[{_or_contains('@name', terms)} or {_or_contains('@label', terms)}]"
        xp2 = f"xpath:://*[{_or_contains('@value', terms)} or {_or_contains('@label', terms)}]"
    else:
        xp = f"xpath:://*[{_or_contains('@text', terms)} or {_or_contains('@content-desc', terms)}]"
        xp2 = f"xpath:://*[{_or_contains('@resource-id', terms)}]"
    if action == "click":
        cands.append(
            {
                "keyword_id": "mobile_element_click",
                "params": {"locator": xp},
                "locator": xp,
                "score": 0.8,
            }
        )
        cands.append(
            {
                "keyword_id": "mobile_element_click",
                "params": {"locator": xp2},
                "locator": xp2,
                "score": 0.5,
            }
        )
    elif action == "type":
        cands.append(
            {
                "keyword_id": "mobile_element_text_input",
                "params": {"locator": xp, "text": v},
                "locator": xp,
                "score": 0.75,
            }
        )
    elif action == "assert":
        # 必须用会抛错的 verify；get_element_exist 仅写 OUT、从不失败
        cands.append(
            {
                "keyword_id": "mobile_verify_element_existed",
                "params": {"locator": xp, "isExisted": "true", "timeout": "5000"},
                "locator": xp,
                "score": 0.7,
            }
        )
    elif action == "swipe":
        cands.append(
            {
                "keyword_id": "mobile_element_swipe",
                "params": {"locator": xp, "direction": "上"},
                "locator": xp,
                "score": 0.6,
            }
        )
    else:
        cands.append(
            {
                "keyword_id": "mobile_element_click",
                "params": {"locator": xp},
                "locator": xp,
                "score": 0.3,
            }
        )
    return cands


def _http_candidates(
    action: str,
    target: str,
    value: str,
    text: str = "",
) -> list[dict[str, Any]]:
    """从意图文案启发式解析 HTTP 关键字候选（不发起请求）。"""
    blob = " ".join(x for x in (text, action, target, value) if x).strip()
    if not blob:
        return []

    method = "get"
    m = _METHOD_RE.search(blob)
    if m:
        method = m.group(1).lower()
    else:
        act = (action or "").strip().lower()
        if act in _HTTP_METHODS:
            method = act
        elif act in ("assert", "verify", "expect", "check"):
            method = "get"
        elif re.search(r"\bpost\b|提交|创建|写入", blob, re.I):
            method = "post"
        elif re.search(r"\bput\b|更新|修改", blob, re.I):
            method = "put"
        elif re.search(r"\bpatch\b", blob, re.I):
            method = "patch"
        elif re.search(r"\bdelete\b|删除", blob, re.I):
            method = "delete"

    url = ""
    um = _URL_RE.search(blob)
    if um:
        url = um.group(1).rstrip(".,;)")
    elif (target or "").strip().startswith("/"):
        url = (target or "").strip()
    elif (value or "").strip().startswith(("/", "http://", "https://")):
        url = (value or "").strip()
    if not url:
        return []

    kid = f"http_{method}"
    follow_ups: list[dict[str, Any]] = []
    assert_spec: dict[str, Any] = {}
    sm = _STATUS_RE.search(blob)
    if sm:
        expected = sm.group(1).replace(" ", "")
        assert_spec["status"] = expected
        follow_ups.append(
            {
                "keyword_id": "http_assert_status",
                "params": {"expected": expected},
            }
        )
    elif (action or "").strip().lower() in ("assert", "verify", "expect", "check"):
        assert_spec["status"] = "200-299"
        follow_ups.append(
            {
                "keyword_id": "http_assert_status",
                "params": {"expected": "200-299"},
            }
        )

    score = 0.85 if m and um else 0.7
    return [
        {
            "keyword_id": kid,
            "params": {"url": url},
            "locator": url,
            "score": score,
            "resolver": "http_heuristic",
            "channel": "http",
            "method": method.upper(),
            "path": url,
            "assert": assert_spec,
            "follow_ups": follow_ups,
        }
    ]


def normalize_channel(channel: str | None) -> str:
    ch = (channel or "ui").strip().lower()
    if ch in ("ui", "http", "auto"):
        return ch
    return "ui"


def effective_channel(
    channel: str | None,
    *,
    cached: dict[str, Any] | None = None,
    intent_text: str = "",
    action: str = "",
    target: str = "",
    value: str = "",
) -> str:
    """将 ui|http|auto 解析为实际执行通道。"""
    ch = normalize_channel(channel)
    if ch in ("ui", "http"):
        return ch
    # auto
    if isinstance(cached, dict):
        cch = str(cached.get("channel") or "").strip().lower()
        plat = str(cached.get("platform") or "").strip().lower()
        if cch == "http" or plat == "http":
            return "http"

    if looks_like_http_intent(intent_text, action, target, value):
        return "http"
    return "ui"


def resolve_candidates(
    *,
    action: str,
    target: str,
    value: str,
    platform: str,
    ctx: Any = None,
    include_vision: bool | None = None,
    vision_enhanced: bool = False,
    channel: str = "ui",
    text: str = "",
    blocked_out: list[str] | None = None,
) -> list[dict[str, Any]]:
    """解析意图候选。

    ``channel``:
      - ``ui``：Web/Mobile（+ 可选 Vision）
      - ``http``：仅 HTTP 关键字启发式
    ``include_vision``:
      - ``None``：按 ``AUTOPILOT_VISION_WHEN``（always / empty / fallback 在 resolve 侧仅 always|empty）
      - ``True`` / ``False``：强制附加或不附加视觉候选
    ``vision_enhanced``：Vision 升质（短边/detail/DOM full），供 runtime 失败重试。
    ``blocked_out``：回填被风险闸门拒掉的关键字 id。
    """

    ch = normalize_channel(channel)
    if ch == "http":
        return filter_safe_candidates(
            _http_candidates(action, target, value, text=text),
            blocked_out=blocked_out,
        )

    plat = (platform or "web").strip().lower()
    if plat in ("android", "ios"):
        cands = _mobile_candidates(action, target, value, platform=plat)
        default_resolver = "accessibility"
    else:
        cands = _web_candidates(action, target, value)
        default_resolver = "dom"
    for c in cands:
        if isinstance(c, dict) and not c.get("resolver"):
            c["resolver"] = "heuristic" if float(c.get("score") or 0) < 0.55 else default_resolver

    want_vision = include_vision
    if want_vision is None:
        try:
            from .config import vision_when  # 延迟：仅 Vision 回退
            from .vision import vision_enabled

            if not vision_enabled():
                want_vision = False
            else:
                mode = vision_when()
                if mode == "always":
                    want_vision = True
                elif mode == "empty":
                    want_vision = len(cands) == 0
                else:
                    want_vision = False
        except (ImportError, OSError, RuntimeError, TypeError, ValueError, AttributeError):
            want_vision = False

    if want_vision:
        try:
            from .vision import vision_candidates

            extra = vision_candidates(
                action=action,
                target=target,
                value=value,
                platform=plat,
                ctx=ctx,
                enhanced=vision_enhanced,
            )
            if extra:
                cands = list(cands) + list(extra)
        except (ImportError, OSError, RuntimeError, TypeError, ValueError, AttributeError):
            pass
    return filter_safe_candidates(cands, blocked_out=blocked_out)
