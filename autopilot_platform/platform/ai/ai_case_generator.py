"""逻辑用例 LLM 生成（OpenAI 兼容 Chat Completions；无 Key 时返回空由调用方回退）。"""

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any

from . import ai_config
from ..design.design_schemas import LogicalCaseCreate

log = logging.getLogger("autopilot_platform.platform.ai")

_CASE_PROMPT = """你是资深测试设计专家。根据需求生成最多 {max_cases} 条**意图测试用例**。

硬性约束：
1. 输出业务意图步骤，禁止 Appium/Selenium/xpath/css/keyword/locator。
2. 每条用例必须同时给出 logical_steps（自然语言展示）与 intent_steps（结构化可执行意图）。
3. intent_steps.action 只能是：click|type|assert|swipe|open|wait|custom。
4. type 必须带 value；click/assert/open 尽量带 target。
5. 覆盖正常、异常、边界中至少两类（若需求允许）。
6. 严格输出 JSON，不要 Markdown 代码围栏，不要解释文字。

JSON 结构：
{{
  "cases": [
    {{
      "case_key": "TC-模块-序号",
      "module": "功能模块",
      "title": "用例标题",
      "preconditions": ["前置1"],
      "logical_steps": ["点击登录按钮", "输入用户名：admin"],
      "intent_steps": [
        {{"id": "s1", "action": "click", "target": "登录按钮", "value": "", "platform_hint": "any", "text": "点击登录按钮"}},
        {{"id": "s2", "action": "type", "target": "用户名", "value": "admin", "platform_hint": "any", "text": "输入用户名：admin"}}
      ],
      "expected_results": ["期望1"],
      "priority": "P0|P1|P2|P3|P4",
      "test_type": "功能|异常|边界|兼容",
      "tags": ["标签"],
      "automatability": "AUTOMATABLE|PARTIAL|MANUAL_ONLY|NEEDS_DESIGN"
    }}
  ]
}}

需求正文：
{requirement}
"""


def _strip_fence(text: str) -> str:
    s = (text or "").strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.IGNORECASE)
        s = re.sub(r"\s*```$", "", s)
    return s.strip()


def _as_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if "\n" in text:
            return [ln.strip(" -\t") for ln in text.splitlines() if ln.strip()]
        return [text]
    return [str(value)]


def _normalize_priority(raw: Any) -> str:
    s = str(raw or "P2").strip().upper()
    if s in {"P0", "P1", "P2", "P3", "P4"}:
        return s
    mapping = {"HIGH": "P1", "MEDIUM": "P2", "LOW": "P3"}
    return mapping.get(s, "P2")


def _normalize_auto(raw: Any) -> str:
    s = str(raw or "UNKNOWN").strip().upper()
    allowed = {"AUTOMATABLE", "PARTIAL", "MANUAL_ONLY", "NEEDS_DESIGN", "UNKNOWN"}
    return s if s in allowed else "NEEDS_DESIGN"


def _parse_intent_steps(raw: Any, logical_steps: list[str], expected: list[str]) -> list:
    from ..design.design_schemas import IntentStep
    from ..design.intent_normalize import texts_to_intent_steps

    if isinstance(raw, list) and raw:
        out = []
        for i, item in enumerate(raw, start=1):
            if not isinstance(item, dict):
                continue
            out.append(
                IntentStep(
                    id=str(item.get("id") or f"s{i}"),
                    action=str(item.get("action") or "custom").strip().lower() or "custom",
                    target=str(item.get("target") or ""),
                    value=str(item.get("value") or ""),
                    platform_hint=str(item.get("platform_hint") or "any"),
                    text=str(item.get("text") or item.get("target") or ""),
                )
            )
        if out:
            return out
    return [
        IntentStep(**s) if isinstance(s, dict) else s
        for s in texts_to_intent_steps(logical_steps, expected)
    ]


def _parse_cases_payload(payload: dict[str, Any], *, module: str) -> list[LogicalCaseCreate]:
    rows = payload.get("cases") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise ValueError("模型返回缺少 cases 数组")
    out: list[LogicalCaseCreate] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        steps = _as_str_list(item.get("logical_steps") or item.get("steps"))
        expected = _as_str_list(item.get("expected_results") or item.get("expected"))
        intents = _parse_intent_steps(item.get("intent_steps"), steps, expected)
        if not title or (not steps and not intents):
            continue
        if not steps and intents:
            steps = [str(getattr(s, "text", None) or getattr(s, "target", "") or "") for s in intents]
        pre = item.get("preconditions")
        if isinstance(pre, str):
            preconditions = _as_str_list(pre)
        else:
            preconditions = _as_str_list(pre)
        out.append(
            LogicalCaseCreate(
                project_id="",
                title=title,
                case_key=str(item.get("case_key") or item.get("case_id") or f"TC-{uuid.uuid4().hex[:8]}"),
                description=str(item.get("description") or ""),
                preconditions=preconditions,
                logical_steps=steps,
                intent_steps=intents,
                expected_results=expected,
                priority=_normalize_priority(item.get("priority")),
                tags=_as_str_list(item.get("tags")),
                test_type=str(item.get("test_type") or ""),
                module=str(item.get("module") or module or ""),
                review_status="AI_DRAFT",
                automatability=_normalize_auto(item.get("automatability")),  # type: ignore[arg-type]
                generation_metadata={
                    "generator": "llm_v1",
                    "provider": ai_config.ai_provider(),
                    "model": ai_config.ai_model(),
                },
            )
        )
    if not out:
        raise ValueError("模型未产出有效逻辑用例")
    return out


def generate_logical_case_drafts(
    requirement_text: str,
    *,
    max_cases: int = 8,
    module: str = "",
    rag_context: str = "",
) -> list[LogicalCaseCreate]:
    """调用 OpenAI 兼容接口；失败抛异常由上层回退启发式。"""
    if not ai_config.ai_enabled():
        raise RuntimeError("AI API Key 未配置")

    from .ai_client import chat_completions

    req = (requirement_text or "").strip()[:12000]
    if (rag_context or "").strip():
        req = f"{req}\n\n----\n{rag_context.strip()[:8000]}"

    prompt = _CASE_PROMPT.format(
        max_cases=max(1, min(int(max_cases), 50)),
        requirement=req,
    )
    content = chat_completions(
        [
            {"role": "system", "content": "你只输出合法 JSON 对象。"},
            {"role": "user", "content": prompt},
        ]
    )

    raw = _strip_fence(str(content))
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        # 尝试截取第一个 JSON 对象
        m = re.search(r"\{[\s\S]*}", raw)
        if not m:
            raise ValueError(f"无法解析模型 JSON: {raw[:400]}") from exc
        payload = json.loads(m.group(0))

    drafts = _parse_cases_payload(payload, module=module)
    log.info(
        "llm generated %s logical cases via %s/%s",
        len(drafts),
        ai_config.ai_provider(),
        ai_config.ai_model(),
    )
    return drafts
