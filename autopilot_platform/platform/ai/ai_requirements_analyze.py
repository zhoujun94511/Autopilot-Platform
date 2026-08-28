"""文档 → 需求/测试点/业务规则：LLM 分析（对齐 TestPilot）+ 启发式回退。"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from . import ai_config

log = logging.getLogger("autopilot_platform.platform.ai")

_REQ_PROMPT = """你是资深需求分析师。请从下面文档中提取结构化需求条目，最多 {max_items} 条。

硬性约束：
1. 只输出 JSON，不要 Markdown 代码围栏，不要解释。
2. type 只能是：functional | non-functional | business | technical
3. priority 只能是：P0 | P1 | P2 | P3
4. title 简洁；content 包含可验收描述。
5. {language_instruction}

JSON 结构：
{{
  "requirements": [
    {{
      "title": "需求标题",
      "content": "需求内容",
      "type": "functional",
      "priority": "P2"
    }}
  ]
}}

文档正文：
{document}
"""

_TEST_POINTS_PROMPT = """请从以下文档中提取测试点，包括功能、边界、异常等，最多 {max_items} 条。

硬性约束：
1. 只输出 JSON，不要 Markdown 代码围栏，不要解释。
2. type 只能是：functional | boundary | exception | performance
3. priority 只能是：P0 | P1 | P2 | P3
4. {language_instruction}

JSON 结构：
{{
  "test_points": [
    {{
      "name": "测试点名称",
      "description": "详细描述",
      "type": "functional",
      "priority": "P1"
    }}
  ]
}}

文档正文：
{document}
"""

_BUSINESS_RULES_PROMPT = """请从以下文档中提取业务规则，包括验证、计算、流程规则等，最多 {max_items} 条。

硬性约束：
1. 只输出 JSON，不要 Markdown 代码围栏，不要解释。
2. type 只能是：validation | calculation | workflow
3. priority 只能是：P0 | P1 | P2 | P3
4. 每条须含 condition（触发条件）
5. {language_instruction}

JSON 结构：
{{
  "business_rules": [
    {{
      "name": "规则名称",
      "description": "规则描述",
      "type": "validation",
      "condition": "触发条件",
      "priority": "P2"
    }}
  ]
}}

