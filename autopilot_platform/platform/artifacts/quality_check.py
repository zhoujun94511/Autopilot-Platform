"""逻辑用例质量 / 幻觉启发式检测（平台原生，不依赖 Flask TestPilot 模块）。"""

from __future__ import annotations

import re
from typing import Any


_VAGUE = [
    r"显示正常",
    r"体验流畅",
    r"结果合理",
    r"对应按钮",
    r"有效账号",
    r"确保数据一致",
    r"页面正常",
    r"按预期",
    r"众所周知",
    r"一般来说",
    r"通常情况下",
    r"根据研究表明",
    r"专家认为",
]

_LOW_LEVEL = [
    r"xpath\s*=",
    r"//XCUIElement",
    r"//android\.",
    r"mobile_element_",
    r"css_selector",
    r"driver\.",
    r"find_element",
    r"selenium",
    r"appium",
]


def assess_intent_steps(intent_steps: list[dict] | None) -> dict[str, Any]:
    """检查结构化意图的 action/target 完整性。"""
    issues: list[str] = []
    suggestions: list[str] = []
    flags: list[str] = []
    steps = [s for s in (intent_steps or []) if isinstance(s, dict)]
    if not steps:
        issues.append("缺少 intent_steps")
        suggestions.append("将逻辑步骤规范化为 action/target 结构")
        flags.append("missing_intent_steps")
        return {
            "engine": "intent_quality_v1",
            "score": 0.2,
            "risk": "high",
            "issues": issues,
            "suggestions": suggestions,
            "flags": flags,
        }

    allowed = {"click", "type", "assert", "swipe", "open", "wait", "custom"}
    weak = 0
    for i, s in enumerate(steps, start=1):
        action = str(s.get("action") or "").strip().lower()
        target = str(s.get("target") or "").strip()
        text = str(s.get("text") or "").strip()
        if action not in allowed:
            issues.append(f"步骤{i} action 非法: {action or '(空)'}")
            weak += 1
        if action in ("click", "type", "assert", "swipe", "open") and not target and not text:
            issues.append(f"步骤{i} 缺少 target/text")
            weak += 1
        if action == "type" and not str(s.get("value") or "").strip():
            issues.append(f"步骤{i} type 缺少 value")
            weak += 1
        if action == "custom":
            weak += 1
            flags.append("custom_intent")

    score = 1.0 - 0.12 * weak - (0.2 if "custom_intent" in flags and weak >= len(steps) // 2 else 0)
    score = max(0.0, min(1.0, score))
    risk = "low" if score >= 0.75 and not issues else ("high" if score < 0.45 else "medium")
    if weak:
        suggestions.append("尽量使用 click/type/assert/open 等明确动作，并补全 target")
    return {
        "engine": "intent_quality_v1",
        "score": round(score, 3),
        "risk": risk,
        "issues": issues,
        "suggestions": suggestions,
        "flags": list(dict.fromkeys(flags)),
        "intent_count": len(steps),
        "weak_count": weak,
    }


def assess_logical_case(
    *,
    title: str,
    logical_steps: list[str],
    expected_results: list[str],
    requirement_text: str = "",
    intent_steps: list[dict] | None = None,
) -> dict[str, Any]:
    issues: list[str] = []
    suggestions: list[str] = []
    flags: list[str] = []

    steps = [s for s in (logical_steps or []) if str(s).strip()]
    expected = [s for s in (expected_results or []) if str(s).strip()]
    blob = "\n".join([title or "", *steps, *expected])

    if not steps:
        issues.append("缺少可执行的逻辑步骤")
        suggestions.append("补充具体用户操作步骤")
    if not expected:
        issues.append("缺少可判定的预期结果")
        suggestions.append("将期望写成可观察断言")

    vague_hits = []
    for pat in _VAGUE:
        if re.search(pat, blob, flags=re.IGNORECASE):
            vague_hits.append(pat)
    if vague_hits:
        issues.append("存在模糊/不可判定表述")
        flags.append("vague_language")
        suggestions.append("把模糊词替换为可观测现象（文案、状态、接口码等）")

    low_hits = []
    for pat in _LOW_LEVEL:
        if re.search(pat, blob, flags=re.IGNORECASE):
            low_hits.append(pat)
    if low_hits:
        issues.append("疑似包含底层自动化定位/驱动细节")
        flags.append("low_level_automation")
        suggestions.append("逻辑用例应保持业务意图，定位器留给 AutoPilot IDE")

    # 与需求的粗粒度重叠（过低可能“自由发挥”）
    req = (requirement_text or "").strip()
    overlap_ratio = 0.0
    if req and blob:
        req_tokens = set(re.findall(r"[\w\u4e00-\u9fff]{2,}", req.lower()))
        case_tokens = set(re.findall(r"[\w\u4e00-\u9fff]{2,}", blob.lower()))
        if req_tokens and case_tokens:
            overlap_ratio = len(req_tokens & case_tokens) / max(1, len(case_tokens))
        if overlap_ratio < 0.05 and len(case_tokens) > 8:
            issues.append("用例用语与需求文本重合度偏低，可能存在推断成分")
            flags.append("low_requirement_overlap")
            suggestions.append("核对需求原文后再人工评审")

    # 简单评分：1.0 减去问题惩罚
    score = 1.0
    score -= 0.25 * len([i for i in issues if "缺少" in i])
    score -= 0.15 if "vague_language" in flags else 0
    score -= 0.35 if "low_level_automation" in flags else 0
    score -= 0.1 if "low_requirement_overlap" in flags else 0
    score = max(0.0, min(1.0, score))

    risk = "low"
    if score < 0.45 or "low_level_automation" in flags:
        risk = "high"
    elif score < 0.75 or issues:
        risk = "medium"

    result: dict[str, Any] = {
        "engine": "heuristic_quality_v1",
        "score": round(score, 3),
        "risk": risk,
        "is_suspicious": risk != "low",
        "issues": issues,
        "suggestions": suggestions,
        "flags": flags,
        "requirement_overlap": round(overlap_ratio, 3),
        "vague_patterns": vague_hits[:8],
        "note": "启发式质量检测，不能替代人工评审或事实验证",
    }
    if intent_steps:
        iq = assess_intent_steps(intent_steps)
        result["intent_quality"] = iq
        result["score"] = round(
            (float(result["score"]) + float(iq.get("score") or 0)) / 2, 3
        )
        result["issues"] = list(result["issues"]) + list(iq.get("issues") or [])
        result["suggestions"] = list(result["suggestions"]) + list(iq.get("suggestions") or [])
        result["flags"] = list(dict.fromkeys(list(result["flags"]) + list(iq.get("flags") or [])))
        if iq.get("risk") == "high" or result["score"] < 0.45:
            result["risk"] = "high"
        elif iq.get("risk") == "medium" and result["risk"] == "low":
            result["risk"] = "medium"
        result["is_suspicious"] = result["risk"] != "low"

    # 人审分桶：auto_approvable | needs_review | reject_suggest
    result["review_bucket"] = review_bucket_for_quality(result)
    return result


def review_bucket_for_quality(quality: dict[str, Any] | None) -> str:
    """根据质量结果给出审阅分桶。"""
    q = quality or {}
    score = float(q.get("score") or 0.0)
    risk = str(q.get("risk") or "").lower()
    flags = set(q.get("flags") or [])
    if risk == "high" or "low_level_automation" in flags or score < 0.45:
        return "reject_suggest"
    if risk == "low" and score >= 0.85 and "vague_language" not in flags:
        return "auto_approvable"
    return "needs_review"
