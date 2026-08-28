"""失败分类 + 归因：fail_class 回答「怎么死」，attribution 回答「谁背锅」。"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

CLASS_ASSERTION = "assertion"
CLASS_TIMEOUT = "timeout"
CLASS_ENVIRONMENT = "environment"
CLASS_LOCATOR = "locator"
CLASS_OTHER = "other"

FAIL_CLASS_LABELS: dict[str, str] = {
    CLASS_ASSERTION: "断言",
    CLASS_TIMEOUT: "超时",
    CLASS_ENVIRONMENT: "环境",
    CLASS_LOCATOR: "定位",
    CLASS_OTHER: "其他",
}

# Intent / 关键字已写入的 fail_reason → 粗分类
_REASON_TO_CLASS: dict[str, str] = {
    "element_not_found": CLASS_LOCATOR,
    "no_candidate": CLASS_LOCATOR,
    "stale_element": CLASS_LOCATOR,
    "wrong_page": CLASS_LOCATOR,
    "timeout": CLASS_TIMEOUT,
    "verify_mismatch": CLASS_ASSERTION,
    "app_crash": CLASS_OTHER,
    "evidence_missing": CLASS_OTHER,
}

_ASSERT_KW_RE = re.compile(
    r"(assert|verify|check_exist|check_text|check_equals)",
    re.IGNORECASE,
)
_TIMEOUT_RE = re.compile(
    r"timeout|timed?\s*out|等待超时|implicitlywait|readtimeout|connecttimeout",
    re.IGNORECASE,
)
_ENV_RE = re.compile(
    r"connection\s*refused|name or service not known|nodename nor servname|"
    r"api_env|profile|找不到\s*(yaml|profile|环境)|"
    r"ssl|certificate|proxy|dns|"
    r"device\s*(not|offline)|设备|appium|session not created|"
    r"failed to establish|max retries|network is unreachable",
    re.IGNORECASE,
)
_LOCATOR_RE = re.compile(
    r"element\s*not\s*found|no such element|unable to locate|"
    r"stale|xpath|locator|定位|找不到元素|no_candidate|no candidate",
    re.IGNORECASE,
)
ATTR_PRODUCT = "product_bug"
ATTR_ENV = "env_issue"
ATTR_AGENT = "inner_agent_bug"
ATTR_TOOLING = "tooling_gap"
ATTR_UNCERTAIN = "uncertain"

ATTRIBUTION_LABELS: dict[str, str] = {
    ATTR_PRODUCT: "产品缺陷",
    ATTR_ENV: "环境问题",
    ATTR_AGENT: "Agent/定位",
    ATTR_TOOLING: "工具链",
    ATTR_UNCERTAIN: "证据不足",
}

_AGENT_REASONS = frozenset({
    "no_candidate",
    "wrong_page",
    "stale_element",
})
_AGENT_STRATEGIES = frozenset({
    "vision",
    "heal",
    "heuristic",
    "failed",
})
_AGENT_HITS = frozenset({
    "failed",
    "rolled_back",
    "healed",
})

_ASSERT_MSG_RE = re.compile(
    r"断言|assert|expected|期望|mismatch|不等于|!=|不匹配|status\s*code",
    re.IGNORECASE,
)


def fail_class_label(code: str) -> str:
    return FAIL_CLASS_LABELS.get((code or "").strip(), "") or (code or "")


def attribution_label(code: str) -> str:
    return ATTRIBUTION_LABELS.get((code or "").strip(), "") or (code or "")


def classify_attribution(
    *,
    fail_class: str = "",
    fail_reason: str = "",
    resolve_strategy: str = "",
    binding_hit: str = "",
    heal_applied: bool = False,
    keyword_id: str = "",
    message: str = "",
    status: str = "",
    attribution: str = "",
) -> dict[str, str]:
    """返回 {attribution, attribution_label}。非 FAIL 或已有合法归因则沿用。"""
    st = str(status or "").strip().upper()
    if st and st not in ("FAIL", "FAILED", "ERROR"):
        return {"attribution": "", "attribution_label": ""}

    existing = str(attribution or "").strip()
    if existing in ATTRIBUTION_LABELS:
        return {"attribution": existing, "attribution_label": attribution_label(existing)}

    fc = str(fail_class or "").strip()
    reason = str(fail_reason or "").strip().lower()
    strategy = str(resolve_strategy or "").strip().lower()
    hit = str(binding_hit or "").strip().lower()
    blob = f"{keyword_id or ''} {message or ''}"

    if reason == "app_crash" or "疑似崩溃" in (message or ""):
        code = ATTR_PRODUCT
    elif reason in {"evidence_missing", "uncertain"} or "证据不足" in (message or ""):
        code = ATTR_UNCERTAIN
    elif fc == CLASS_ENVIRONMENT:
        code = ATTR_ENV
    elif fc == CLASS_TIMEOUT:
        code = ATTR_ENV
    elif fc == CLASS_ASSERTION:
        code = ATTR_PRODUCT
    elif fc == CLASS_LOCATOR:
        if (
            heal_applied
            or strategy in _AGENT_STRATEGIES
            or reason in _AGENT_REASONS
            or hit in _AGENT_HITS
        ):
            code = ATTR_AGENT
        elif hit in {"cache", "resolved"} and reason == "element_not_found":
            # Binding 曾经有效，元素消失：更像产品改版，而不是首次没点准
            code = ATTR_PRODUCT
        else:
            code = ATTR_AGENT
    elif fc == CLASS_OTHER and _ENV_RE.search(blob):
        code = ATTR_ENV
    elif fc == CLASS_OTHER:
        code = ATTR_TOOLING
    elif not fc and _ENV_RE.search(blob):
        code = ATTR_ENV
    elif not st and not reason and not (message or "").strip() and not fc:
        return {"attribution": "", "attribution_label": ""}
    else:
        code = ATTR_TOOLING
    return {"attribution": code, "attribution_label": attribution_label(code)}


def classify_failure(
    *,
    keyword_id: str = "",
    fail_reason: str = "",
    message: str = "",
    status: str = "",
) -> dict[str, str]:
    """返回 {fail_class, fail_class_label}。非 FAIL 返回空。"""
    st = str(status or "").strip().upper()
    if st and st not in ("FAIL", "FAILED", "ERROR"):
        return {"fail_class": "", "fail_class_label": ""}

    reason = str(fail_reason or "").strip().lower()
    if reason in _REASON_TO_CLASS:
        code = _REASON_TO_CLASS[reason]
        return {"fail_class": code, "fail_class_label": fail_class_label(code)}

    kid = str(keyword_id or "")
    blob = f"{kid} {message or ''}"

    if _TIMEOUT_RE.search(blob) or reason == "timeout":
        return {
            "fail_class": CLASS_TIMEOUT,
            "fail_class_label": FAIL_CLASS_LABELS[CLASS_TIMEOUT],
        }
    if _ASSERT_KW_RE.search(kid) or _ASSERT_MSG_RE.search(message or ""):
        return {
            "fail_class": CLASS_ASSERTION,
            "fail_class_label": FAIL_CLASS_LABELS[CLASS_ASSERTION],
        }
    if _ENV_RE.search(blob):
        return {
            "fail_class": CLASS_ENVIRONMENT,
            "fail_class_label": FAIL_CLASS_LABELS[CLASS_ENVIRONMENT],
        }
    if _LOCATOR_RE.search(blob):
        return {
            "fail_class": CLASS_LOCATOR,
            "fail_class_label": FAIL_CLASS_LABELS[CLASS_LOCATOR],
        }
    if not st and not reason and not (message or "").strip():
        return {"fail_class": "", "fail_class_label": ""}
    return {
        "fail_class": CLASS_OTHER,
        "fail_class_label": FAIL_CLASS_LABELS[CLASS_OTHER],
    }


def _attribution_from_source(sr: Any, fail_class: str) -> dict[str, str]:
    if isinstance(sr, dict):
        return classify_attribution(
            fail_class=fail_class or str(sr.get("fail_class") or ""),
            fail_reason=str(sr.get("fail_reason") or ""),
            resolve_strategy=str(sr.get("resolve_strategy") or ""),
            binding_hit=str(sr.get("binding_hit") or ""),
            heal_applied=bool(sr.get("heal_applied")),
            keyword_id=str(sr.get("keyword_id") or sr.get("resolved_keyword_id") or ""),
            message=str(sr.get("message") or sr.get("error_message") or ""),
            status=str(sr.get("status") or ""),
            attribution=str(sr.get("attribution") or ""),
        )
    return classify_attribution(
        fail_class=fail_class or str(getattr(sr, "fail_class", "") or ""),
        fail_reason=str(getattr(sr, "fail_reason", "") or ""),
        resolve_strategy=str(getattr(sr, "resolve_strategy", "") or ""),
        binding_hit=str(getattr(sr, "binding_hit", "") or ""),
        heal_applied=bool(getattr(sr, "heal_applied", False)),
        keyword_id=str(
            getattr(sr, "keyword_id", "") or getattr(sr, "resolved_keyword_id", "") or ""
        ),
        message=str(getattr(sr, "message", "") or ""),
        status=str(getattr(sr, "status", "") or ""),
        attribution=str(getattr(sr, "attribution", "") or ""),
    )


def classify_step(sr: Any) -> dict[str, str]:
    """从 StepResult / dict 归类；已有 fail_class / attribution 则沿用。"""
    if isinstance(sr, dict):
        existing = str(sr.get("fail_class") or "").strip()
        if existing:
            label = str(sr.get("fail_class_label") or "").strip() or fail_class_label(
                existing
            )
            out = {"fail_class": existing, "fail_class_label": label}
        else:
            out = classify_failure(
                keyword_id=str(sr.get("keyword_id") or sr.get("resolved_keyword_id") or ""),
                fail_reason=str(sr.get("fail_reason") or ""),
                message=str(sr.get("message") or sr.get("error_message") or ""),
                status=str(sr.get("status") or ""),
            )
        out.update(_attribution_from_source(sr, out.get("fail_class") or ""))
        return out
    existing = str(getattr(sr, "fail_class", "") or "").strip()
    if existing:
        label = str(getattr(sr, "fail_class_label", "") or "").strip() or fail_class_label(
            existing
        )
        out = {"fail_class": existing, "fail_class_label": label}
    else:
        out = classify_failure(
            keyword_id=str(
                getattr(sr, "keyword_id", "") or getattr(sr, "resolved_keyword_id", "") or ""
            ),
            fail_reason=str(getattr(sr, "fail_reason", "") or ""),
            message=str(getattr(sr, "message", "") or ""),
            status=str(getattr(sr, "status", "") or ""),
        )
    out.update(_attribution_from_source(sr, out.get("fail_class") or ""))
    return out


def scan_fail_classes(payload: dict[str, Any], counter: Counter[str]) -> None:
    """扫描失败步的 fail_class（断言/超时/环境/定位）。"""
    cases = payload.get("cases") if isinstance(payload.get("cases"), list) else []
    for case in cases:
        if not isinstance(case, dict):
            continue
        steps = case.get("steps") if isinstance(case.get("steps"), list) else []
        for step in steps:
            if not isinstance(step, dict):
                continue
            st = str(step.get("status") or step.get("result") or "").lower()
            if st not in ("fail", "failed", "error"):
                continue
            fc = str(step.get("fail_class") or case.get("fail_class") or "").strip()
            if fc:
                counter[fc] += 1


def scan_attributions(payload: dict[str, Any], counter: Counter[str]) -> None:
    """扫描失败步归因；同一用例内相同根因只计一次。"""
    cases = payload.get("cases") if isinstance(payload.get("cases"), list) else []
    for case in cases:
        if not isinstance(case, dict):
            continue
        steps = case.get("steps") if isinstance(case.get("steps"), list) else []
        seen: set[tuple[str, str, str]] = set()
        for step in steps:
            if not isinstance(step, dict):
                continue
            st = str(step.get("status") or step.get("result") or "").lower()
            if st not in ("fail", "failed", "error"):
                continue
            attr = str(step.get("attribution") or case.get("attribution") or "").strip()
            if not attr:
                attr = str(
                    classify_attribution(
                        fail_class=str(step.get("fail_class") or case.get("fail_class") or ""),
                        fail_reason=str(step.get("fail_reason") or ""),
                        resolve_strategy=str(step.get("resolve_strategy") or ""),
                        binding_hit=str(step.get("binding_hit") or ""),
                        heal_applied=bool(step.get("heal_applied")),
                        keyword_id=str(step.get("keyword_id") or ""),
                        message=str(step.get("error_message") or step.get("message") or ""),
                        status="FAIL",
                    ).get("attribution")
                    or ""
                )
            if not attr:
                continue
            key = (
                attr,
                str(step.get("fail_class") or case.get("fail_class") or "").strip(),
                str(step.get("fail_reason") or "").strip(),
            )
            if key in seen:
                continue
            seen.add(key)
            counter[attr] += 1