文档正文：
{document}
"""


def _infer_language_instruction(text: str) -> str:
    zh = sum(1 for ch in (text or "") if "\u4e00" <= ch <= "\u9fff")
    en = sum(1 for ch in (text or "") if ("a" <= ch.lower() <= "z"))
    if zh > en:
        return "请使用简体中文输出字段内容。"
    if en > zh:
        return "Please output field contents in English."
    return "请跟随输入文本主体语言输出字段内容。"


def _strip_fence(text: str) -> str:
    s = (text or "").strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.IGNORECASE)
        s = re.sub(r"\s*```$", "", s)
    return s.strip()


def _norm_priority(raw: Any) -> str:
    key = str(raw or "P2").strip().upper()
    if key in {"P0", "P1", "P2", "P3"}:
        return key
    mapping = {"HIGH": "P1", "MEDIUM": "P2", "LOW": "P3", "CRITICAL": "P0"}
    return mapping.get(key, "P2")


def _parse_json_object(content: str) -> dict[str, Any]:
    raw = _strip_fence(str(content))
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*}", raw)
        if not m:
            raise ValueError(f"无法解析模型 JSON: {raw[:400]}")
        payload = json.loads(m.group(0))
    if not isinstance(payload, dict):
        raise ValueError("模型返回非对象 JSON")
    return payload


def _llm_json(prompt: str) -> dict[str, Any]:
    if not ai_config.ai_enabled():
        raise RuntimeError("AI API Key 未配置")
    from .ai_client import chat_completions

    content = chat_completions(
        [
            {"role": "system", "content": "你只输出合法 JSON 对象。"},
            {"role": "user", "content": prompt},
        ]
    )
    return _parse_json_object(str(content))


def analyze_document_to_requirement_drafts(
    document_text: str,
    *,
    max_requirements: int = 20,
) -> list[dict[str, str]]:
    """调用 LLM 抽取需求；失败抛异常由上层回退启发式。"""
    doc = (document_text or "").strip()[:20000]
    if not doc:
        raise ValueError("文档内容为空")
    cap = max(1, min(int(max_requirements), 100))
    prompt = _REQ_PROMPT.format(
        max_items=cap,
        language_instruction=_infer_language_instruction(doc),
        document=doc,
    )
    payload = _llm_json(prompt)
    rows = payload.get("requirements")
    if not isinstance(rows, list) or not rows:
        raise ValueError("模型未返回 requirements 数组")

    out: list[dict[str, str]] = []
    for entry in rows[:cap]:
        if not isinstance(entry, dict):
            continue
        title = str(entry.get("title") or "").strip()
        body = str(entry.get("content") or entry.get("text") or "").strip()
        if not title or not body:
            continue
        out.append(
            {
                "title": title[:200],
                "content": body[:20000],
                "req_type": str(entry.get("type") or entry.get("req_type") or "functional"),
                "priority": _norm_priority(entry.get("priority")),
            }
        )
    if not out:
        raise ValueError("模型未产出有效需求")
    log.info(
        "llm extracted %s requirements via %s/%s",
        len(out),
        ai_config.ai_provider(),
        ai_config.ai_model(),
    )
    return out


def analyze_document_to_test_point_drafts(
    document_text: str,
    *,
    max_items: int = 20,
) -> list[dict[str, str]]:
    doc = (document_text or "").strip()[:20000]
    if not doc:
        raise ValueError("文档内容为空")
    cap = max(1, min(int(max_items), 20))
    prompt = _TEST_POINTS_PROMPT.format(
        max_items=cap,
        language_instruction=_infer_language_instruction(doc),
        document=doc,
    )
    payload = _llm_json(prompt)
    rows = payload.get("test_points")
    if not isinstance(rows, list) or not rows:
        raise ValueError("模型未返回 test_points 数组")
    out: list[dict[str, str]] = []
    for i, entry in enumerate(rows[:cap]):
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or entry.get("title") or "").strip()
        desc = str(entry.get("description") or entry.get("content") or "").strip()
        if not name:
            continue
        out.append(
            {
                "name": name[:200],
                "description": (desc or name)[:8000],
                "type": str(entry.get("type") or "functional")[:64],
                "priority": _norm_priority(entry.get("priority")),
                "id": f"TP_{i + 1:03d}",
            }
        )
    if not out:
        raise ValueError("模型未产出有效测试点")
    return out


def analyze_document_to_business_rule_drafts(
    document_text: str,
    *,
    max_items: int = 20,
) -> list[dict[str, str]]:
    doc = (document_text or "").strip()[:20000]
    if not doc:
        raise ValueError("文档内容为空")
    cap = max(1, min(int(max_items), 20))
    prompt = _BUSINESS_RULES_PROMPT.format(
        max_items=cap,
        language_instruction=_infer_language_instruction(doc),
        document=doc,
    )
    payload = _llm_json(prompt)
    rows = payload.get("business_rules")
    if not isinstance(rows, list) or not rows:
        raise ValueError("模型未返回 business_rules 数组")
    out: list[dict[str, str]] = []
    for i, entry in enumerate(rows[:cap]):
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or entry.get("title") or "").strip()
        desc = str(entry.get("description") or entry.get("content") or "").strip()
        if not name:
            continue
        out.append(
            {
                "name": name[:200],
                "description": (desc or name)[:8000],
                "type": str(entry.get("type") or "validation")[:64],
                "condition": str(entry.get("condition") or "")[:2000],
                "priority": _norm_priority(entry.get("priority")),
                "id": f"BR_{i + 1:03d}",
            }
        )
    if not out:
        raise ValueError("模型未产出有效业务规则")
    return out
