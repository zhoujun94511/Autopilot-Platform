"""自愈失败归因：从异常文案归类，供人审 / result.json。"""

from __future__ import annotations

import re
from typing import Any


# 稳定枚举，写入 result / Binding / 人审表
FAIL_NO_CANDIDATE = "no_candidate"
FAIL_NOT_FOUND = "element_not_found"
FAIL_TIMEOUT = "timeout"
FAIL_WRONG_PAGE = "wrong_page"
FAIL_STALE = "stale_element"
FAIL_VERIFY = "verify_mismatch"
FAIL_LOOKS_LIKE_HTTP = "looks_like_http"
FAIL_UNKNOWN = "unknown"

# 像 HTTP/API 的意图（O9 归因；C1 起 channel=http/auto 可执行）
_HTTP_INTENT_RE = re.compile(
    r"\b(http|https|api|rest|graphql|rpc|endpoint|url)\b|"
    r"接口|请求|调用接口|发送请求|http\s*get|http\s*post|get\s+/|post\s+/|"
    r"json\s*path|jsonpath|status\s*code|响应体|响应码|"
    r"/api/|/v\d+/",
    re.IGNORECASE,
)


def looks_like_http_intent(*texts: str) -> bool:
    """意图文案是否更像 HTTP/API（供归因与后续 channel=http）。"""
    blob = " ".join(t for t in texts if t).strip()
    if not blob:
        return False
    return bool(_HTTP_INTENT_RE.search(blob))


def classify_intent_failure(
    errors: list[str] | None = None,
    *,
    message: str = "",
    had_candidates: bool = True,
    intent_text: str = "",
    channel: str = "",
) -> dict[str, Any]:
    """返回 {code, label, detail}。"""
    blob = " | ".join([*(errors or []), message or "", intent_text or ""]).lower()
    ch = (channel or "").strip().lower()
    if not had_candidates or "无法解析意图" in (message or "") or "no candidate" in blob:
        if ch == "http":
            return {
                "code": FAIL_NO_CANDIDATE,
                "label": "无候选",
                "detail": (
                    message
                    or "无法解析为 HTTP 请求（需 method + path/URL，或已有 HTTP Binding）"
                )[:240],
            }
        if looks_like_http_intent(message, intent_text, *(errors or [])):
            hint = "请设 channel=http|auto，或补充 HTTP Binding"
            base = (message or "").strip() or "意图更像 HTTP/API"
            return {
                "code": FAIL_LOOKS_LIKE_HTTP,
                "label": "像HTTP/API",
                "detail": f"{base}；{hint}"[:240],
            }
        return {
            "code": FAIL_NO_CANDIDATE,
            "label": "无候选",
            "detail": (message or "无可用解析候选")[:240],
        }

    if re.search(r"timeout|timed?\s*out|等待超时|implicitlywait", blob):
        return {"code": FAIL_TIMEOUT, "label": "超时", "detail": blob[:240]}

    if re.search(r"stale|obsolete|detached", blob):
        return {"code": FAIL_STALE, "label": "元素过期", "detail": blob[:240]}

    if re.search(
        r"wrong.?page|activity|package|当前页|不在.*页|session.*terminat",
        blob,
    ):
        return {"code": FAIL_WRONG_PAGE, "label": "页错/会话", "detail": blob[:240]}

    if re.search(r"校验.*失败|不符合预期|verify|assert.*fail|期望值", blob):
        # 存在性校验失败多半是文案变了或控件不在当前页
        if re.search(r"实际值是\[false].*期望值是\[true]|不存在|not found|nosuchelement", blob):
            return {
                "code": FAIL_NOT_FOUND,
                "label": "文案变/找不到",
                "detail": blob[:240],
            }
        return {"code": FAIL_VERIFY, "label": "断言不符", "detail": blob[:240]}

    if re.search(
        r"nosuchelement|no such element|未找到元素|element.*not.*found|unable to locate",
        blob,
    ):
        return {"code": FAIL_NOT_FOUND, "label": "文案变/找不到", "detail": blob[:240]}

    return {"code": FAIL_UNKNOWN, "label": "未知", "detail": blob[:240] or "执行失败"}
