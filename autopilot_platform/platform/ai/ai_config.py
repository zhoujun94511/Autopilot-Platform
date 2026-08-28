"""设计域 AI 配置（环境变量 + 运行时覆盖；运行时优先）。

Provider 走 OpenAI 兼容 Chat Completions。对齐官方文档：
- DeepSeek：https://api-docs.deepseek.com/zh-cn/
- Gemini：Google OpenAI 兼容网关 ``…/v1beta/openai``

各厂商默认 Base URL / 推荐模型以本模块 ``AI_PROVIDERS`` 为单一事实来源
（运维配置中心、Chat 选项、文档应与此对齐）。
"""

from __future__ import annotations

import os
from typing import Any


def _cfg(key: str, default: str = "") -> str:
    try:
        from ..ops.runtime_config import cfg_str

        return cfg_str(key, default)
    except (ImportError, OSError, KeyError, TypeError, ValueError, AttributeError):
        return (os.environ.get(key) or default).strip()


def _truthy(raw: str) -> bool:
    return (raw or "").strip().lower() in ("1", "true", "yes", "on")


# 运维配置中心 / Chat 推荐模型目录（default_* 与下方 ai_base_url / ai_model 回落一致）
# accepts_images：设计域 Chat 文本为主；Intent Vision 另选 VL 模型
AI_PROVIDERS: tuple[dict[str, Any], ...] = (
    {
        "id": "openai",
        "label": "OpenAI",
        "default_base_url": "https://api.openai.com/v1",
        "default_model": "gpt-5.4-mini",
        "models": [
            "gpt-5.4-mini",
            "gpt-5.4",
            "gpt-5.6-terra",
            "gpt-5-mini",
            "gpt-5",
            "gpt-4.1-mini",
            "gpt-4o-mini",  # legacy
        ],
        "accepts_images": True,
        "vision_models": ["gpt-5.4-mini", "gpt-5-mini", "gpt-5", "gpt-4o-mini"],
    },
    {
        "id": "deepseek",
        "label": "DeepSeek",
        "default_base_url": "https://api.deepseek.com",
        "default_model": "deepseek-v4-flash",
        "models": [
            "deepseek-v4-flash",
            "deepseek-v4-pro",
            "deepseek-v4-flash-vision-exp",
            "deepseek-chat",  # legacy → 2026/07/24
            "deepseek-reasoner",  # legacy
        ],
        "accepts_images": False,  # Chat 默认文本；识图见 vision_models
        "vision_models": ["deepseek-v4-flash-vision-exp"],
    },
    {
        "id": "qwen",
        "label": "通义千问 (Qwen)",
        "default_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "default_model": "qwen-plus",
        "models": [
            "qwen-plus",
            "qwen-flash",
            "qwen-max",
            "qwen3.7-plus",
            "qwen-vl-plus",
            "qwen3-vl-plus",
        ],
        "accepts_images": False,  # 默认文本；VL 模型见 vision_models
        "vision_models": ["qwen-vl-plus", "qwen3-vl-plus"],
    },
    {
        "id": "gemini",
        "label": "Gemini",
        "default_base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "default_model": "gemini-3.5-flash",
        "models": [
            "gemini-3.5-flash",
            "gemini-3.1-flash-lite",
            "gemini-2.5-flash",  # legacy / 临近退役
            "gemini-2.0-flash",
        ],
        "accepts_images": True,
        "vision_models": [
            "gemini-3.5-flash",
            "gemini-3.1-flash-lite",
            "gemini-2.5-flash",
        ],
    },
    {
        "id": "ollama",
        "label": "Ollama（本地）",
        "default_base_url": "http://127.0.0.1:11434/v1",
        "default_model": "llama3.2",
        "models": ["llama3.2", "phi:2.7b", "gemma:2b", "llava"],
        "accepts_images": False,
        "vision_models": ["llava"],
    },
)

_PROVIDER_BY_ID: dict[str, dict[str, Any]] = {str(p["id"]): p for p in AI_PROVIDERS}


