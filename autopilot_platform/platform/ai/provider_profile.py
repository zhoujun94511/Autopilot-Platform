"""多厂商模型 Profile：能力位 + 统一推理档位 → 各家请求字段。

不引入 LangChain：在现有 OpenAI 兼容 Chat Completions 上做薄映射。

统一档位：``none | minimal | low | medium | high | max``
（环境变量 ``AP_AI_REASONING_EFFORT``）。

verbosity（OpenAI gpt-5）：``none | low | medium | high``
（环境变量 ``AP_AI_VERBOSITY`` / ``AUTOPILOT_VISION_VERBOSITY``）。

官网对齐要点：
- DeepSeek：thinking + reasoning_effort∈{high,max}；low/medium→high，xhigh→max
- DeepSeek 识图：仅 vision 型号接受 image_url（https://api-docs.deepseek.com/zh-cn/guides/vision）
- OpenAI gpt-5：原样传 reasoning_effort（含 max）；非 reasoning 模型不传
- OpenAI gpt-5：可选 verbosity∈{low,medium,high}
- Gemini OpenAI 兼容：原样传 reasoning_effort∈{none,minimal,low,medium,high}
  （见 https://ai.google.dev/gemini-api/docs/openai ）；勿把 low 改写成 minimal
- Qwen：enable_thinking + thinking_budget（budget 为工程近似分档，非厂商固定表）
"""

from __future__ import annotations

from typing import Any, Literal

ReasoningEffort = Literal["none", "minimal", "low", "medium", "high", "max"]
Verbosity = Literal["none", "low", "medium", "high"]

DEFAULT_DEEPSEEK_VISION_MODEL = "deepseek-v4-flash-vision-exp"

_VALID_EFFORTS = frozenset({"none", "minimal", "low", "medium", "high", "max"})
_VALID_VERBOSITY = frozenset({"none", "low", "medium", "high"})

# model 子串 → 弃用提示（不静默 remap）
_MODEL_DEPRECATION: tuple[tuple[str, str], ...] = (
    ("deepseek-chat", "deepseek-v4-flash（非思考）"),
    ("deepseek-reasoner", "deepseek-v4-flash（思考）或 deepseek-v4-pro"),
    ("gpt-4o-mini", "gpt-5.4-mini / gpt-5-mini 或 gpt-5.6-terra"),
    ("gpt-4o", "gpt-5 / gpt-5.4 系列"),
    ("gemini-1.5", "gemini-3.5-flash / gemini-3.1-flash-lite"),
    ("gemini-2.0-flash", "gemini-3.5-flash"),
    ("gemini-2.5-flash", "gemini-3.5-flash（2.5 系列将退役）"),
)

# 千问 thinking_budget：工程近似（对齐 Gemini OpenAI 兼容表量级），非 DashScope 官方枚举
_QWEN_THINKING_BUDGET = {
    "minimal": 1024,
    "low": 1024,
    "medium": 8192,
    "high": 24576,
    "max": 32768,
}


def normalize_reasoning_effort(raw: str | None, *, default: str = "none") -> ReasoningEffort:
    s = (raw or default or "none").strip().lower()
    if s in ("off", "0", "false", "disabled", "disable"):
        return "none"
    if s in ("min",):
        return "minimal"
    if s in ("xhigh", "extra_high", "extra-high"):
        return "max"
    if s in _VALID_EFFORTS:
        return s  # type: ignore[return-value]
    if default and default != "none":
        return normalize_reasoning_effort(default, default="none")
    return "none"


def normalize_verbosity(raw: str | None, *, default: str = "none") -> Verbosity:
    """OpenAI gpt-5 verbosity：none=不传；low|medium|high。"""
    s = (raw or default or "none").strip().lower()
    if s in ("off", "0", "false", "disabled", "disable", "", "none"):
        return "none"
    if s in ("min", "minimal"):
        return "low"
    if s in ("max", "xhigh"):
        return "high"
    if s in _VALID_VERBOSITY:
        return s  # type: ignore[return-value]
    return "none"


def detect_provider(provider: str | None, model: str | None = None, base_url: str | None = None) -> str:
    pid = (provider or "").strip().lower()
    if pid in ("openai", "deepseek", "qwen", "gemini", "ollama"):
        return pid
    mid = (model or "").strip().lower()
    url = (base_url or "").strip().lower()
    if "deepseek" in url or mid.startswith("deepseek"):
        return "deepseek"
    if "dashscope" in url or mid.startswith("qwen"):
        return "qwen"
    if "generativelanguage.googleapis" in url or mid.startswith("gemini"):
        return "gemini"
    if "11434" in url:
        return "ollama"
    if "openai.com" in url or mid.startswith("gpt-") or mid.startswith("o1") or mid.startswith("o3"):
        return "openai"
    return pid or "openai"


def model_accepts_images(provider: str, model: str, *, base_url: str = "") -> bool:
    """当前模型/厂商是否应传 image_url（官方托管能力）。"""
    p = detect_provider(provider, model, base_url)
    m = (model or "").strip().lower()
    if p == "deepseek" or m.startswith("deepseek"):
        return bool(m) and "vision" in m
    if p == "ollama":
        return any(x in m for x in ("llava", "vision", "vl"))
    if p == "qwen":
        return "vl" in m or "vision" in m or "omni" in m
    if p == "gemini":
        return True
    if p == "openai":
        if "gpt-5" in m and "chat" in m:
            return False
        return True
    return False


