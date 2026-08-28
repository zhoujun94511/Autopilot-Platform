"""Intent / Vision / Webhook 配置：环境变量 + 默认兜底。"""

from __future__ import annotations

import os

from .provider_profile import (
    DEFAULT_DEEPSEEK_VISION_MODEL,
    detect_provider,
    model_accepts_images,
    normalize_reasoning_effort,
    normalize_verbosity,
)


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def _truthy(raw: str) -> bool:
    return raw.strip().lower() in ("1", "true", "yes", "on")


# ---- Vision ----

DEFAULT_VISION_ENABLED = "0"
DEFAULT_VISION_BASE_URL = "https://api.openai.com/v1"
DEFAULT_VISION_MODEL = "gpt-5.4-mini"
DEFAULT_VISION_TIMEOUT_SEC = "45"
DEFAULT_VISION_REASONING_EFFORT = "none"
DEFAULT_VISION_TEMPERATURE = "0.1"
DEFAULT_VISION_VERBOSITY = "none"
# always | fallback（启发式全失败后再调）| empty（仅无启发式候选时）
DEFAULT_VISION_WHEN = "fallback"
DEFAULT_VISION_SCREENSHOT = "1"
DEFAULT_VISION_DOM = "1"
DEFAULT_VISION_DOM_MODE = "compact"  # compact | full | off
DEFAULT_VISION_DOM_MAX = "50"
DEFAULT_VISION_IMAGE_MAX_KB = "220"
DEFAULT_VISION_IMAGE_SHORT_SIDE = "560"
DEFAULT_VISION_IMAGE_DETAIL = "low"  # low | auto | high | original；无 DOM 时自动升 auto，enhanced 升 high
# auto：按厂商能力决定是否传图；off：永不传图；force：强制传 image_url（真多模态网关）
DEFAULT_VISION_IMAGE_MODE = "auto"
# 单用例 vision 调用硬顶：0=不限（不建议）
DEFAULT_VISION_MAX_CALLS_PER_CASE = "30"


def intent_vision_enabled() -> bool:
    return _truthy(_env("AUTOPILOT_INTENT_VISION", DEFAULT_VISION_ENABLED))


def vision_max_calls_per_case() -> int:
    """每用例最多调用多少次 vision；0=关闭上限。"""
    raw = _env("AUTOPILOT_VISION_MAX_CALLS_PER_CASE", DEFAULT_VISION_MAX_CALLS_PER_CASE)
    try:
        return max(0, int(raw or DEFAULT_VISION_MAX_CALLS_PER_CASE))
    except ValueError:
        return int(DEFAULT_VISION_MAX_CALLS_PER_CASE)


_VISION_KEY_ENVS = (
    "AUTOPILOT_VISION_API_KEY",
    "AP_AI_API_KEY",
    "OPENAI_API_KEY",
    "DEEPSEEK_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "DASHSCOPE_API_KEY",
)


def vision_local_key_allowed() -> bool:
    """企业锁定 Platform URL 时默认禁止本机 Vision Key（AUD-P2-007）。

    与链路 3「企业 Key 只在 Platform」对齐；Runner 若由 IT 注入 Key 跑 Vision，
    须显式 ``AUTOPILOT_VISION_ALLOW_LOCAL_KEY=1``。开发机未锁定 URL 时不受影响。
    """
    raw = _env("AUTOPILOT_VISION_ALLOW_LOCAL_KEY")
    if raw:
        return _truthy(raw)
    try:
        from ..runtime.platform_deploy import platform_url_locked  # 延迟：仅锁定部署 URL
    except ImportError:
        platform_url_locked = None  # Platform ``ap`` 切片可能无此模块
    if callable(platform_url_locked):
        try:
            if platform_url_locked():
                return False
            return True
        except (OSError, RuntimeError):
            return True

    # 无 platform_deploy：回落认环境变量部署
    if _env("AUTOPILOT_PLATFORM_URL"):
        ov = _env("AUTOPILOT_ALLOW_PLATFORM_URL_OVERRIDE").lower()
        if ov not in ("1", "true", "yes", "on"):
            return False
    return True


def vision_api_key_configured() -> bool:
    """环境中是否出现任一 Vision/厂商 Key（忽略企业锁定策略）。"""
    return any(_env(name) for name in _VISION_KEY_ENVS)


def vision_api_key() -> str:
    if not vision_local_key_allowed():
        return ""
    for key in _VISION_KEY_ENVS:
        val = _env(key)
        if val:
            return val
    return ""


def vision_base_url() -> str:
    return (
        _env("AUTOPILOT_VISION_BASE_URL")
        or _env("AP_AI_BASE_URL")
        or _env("DEEPSEEK_BASE_URL")
        or DEFAULT_VISION_BASE_URL
    ).rstrip("/")