def list_ai_providers() -> list[dict[str, Any]]:
    """返回各 Provider 目录副本（供配置中心 / API）。"""
    out: list[dict[str, Any]] = []
    for p in AI_PROVIDERS:
        out.append(
            {
                "id": str(p["id"]),
                "label": str(p["label"]),
                "default_base_url": str(p["default_base_url"]),
                "default_model": str(p["default_model"]),
                "models": list(p.get("models") or []),
                "accepts_images": bool(p.get("accepts_images")),
                "vision_models": list(p.get("vision_models") or []),
            }
        )
    return out


def provider_catalog_entry(provider: str | None = None) -> dict[str, Any] | None:
    pid = (provider or ai_provider()).strip().lower()
    entry = _PROVIDER_BY_ID.get(pid)
    if not entry:
        return None
    return {
        "id": str(entry["id"]),
        "label": str(entry["label"]),
        "default_base_url": str(entry["default_base_url"]),
        "default_model": str(entry["default_model"]),
        "models": list(entry.get("models") or []),
        "accepts_images": bool(entry.get("accepts_images")),
        "vision_models": list(entry.get("vision_models") or []),
    }


def provider_default_base_url(provider: str) -> str:
    entry = _PROVIDER_BY_ID.get((provider or "").strip().lower())
    return str(entry["default_base_url"]) if entry else str(_PROVIDER_BY_ID["openai"]["default_base_url"])


def provider_default_model(provider: str) -> str:
    entry = _PROVIDER_BY_ID.get((provider or "").strip().lower())
    return str(entry["default_model"]) if entry else str(_PROVIDER_BY_ID["openai"]["default_model"])


def provider_recommended_models(provider: str) -> list[str]:
    entry = _PROVIDER_BY_ID.get((provider or "").strip().lower())
    return list(entry.get("models") or []) if entry else []


def known_default_base_urls() -> set[str]:
    return {str(p["default_base_url"]).rstrip("/") for p in AI_PROVIDERS}


def known_default_models() -> set[str]:
    return {str(p["default_model"]) for p in AI_PROVIDERS}


def ai_enabled() -> bool:
    # Ollama 本地常无 Key；其它厂商仍要求 Key（与 Chat fail-closed 对齐）
    if ai_provider() == "ollama":
        return True
    return bool(ai_api_key())


def ai_reject_degraded() -> bool:
    """为 True 时 LLM 失败不回落启发式（默认关，避免打断现网）。

    环境变量 / 运维配置：``AP_AI_REJECT_DEGRADED=1``。
    """
    return _truthy(_cfg("AP_AI_REJECT_DEGRADED", "0"))


def ai_provider() -> str:
    return (
        _cfg("AP_AI_PROVIDER")
        or _cfg("MC_AI_PROVIDER")
        or "openai"
    ).strip().lower() or "openai"


def ai_api_key() -> str:
    """按当前 Provider 优先取分厂商 Key，再回退通用 Key。"""
    provider = ai_provider()
    vendor_keys = {
        "openai": ("OPENAI_API_KEY",),
        "deepseek": ("DEEPSEEK_API_KEY",),
        "qwen": ("DASHSCOPE_API_KEY", "QWEN_API_KEY"),
        "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
        "ollama": ("OLLAMA_API_KEY",),
    }
    for key in ("AP_AI_API_KEY", "MC_AI_API_KEY"):
        val = _cfg(key)
        if val:
            return val
    for key in vendor_keys.get(provider, ()):
        val = (os.environ.get(key) or "").strip()
        if val:
            return val
    # 最后兜底扫一遍常见 Key，避免换 provider 后忘改通用 Key
    for key in (
        "OPENAI_API_KEY",
        "DEEPSEEK_API_KEY",
        "DASHSCOPE_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
    ):
        val = (os.environ.get(key) or "").strip()
        if val:
            return val
    return ""