def model_deprecation_hint(model: str) -> str:
    m = (model or "").strip()
    if not m:
        return ""
    low = m.lower()
    for needle, suggested in _MODEL_DEPRECATION:
        if low == needle or low.startswith(needle):
            return f"模型 {m} 已偏旧/临近弃用，建议改为 {suggested}"
    return ""


def openai_supports_reasoning_effort(model: str) -> bool:
    m = (model or "").strip().lower()
    if not m:
        return False
    if m.startswith(("o1", "o3", "o4")):
        return True
    if "gpt-5" in m:
        if "chat" in m:
            return False
        return True
    return False


def openai_supports_verbosity(model: str) -> bool:
    """gpt-5 系支持 verbosity（low/medium/high）。"""
    m = (model or "").strip().lower()
    return bool(m) and "gpt-5" in m


def apply_reasoning_to_body(
    body: dict[str, Any],
    *,
    provider: str,
    model: str,
    effort: str | None,
    base_url: str = "",
    deepseek_thinking_override: bool | None = None,
) -> dict[str, Any]:
    """就地写入厂商推理字段，返回同一 body。"""
    level = normalize_reasoning_effort(effort, default="none")
    p = detect_provider(provider, model, base_url)
    m = (model or "").strip()
    m_low = m.lower()

    if p == "deepseek":
        thinking_on = (
            bool(deepseek_thinking_override)
            if deepseek_thinking_override is not None
            else level != "none"
        )
        if thinking_on:
            body["thinking"] = {"type": "enabled"}
            # 官方：仅 high|max；兼容 low/medium/minimal→high，xhigh/max→max
            body["reasoning_effort"] = "max" if level == "max" else "high"
        else:
            body["thinking"] = {"type": "disabled"}
            body.pop("reasoning_effort", None)
        return body

    if p == "openai":
        if level != "none" and openai_supports_reasoning_effort(m):
            # 官方档位含 minimal/low/medium/high/xhigh/max；统一 max 直接传 max
            body["reasoning_effort"] = level
        else:
            body.pop("reasoning_effort", None)
        return body

    if p == "qwen":
        if level == "none":
            body["enable_thinking"] = False
            body.pop("thinking_budget", None)
        else:
            body["enable_thinking"] = True
            body["thinking_budget"] = _QWEN_THINKING_BUDGET.get(level, 8192)
        return body

    if p == "gemini":
        # OpenAI 兼容网关：reasoning_effort 原样映射官方表
        # minimal/low/medium/high；2.5 可用 none 关思考；3.x 不能完全关闭
        if level == "none":
            if "2.5" in m_low:
                body["reasoning_effort"] = "none"
            else:
                body.pop("reasoning_effort", None)
            return body
        # max 非 Gemini 官表 → high；其余（含 minimal/low）原样传递
        body["reasoning_effort"] = "high" if level == "max" else level
        return body

    return body


def apply_verbosity_to_body(
    body: dict[str, Any],
    *,
    provider: str,
    model: str,
    verbosity: str | None,
    base_url: str = "",
) -> dict[str, Any]:
    """就地写入 OpenAI gpt-5 verbosity；其他厂商忽略。"""
    level = normalize_verbosity(verbosity, default="none")
    p = detect_provider(provider, model, base_url)
    if p == "openai" and level != "none" and openai_supports_verbosity(model):
        body["verbosity"] = level
    else:
        body.pop("verbosity", None)
    return body


def uses_max_completion_tokens(model: str) -> bool:
    """OpenAI gpt-5 / o 系列拒收 max_tokens，须用 max_completion_tokens。"""
    m = (model or "").strip().lower()
    if not m:
        return False
    if "gpt-5" in m:
        return True
    if m.startswith(("o1", "o3", "o4")):
        return True
    return False


def apply_max_output_tokens(body: dict[str, Any], model: str, max_tokens: int) -> dict[str, Any]:
    """按模型写入 max_tokens 或 max_completion_tokens（互斥）。"""
    n = max(1, int(max_tokens))
    body.pop("max_tokens", None)
    body.pop("max_completion_tokens", None)
    if uses_max_completion_tokens(model):
        body["max_completion_tokens"] = n
    else:
        body["max_tokens"] = n
    return body


def should_omit_temperature(
    provider: str,
    model: str,
    *,
    thinking_enabled: bool = False,
) -> bool:
    """是否省略 temperature。

    - gpt-5 系：多数只接受默认 temperature
    - Gemini 3 / 2.5：官方建议勿改 temperature
    - DeepSeek thinking 开启：官方称 temperature 无效，请求中省略以免误导
    """
    m = (model or "").strip().lower()
    p = detect_provider(provider, model)
    if thinking_enabled and p == "deepseek":
        return True
    if "gpt-5" in m:
        return True
    if p == "gemini" and ("gemini-3" in m or "gemini-2.5" in m):
        return True
    return False