def vision_model() -> str:
    """Vision 定位模型。

    未显式指定 ``AUTOPILOT_VISION_MODEL`` / ``AP_AI_LOCATE_MODEL`` 时，
    若 Chat 默认是 DeepSeek 纯文本型号，回落到官方 vision 实验模型，避免把
    ``deepseek-v4-flash`` 误当识图。显式指定文本型号仍走 DOM-only。
    """
    explicit = _env("AUTOPILOT_VISION_MODEL") or _env("AP_AI_LOCATE_MODEL")
    if explicit:
        return explicit
    mid = _env("AP_AI_MODEL") or _env("DEEPSEEK_MODEL") or DEFAULT_VISION_MODEL
    url = vision_base_url()
    provider = detect_provider("", mid, url)
    if (provider == "deepseek" or mid.lower().startswith("deepseek")) and not model_accepts_images(
        provider, mid, base_url=url
    ):
        return DEFAULT_DEEPSEEK_VISION_MODEL
    return mid


def vision_image_mode() -> str:
    """auto | off | force。"""
    raw = (_env("AUTOPILOT_VISION_IMAGE_MODE", DEFAULT_VISION_IMAGE_MODE) or "auto").lower()
    if raw in ("off", "none", "0", "false", "text", "text_only"):
        return "off"
    if raw in ("force", "always", "on", "1", "true"):
        return "force"
    return "auto"


def vision_reasoning_effort() -> str:
    """Vision 调用推理档位；默认 none（定位任务低延迟）。"""

    raw = (
        _env("AUTOPILOT_VISION_REASONING_EFFORT")
        or _env("AP_AI_REASONING_EFFORT")
        or DEFAULT_VISION_REASONING_EFFORT
    )
    return normalize_reasoning_effort(raw, default="none")


def vision_temperature() -> float:
    """Vision temperature；gpt-5 / Gemini3 / DeepSeek thinking 时仍可能省略。"""
    raw = (
        _env("AUTOPILOT_VISION_TEMPERATURE")
        or _env("AP_AI_TEMPERATURE")
        or DEFAULT_VISION_TEMPERATURE
    )
    try:
        return max(0.0, min(2.0, float(raw)))
    except ValueError:
        return 0.1


def vision_verbosity() -> str:
    """OpenAI gpt-5 verbosity；默认 none=不传。可回退 AP_AI_VERBOSITY。"""

    raw = (
        _env("AUTOPILOT_VISION_VERBOSITY")
        or _env("AP_AI_VERBOSITY")
        or DEFAULT_VISION_VERBOSITY
    )
    return normalize_verbosity(raw, default="none")


def vision_provider_is_text_only(
    base_url: str | None = None,
    model: str | None = None,
) -> bool:
    """当前 Vision 配置是否不应传图（DeepSeek 非 vision / 非 VL 千问等）。"""

    url = (base_url if base_url is not None else vision_base_url()).strip()
    mid = (model if model is not None else vision_model()).strip()
    provider = detect_provider("", mid, url)
    return not model_accepts_images(provider, mid, base_url=url)


def vision_accepts_images(
    base_url: str | None = None,
    model: str | None = None,
) -> bool:
    """当前配置是否应在请求里附带截图（image_url）。"""
    mode = vision_image_mode()
    if mode == "off":
        return False
    if mode == "force":
        # force 只允许绕过 auto/off 策略，不能伪造模型能力。DeepSeek 文本型号
        # 若误发图会浪费一次失败请求再降级，故仍 fail-closed 为 DOM-only。
        return not vision_provider_is_text_only(base_url, model)
    return not vision_provider_is_text_only(base_url, model)


def vision_timeout_sec() -> float:
    raw = _env("AUTOPILOT_VISION_TIMEOUT_SEC", DEFAULT_VISION_TIMEOUT_SEC)
    try:
        return max(10.0, float(raw or DEFAULT_VISION_TIMEOUT_SEC))
    except ValueError:
        return float(DEFAULT_VISION_TIMEOUT_SEC)


def vision_when() -> str:
    """always | fallback | empty。"""
    raw = (_env("AUTOPILOT_VISION_WHEN", DEFAULT_VISION_WHEN) or DEFAULT_VISION_WHEN).lower()
    if raw in ("always", "every", "all"):
        return "always"
    if raw in ("empty", "heuristic_empty", "no_heuristic"):
        return "empty"
    return "fallback"


def vision_screenshot_enabled() -> bool:
    return _truthy(_env("AUTOPILOT_VISION_SCREENSHOT", DEFAULT_VISION_SCREENSHOT))


def vision_dom_enabled() -> bool:
    mode = vision_dom_mode()
    if mode == "off":
        return False
    return _truthy(_env("AUTOPILOT_VISION_DOM", DEFAULT_VISION_DOM))