def ai_base_url() -> str:
    explicit = (_cfg("AP_AI_BASE_URL") or _cfg("MC_AI_BASE_URL")).rstrip("/")
    if explicit:
        return explicit
    provider = ai_provider()
    # 分厂商覆盖
    vendor = {
        "openai": _cfg("OPENAI_BASE_URL"),
        "deepseek": _cfg("DEEPSEEK_BASE_URL"),
        "qwen": _cfg("QWEN_BASE_URL") or _cfg("DASHSCOPE_BASE_URL"),
        "gemini": _cfg("GEMINI_BASE_URL"),
        "ollama": _cfg("OLLAMA_BASE_URL"),
    }.get(provider, "")
    if vendor:
        url = vendor.rstrip("/")
        if provider == "ollama" and not url.endswith("/v1"):
            return url + "/v1"
        return url
    return provider_default_base_url(provider)


def ai_model() -> str:
    explicit = _cfg("AP_AI_MODEL") or _cfg("MC_AI_MODEL")
    if not explicit:
        provider = ai_provider()
        vendor = {
            "openai": _cfg("OPENAI_MODEL"),
            "deepseek": _cfg("DEEPSEEK_MODEL"),
            "qwen": _cfg("QWEN_MODEL"),
            "gemini": _cfg("GEMINI_MODEL"),
            "ollama": _cfg("OLLAMA_MODEL") or os.environ.get("OLLAMA_MODEL", ""),
        }.get(provider, "")
        if vendor:
            explicit = vendor
        else:
            explicit = provider_default_model(provider)
    return (explicit or provider_default_model("openai")).strip()


def normalize_codegen_purpose(purpose: str | None) -> str:
    """authoring | planning | locate。"""
    raw = (purpose or "authoring").strip().lower()
    if raw in ("locate", "location", "deep_think", "deep-think"):
        return "locate"
    if raw in ("planning", "plan", "nl", "nl_bootstrap", "bootstrap"):
        return "planning"
    return "authoring"


def ai_model_for_purpose(purpose: str | None = "authoring") -> str:
    """按 codegen purpose 选模型；未配置专用项时回落 ``ai_model()``。

    - 定位：``AP_AI_LOCATE_MODEL`` → ``AP_AI_PLANNING_MODEL`` → 默认
    - 规划/编写：``AP_AI_PLANNING_MODEL`` → 默认
    """
    kind = normalize_codegen_purpose(purpose)
    if kind == "locate":
        locate = (_cfg("AP_AI_LOCATE_MODEL") or "").strip()
        if locate:
            return locate
    if kind in ("locate", "planning", "authoring"):
        planning = (_cfg("AP_AI_PLANNING_MODEL") or "").strip()
        if planning:
            return planning
    return ai_model()


def ai_model_deprecation_hint(model: str | None = None) -> str:
    """旧模型 / 临近弃用提示（不静默 remap）。"""
    from .provider_profile import model_deprecation_hint

    m = (model or ai_model()).strip()
    hint = model_deprecation_hint(m)
    if m in ("deepseek-chat", "deepseek-reasoner") and hint:
        return hint + "（DeepSeek 旧别名见 https://api-docs.deepseek.com/zh-cn/ ）"
    return hint


def ai_reasoning_effort() -> str:
    """统一推理档位：none | low | medium | high | max。

    仅读 ``AP_AI_REASONING_EFFORT``；默认 ``none``（设计域低延迟）。
    旧键 ``AP_AI_DEEPSEEK_REASONING_EFFORT`` 只影响 DeepSeek 已开启 thinking 时的 high/max。
    """
    from .provider_profile import normalize_reasoning_effort

    raw = _cfg("AP_AI_REASONING_EFFORT", "")
    if raw:
        return normalize_reasoning_effort(raw, default="none")
    return "none"


def deepseek_thinking_enabled() -> bool:
    """是否对 DeepSeek 启用 thinking。

    官方默认 thinking=enabled；用例生成默认要低延迟，故：
    - 显式 ``AP_AI_DEEPSEEK_THINKING=1/0`` → 遵从
    - 统一 ``AP_AI_REASONING_EFFORT!=none`` → 开
    - 模型为 ``deepseek-v4-pro`` 或旧别名 ``deepseek-reasoner`` → 开
    - 否则关（并在请求里显式 disabled，避免吃到官方默认 enabled）
    """
    raw = _cfg("AP_AI_DEEPSEEK_THINKING", "")
    if raw:
        return _truthy(raw)
    if ai_reasoning_effort() != "none":
        return True
    model = ai_model().strip()
    return model in ("deepseek-v4-pro", "deepseek-reasoner")


