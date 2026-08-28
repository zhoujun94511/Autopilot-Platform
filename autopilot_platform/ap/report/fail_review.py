"""失败用例事后二审：只加注，不改步骤 PASS/FAIL。

默认启发式（不耗 token）。``AUTOPILOT_FAIL_REVIEW=off`` 关闭。
"""

from __future__ import annotations

import os
from typing import Any

from .fail_class import (
    ATTR_AGENT,
    ATTR_PRODUCT,
    ATTR_UNCERTAIN,
    attribution_label,
    classify_step,
)


def fail_review_mode() -> str:
    raw = (os.environ.get("AUTOPILOT_FAIL_REVIEW") or "heuristic").strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return "off"
    if raw in {"llm", "1", "true", "on", "yes"}:
        return "heuristic"
    return "heuristic"


def root_key(step: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(step.get("attribution") or "").strip(),
        str(step.get("fail_class") or "").strip(),
        str(step.get("fail_reason") or "").strip(),
    )


def unique_root_causes(fail_steps: list[dict[str, Any]]) -> list[dict[str, str]]:
    """同一用例内相同归因+分类+原因只保留一条。"""
    seen: set[tuple[str, str, str]] = set()
    out: list[dict[str, str]] = []
    for step in fail_steps:
        if not isinstance(step, dict):
            continue
        cls = classify_step(step) if not str(step.get("attribution") or "").strip() else {}
        attr = str(step.get("attribution") or cls.get("attribution") or "").strip()
        fc = str(step.get("fail_class") or cls.get("fail_class") or "").strip()
        reason = str(step.get("fail_reason") or "").strip()
        key = (attr, fc, reason)
        if not any(key) or key in seen:
            continue
        seen.add(key)
        out.append({
            "attribution": attr,
            "attribution_label": attribution_label(attr) if attr else "",
            "fail_class": fc,
            "fail_reason": reason,
        })
    return out


def _has_shot(step: dict[str, Any]) -> bool:
    return bool(
        str(step.get("screenshot_path") or "").strip()
        or str(step.get("screenshot_before_path") or "").strip()
        or str(step.get("screenshot") or "").strip()
    )


def review_failed_case(case: dict[str, Any]) -> dict[str, Any]:
    """给失败用例写 qa_review。通过用例返回空。不得改 case['status']。"""
    if fail_review_mode() == "off":
        return {}
    if str(case.get("status") or "").lower() not in {"failed", "fail", "error"}:
        return {}
    steps = [s for s in (case.get("steps") or []) if isinstance(s, dict)]
    fails = [s for s in steps if str(s.get("status") or "").lower() in {"fail", "failed", "error"}]
    issues: list[str] = []
    for step in fails:
        cls = classify_step(step)
        attr = str(cls.get("attribution") or step.get("attribution") or "")
        reason = str(step.get("fail_reason") or "")
        fc = str(cls.get("fail_class") or step.get("fail_class") or "")
        if reason == "app_crash" or (
            attr == ATTR_PRODUCT and "崩溃" in str(step.get("error_message") or "")
        ):
            issues.append("目标应用疑似崩溃，记为产品缺陷，不要当成定位失败")
        elif attr == ATTR_AGENT:
            issues.append("更像 Agent/定位偏差，不要记成产品缺陷")
        elif attr == ATTR_UNCERTAIN:
            issues.append("证据不足，无法判断产品还是执行偏差")
        elif (
            not _has_shot(step)
            and attr in {ATTR_AGENT, ATTR_PRODUCT}
            and fc == "locator"
        ):
            issues.append("缺少前后截图，证据不足")
    roots = unique_root_causes(fails)
    if not issues and roots:
        issues.append("按失败步归因汇总，未改用例结果")
    # 同根因去重：issues 也按原文去重
    uniq_issues: list[str] = []
    for text in issues:
        if text not in uniq_issues:
            uniq_issues.append(text)
    return {
        "source": "heuristic",
        "changed_status": False,
        "issue_count": len(uniq_issues),
        "issues": uniq_issues,
        "root_causes": roots,
    }