def vision_dom_mode() -> str:
    raw = (_env("AUTOPILOT_VISION_DOM_MODE", DEFAULT_VISION_DOM_MODE) or "compact").lower()
    if raw in ("full", "attrs", "rich"):
        return "full"
    if raw in ("off", "none", "0", "false"):
        return "off"
    return "compact"


def vision_dom_max() -> int:
    raw = _env("AUTOPILOT_VISION_DOM_MAX", DEFAULT_VISION_DOM_MAX)
    try:
        return max(1, min(200, int(raw or DEFAULT_VISION_DOM_MAX)))
    except ValueError:
        return int(DEFAULT_VISION_DOM_MAX)


def vision_image_max_kb() -> int:
    raw = _env("AUTOPILOT_VISION_IMAGE_MAX_KB", DEFAULT_VISION_IMAGE_MAX_KB)
    try:
        return max(32, min(2048, int(raw or DEFAULT_VISION_IMAGE_MAX_KB)))
    except ValueError:
        return int(DEFAULT_VISION_IMAGE_MAX_KB)


def vision_image_short_side() -> int:
    raw = _env("AUTOPILOT_VISION_IMAGE_SHORT_SIDE", DEFAULT_VISION_IMAGE_SHORT_SIDE)
    try:
        return max(160, min(1600, int(raw or DEFAULT_VISION_IMAGE_SHORT_SIDE)))
    except ValueError:
        return int(DEFAULT_VISION_IMAGE_SHORT_SIDE)


def vision_image_detail() -> str:
    raw = (_env("AUTOPILOT_VISION_IMAGE_DETAIL", DEFAULT_VISION_IMAGE_DETAIL) or "low").lower()
    if raw in ("high", "auto", "low", "original"):
        return raw
    return "low"


def vision_image_enhanced() -> bool:
    """强制使用高清档（短边 720 / detail=high / DOM full）。"""
    return _truthy(_env("AUTOPILOT_VISION_IMAGE_ENHANCED", "0"))


# ---- IDE webhook receiver ----

DEFAULT_WEBHOOK_HOST = "127.0.0.1"
DEFAULT_WEBHOOK_PORT = "8765"
DEFAULT_IMPORT_SUBDIR = "imported_logical"


def intent_webhook_host() -> str:
    return _env("AUTOPILOT_INTENT_WEBHOOK_HOST", DEFAULT_WEBHOOK_HOST) or DEFAULT_WEBHOOK_HOST


def intent_webhook_port() -> int:
    raw = _env("AUTOPILOT_INTENT_WEBHOOK_PORT", DEFAULT_WEBHOOK_PORT)
    try:
        return max(1, int(raw or DEFAULT_WEBHOOK_PORT))
    except ValueError:
        return int(DEFAULT_WEBHOOK_PORT)


def intent_webhook_secret() -> str:
    return (
        _env("AUTOPILOT_WEBHOOK_SECRET")
        or _env("MC_WEBHOOK_SECRET")
        or ""
    )


def intent_import_subdir() -> str:
    return _env("AUTOPILOT_INTENT_IMPORT_SUBDIR", DEFAULT_IMPORT_SUBDIR) or DEFAULT_IMPORT_SUBDIR


def intent_watch_interval_sec() -> int:
    raw = _env("AUTOPILOT_INTENT_WATCH_INTERVAL_SEC", "30")
    try:
        return max(5, int(raw or "30"))
    except ValueError:
        return 30


def intent_auto_approve_min_quality() -> float:
    raw = _env("AUTOPILOT_INTENT_MIN_QUALITY", "0.8")
    try:
        return max(0.0, min(1.0, float(raw or "0.8")))
    except ValueError:
        return 0.8


# ---- 自愈预算 ----

DEFAULT_HEAL_BUDGET_MS = "3000"
DEFAULT_HEAL_CANDIDATE_TIMEOUT_MS = "1500"


def heal_budget_ms() -> int:
    """单步自愈总预算（毫秒）；超时后停止换候选。"""
    raw = _env("AUTOPILOT_INTENT_HEAL_BUDGET_MS", DEFAULT_HEAL_BUDGET_MS)
    try:
        return max(500, min(60_000, int(raw or DEFAULT_HEAL_BUDGET_MS)))
    except ValueError:
        return int(DEFAULT_HEAL_BUDGET_MS)


def heal_candidate_timeout_ms() -> int:
    """自愈阶段覆盖关键字 locator 查找超时（毫秒）。"""
    raw = _env("AUTOPILOT_INTENT_HEAL_CANDIDATE_TIMEOUT_MS", DEFAULT_HEAL_CANDIDATE_TIMEOUT_MS)
    try:
        return max(200, min(15_000, int(raw or DEFAULT_HEAL_CANDIDATE_TIMEOUT_MS)))
    except ValueError:
        return int(DEFAULT_HEAL_CANDIDATE_TIMEOUT_MS)