def deepseek_reasoning_effort() -> str:
    """high | max；由统一档位映射（DeepSeek 仅两档）。"""
    level = ai_reasoning_effort()
    if level == "max":
        return "max"
    if level == "none":
        # thinking 关闭时不使用；若仍被读取则给 high 占位
        raw = (
            _cfg("AP_AI_DEEPSEEK_REASONING_EFFORT")
            or _cfg("DEEPSEEK_REASONING_EFFORT")
            or "high"
        ).strip().lower()
        return "max" if raw in ("max", "xhigh", "extra_high") else "high"
    return "max" if level == "max" else "high"


def resolve_deepseek_thinking_for_model(model: str | None = None) -> bool:
    """组装请求体时的 DeepSeek thinking 开关（含单次 model 覆盖）。"""
    raw = _cfg("AP_AI_DEEPSEEK_THINKING", "")
    if raw:
        return _truthy(raw)
    m = (model or ai_model()).strip()
    # pro / 旧 reasoner：默认开思考（历史行为）
    if m in ("deepseek-v4-pro", "deepseek-reasoner"):
        return True
    # flash：仅统一档位非 none 时开
    return ai_reasoning_effort() != "none"


def ai_timeout_sec() -> float:
    raw = _cfg("AP_AI_TIMEOUT_SEC", "180")
    try:
        return max(30.0, float(raw))
    except ValueError:
        return 180.0


def ai_max_tokens() -> int:
    raw = _cfg("AP_AI_MAX_TOKENS", "4096")
    try:
        return max(512, int(raw))
    except ValueError:
        return 4096


def ai_codegen_max_tokens() -> int:
    """链路 3 单次输出上限。

    默认与通用 Chat 齐平：一次性规划整条用例（可达 24 步）时输出并不短，
    截断会直接毁掉整轮编写。要压成本请调这个值，别指望默认值兜。
    """
    raw = _cfg("AP_AI_CODEGEN_MAX_TOKENS", "")
    if not raw:
        return ai_max_tokens()
    try:
        configured = max(512, min(8192, int(raw)))
    except ValueError:
        return ai_max_tokens()
    return configured


def ai_temperature() -> float:
    raw = _cfg("AP_AI_TEMPERATURE", "0.2")
    try:
        return max(0.0, min(2.0, float(raw)))
    except ValueError:
        return 0.2


def ai_verbosity() -> str:
    """OpenAI gpt-5 verbosity：none|low|medium|high；默认 none=不传。"""
    from .provider_profile import normalize_verbosity

    raw = _cfg("AP_AI_VERBOSITY", "")
    if raw:
        return normalize_verbosity(raw, default="none")
    return "none"


def ai_embedding_model() -> str:
    explicit = (_cfg("AP_AI_EMBEDDING_MODEL") or "").strip()
    if explicit:
        return explicit
    provider = ai_provider()
    if provider == "ollama":
        return "nomic-embed-text"
    if provider == "qwen":
        return "text-embedding-v3"
    if provider == "gemini":
        return "text-embedding-004"
    return "text-embedding-3-small"


def rag_embedder() -> str:
    raw = (_cfg("AP_RAG_EMBEDDER") or "auto").strip().lower()
    return raw if raw in ("auto", "hashing", "openai") else "auto"


def ai_chat_max_attempts() -> int:
    """空内容 / 5xx 重试次数。"""
    raw = _cfg("AP_AI_CHAT_MAX_ATTEMPTS", "3")
    try:
        return max(1, min(5, int(raw)))
    except ValueError:
        return 3


def ai_codegen_max_attempts() -> int:
    """链路 3 厂商调用尝试次数；默认最多重试一次，避免瞬时故障放大消耗。"""
    raw = _cfg("AP_AI_CODEGEN_MAX_ATTEMPTS", "2")
    try:
        return max(1, min(4, int(raw)))
    except ValueError:
        return 2
