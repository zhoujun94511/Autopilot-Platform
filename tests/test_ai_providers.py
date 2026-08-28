"""AI provider 配置与 chat client 单测。"""

from __future__ import annotations

import httpx
import pytest

import autopilot_platform.platform.ai.ai_client as ai_client
import autopilot_platform.platform.ai.ai_config as ai_config
from autopilot_platform.platform.ai.ai_client import (
    chat_completions,
    chat_completions_stream,
)


_CLEAR_KEYS = (
    "AP_AI_PROVIDER",
    "AP_AI_API_KEY",
    "AP_AI_BASE_URL",
    "AP_AI_MODEL",
    "AP_AI_REASONING_EFFORT",
    "AP_AI_DEEPSEEK_THINKING",
    "AP_AI_DEEPSEEK_REASONING_EFFORT",
    "AP_AI_CHAT_MAX_ATTEMPTS",
    "MC_AI_PROVIDER",
    "MC_AI_API_KEY",
    "MC_AI_BASE_URL",
    "MC_AI_MODEL",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "OPENAI_MODEL",
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_BASE_URL",
    "DEEPSEEK_MODEL",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "GEMINI_BASE_URL",
    "GEMINI_MODEL",
    "DASHSCOPE_API_KEY",
    "QWEN_API_KEY",
    "QWEN_BASE_URL",
    "QWEN_MODEL",
    "OLLAMA_BASE_URL",
    "OLLAMA_MODEL",
)


@pytest.fixture(autouse=True)
def _clear_ai_env(monkeypatch, tmp_path):
    for k in _CLEAR_KEYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("MC_RUNTIME_CONFIG", str(tmp_path / "mc_runtime_config.json"))
    from autopilot_platform.platform.ops.runtime_config import reload_runtime_config

    reload_runtime_config()
    yield
    reload_runtime_config()


def test_deepseek_defaults(monkeypatch):
    monkeypatch.setenv("AP_AI_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds")
    from autopilot_platform.platform.ops.runtime_config import reload_runtime_config

    reload_runtime_config()
    assert ai_config.ai_provider() == "deepseek"
    assert ai_config.ai_base_url() == "https://api.deepseek.com"
    assert ai_config.ai_model() == "deepseek-v4-flash"
    assert ai_config.ai_api_key() == "sk-ds"
    assert ai_config.deepseek_thinking_enabled() is False
    body = ai_client._build_chat_body(messages=[{"role": "user", "content": "hi"}])
    assert body["thinking"] == {"type": "disabled"}


def test_qwen_and_ollama_and_openai_defaults(monkeypatch):
    from autopilot_platform.platform.ops.runtime_config import reload_runtime_config

    monkeypatch.setenv("AP_AI_PROVIDER", "qwen")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-qw")
    reload_runtime_config()
    assert ai_config.ai_base_url() == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert ai_config.ai_model() == "qwen-plus"

    monkeypatch.setenv("AP_AI_PROVIDER", "ollama")
    for k in ("AP_AI_BASE_URL", "AP_AI_MODEL", "OLLAMA_BASE_URL", "OLLAMA_MODEL"):
        monkeypatch.delenv(k, raising=False)
    reload_runtime_config()
    assert ai_config.ai_base_url() == "http://127.0.0.1:11434/v1"
    assert ai_config.ai_model() == "llama3.2"

    monkeypatch.setenv("AP_AI_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-oai")
    for k in ("AP_AI_BASE_URL", "AP_AI_MODEL", "OPENAI_BASE_URL", "OPENAI_MODEL"):
        monkeypatch.delenv(k, raising=False)
    reload_runtime_config()
    assert ai_config.ai_base_url() == "https://api.openai.com/v1"
    assert ai_config.ai_model() == "gpt-5.4-mini"


def test_list_ai_providers_catalog():
    providers = ai_config.list_ai_providers()
    ids = [p["id"] for p in providers]
    assert ids == ["openai", "deepseek", "qwen", "gemini", "ollama"]
    by_id = {p["id"]: p for p in providers}
    assert by_id["deepseek"]["default_base_url"] == "https://api.deepseek.com"
    assert by_id["deepseek"]["default_model"] == "deepseek-v4-flash"
    assert "deepseek-v4-pro" in by_id["deepseek"]["models"]
    assert by_id["deepseek"]["accepts_images"] is False
    assert "deepseek-v4-flash-vision-exp" in by_id["deepseek"]["vision_models"]
    assert "deepseek-v4-flash-vision-exp" in by_id["deepseek"]["models"]
    assert by_id["qwen"]["default_model"] == "qwen-plus"
    assert "qwen-vl-plus" in by_id["qwen"]["vision_models"]
    assert by_id["gemini"]["default_model"] == "gemini-3.5-flash"
    assert by_id["ollama"]["default_base_url"].endswith("/v1")
    assert by_id["openai"]["default_model"] == "gpt-5.4-mini"
    # catalog defaults must match runtime resolvers
    for p in providers:
        assert ai_config.provider_default_base_url(p["id"]) == p["default_base_url"]
        assert ai_config.provider_default_model(p["id"]) == p["default_model"]
        assert ai_config.provider_recommended_models(p["id"]) == p["models"]


def test_deepseek_pro_enables_thinking(monkeypatch):
    monkeypatch.setenv("AP_AI_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds")
    monkeypatch.setenv("AP_AI_MODEL", "deepseek-v4-pro")
    from autopilot_platform.platform.ops.runtime_config import reload_runtime_config

    reload_runtime_config()
    assert ai_config.deepseek_thinking_enabled() is True
    body = ai_client._build_chat_body(messages=[{"role": "user", "content": "hi"}])
    assert body["thinking"] == {"type": "enabled"}
    assert body["reasoning_effort"] == "high"


def test_deepseek_deprecated_hint(monkeypatch):
    monkeypatch.setenv("AP_AI_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk")
    monkeypatch.setenv("AP_AI_MODEL", "deepseek-chat")
    from autopilot_platform.platform.ops.runtime_config import reload_runtime_config

    reload_runtime_config()
    hint = ai_config.ai_model_deprecation_hint()
    assert "deepseek-v4-flash" in hint
    assert ai_config.ai_model() == "deepseek-chat"


def test_gemini_defaults(monkeypatch):
    monkeypatch.setenv("AP_AI_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "AIza")
    from autopilot_platform.platform.ops.runtime_config import reload_runtime_config

    reload_runtime_config()
    assert ai_config.ai_provider() == "gemini"
    assert "v1beta/openai" in ai_config.ai_base_url()
    assert ai_config.ai_model() == "gemini-3.5-flash"
    assert ai_config.ai_api_key() == "AIza"


def test_chat_completions_retries_empty(monkeypatch):
    monkeypatch.setenv("AP_AI_PROVIDER", "openai")
    monkeypatch.setenv("AP_AI_API_KEY", "sk-test")
    monkeypatch.setenv("AP_AI_CHAT_MAX_ATTEMPTS", "2")
    from autopilot_platform.platform.ops.runtime_config import reload_runtime_config

    reload_runtime_config()

    calls = {"n": 0}

    class _Resp:
        def __init__(self, payload):
            self.status_code = 200
            self._payload = payload
            self.request = httpx.Request("POST", "http://example/v1/chat/completions")

        @staticmethod
        def raise_for_status():
            return None

        def json(self):
            return self._payload

    class _Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        @staticmethod
        def post(_url, _headers=None, _json=None):
            calls["n"] += 1
            if calls["n"] == 1:
                return _Resp(
                    {"choices": [{"message": {"content": ""}, "finish_reason": "stop"}]}
                )
            return _Resp({"choices": [{"message": {"content": '{"ok":true}'}}]})

    monkeypatch.setattr(httpx, "Client", _Client)
    out = chat_completions([{"role": "user", "content": "x"}])
    assert out.startswith("{")
    assert calls["n"] == 2


def test_chat_completions_stream_parses_sse(monkeypatch):
    monkeypatch.setenv("AP_AI_PROVIDER", "openai")
    monkeypatch.setenv("AP_AI_API_KEY", "sk-test")
    from autopilot_platform.platform.ops.runtime_config import reload_runtime_config

    reload_runtime_config()

    lines = [
        'data: {"choices":[{"delta":{"content":"Hel"}}]}',
        'data: {"choices":[{"delta":{"content":"lo"}}]}',
        "data: [DONE]",
    ]

    class _StreamResp:
        status_code = 200
        request = httpx.Request("POST", "http://example/v1/chat/completions")

        @staticmethod
        def iter_lines():
            yield from lines

        @staticmethod
        def read():
            return b""

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class _Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        @staticmethod
        def stream(_method, _url, _headers=None, json=None):
            assert json is not None and json.get("stream") is True
            return _StreamResp()

    monkeypatch.setattr(httpx, "Client", _Client)
    pieces = list(chat_completions_stream([{"role": "user", "content": "x"}]))
    assert pieces == ["Hel", "lo"]


def test_build_chat_body_overrides_temperature_and_model(monkeypatch):
    monkeypatch.setenv("AP_AI_PROVIDER", "openai")
    monkeypatch.setenv("AP_AI_API_KEY", "sk-test")
    monkeypatch.setenv("AP_AI_MODEL", "gpt-4o-mini")
    monkeypatch.setenv("AP_AI_TEMPERATURE", "0.9")
    from autopilot_platform.platform.ops.runtime_config import reload_runtime_config

    reload_runtime_config()

    body = ai_client._build_chat_body(
        messages=[{"role": "user", "content": "hi"}],
        model="gpt-4o",
        temperature=0.2,
        max_tokens=1024,
    )
    assert body["model"] == "gpt-4o"
    assert body["temperature"] == 0.2
    assert body["max_tokens"] == 1024

    # 运维/请求温度原样生效（仅钳制到 [0, 2]，不再静默改写）
    body2 = ai_client._build_chat_body(
        messages=[{"role": "user", "content": "hi"}],
        temperature=0.9,
    )
    assert body2["temperature"] == 0.9

    # gpt-5 不传 temperature
    body3 = ai_client._build_chat_body(
        messages=[{"role": "user", "content": "hi"}],
        model="gpt-5",
        temperature=0.2,
    )
    assert "temperature" not in body3
    assert body3["model"] == "gpt-5"


def test_reasoning_effort_openai_gpt5(monkeypatch):
    monkeypatch.setenv("AP_AI_PROVIDER", "openai")
    monkeypatch.setenv("AP_AI_API_KEY", "sk")
    monkeypatch.setenv("AP_AI_MODEL", "gpt-5.4-mini")
    monkeypatch.setenv("AP_AI_REASONING_EFFORT", "max")
    from autopilot_platform.platform.ops.runtime_config import reload_runtime_config

    reload_runtime_config()
    body = ai_client._build_chat_body(messages=[{"role": "user", "content": "hi"}])
    assert body.get("reasoning_effort") == "max"
    assert "temperature" not in body


def test_reasoning_effort_qwen_enable_thinking(monkeypatch):
    monkeypatch.setenv("AP_AI_PROVIDER", "qwen")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk")
    monkeypatch.setenv("AP_AI_REASONING_EFFORT", "medium")
    from autopilot_platform.platform.ops.runtime_config import reload_runtime_config

    reload_runtime_config()
    body = ai_client._build_chat_body(messages=[{"role": "user", "content": "hi"}])
    assert body.get("enable_thinking") is True
    assert body.get("thinking_budget") == 8192


def test_reasoning_effort_gemini_passthrough(monkeypatch):
    """Gemini OpenAI 兼容：low 必须原样为 low，不得改写成 minimal。"""
    monkeypatch.setenv("AP_AI_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "AIza")
    monkeypatch.setenv("AP_AI_REASONING_EFFORT", "low")
    from autopilot_platform.platform.ops.runtime_config import reload_runtime_config

    reload_runtime_config()
    body = ai_client._build_chat_body(messages=[{"role": "user", "content": "hi"}])
    assert body.get("reasoning_effort") == "low"
    assert "temperature" not in body

    monkeypatch.setenv("AP_AI_REASONING_EFFORT", "minimal")
    reload_runtime_config()
    body2 = ai_client._build_chat_body(messages=[{"role": "user", "content": "hi"}])
    assert body2.get("reasoning_effort") == "minimal"


def test_deepseek_thinking_omits_temperature(monkeypatch):
    monkeypatch.setenv("AP_AI_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk")
    monkeypatch.setenv("AP_AI_MODEL", "deepseek-v4-pro")
    monkeypatch.setenv("AP_AI_TEMPERATURE", "0.5")
    from autopilot_platform.platform.ops.runtime_config import reload_runtime_config

    reload_runtime_config()
    body = ai_client._build_chat_body(messages=[{"role": "user", "content": "hi"}])
    assert body.get("thinking") == {"type": "enabled"}
    assert "temperature" not in body


def test_provider_profile_accepts_images():
    from autopilot_platform.platform.ai.provider_profile import model_accepts_images

    assert model_accepts_images("deepseek", "deepseek-v4-flash") is False
    assert model_accepts_images("deepseek", "deepseek-v4-flash-vision-exp") is True
    assert model_accepts_images("qwen", "qwen-plus") is False
    assert model_accepts_images("qwen", "qwen-vl-plus") is True
    assert model_accepts_images("openai", "gpt-5.4-mini") is True
    assert model_accepts_images("gemini", "gemini-3.5-flash") is True


def test_gpt5_uses_max_completion_tokens(monkeypatch):
    monkeypatch.setenv("AP_AI_PROVIDER", "openai")
    monkeypatch.setenv("AP_AI_API_KEY", "sk")
    monkeypatch.setenv("AP_AI_MODEL", "gpt-5.4-mini")
    from autopilot_platform.platform.ops.runtime_config import reload_runtime_config

    reload_runtime_config()
    body = ai_client._build_chat_body(messages=[{"role": "user", "content": "hi"}])
    assert "max_tokens" not in body
    assert body.get("max_completion_tokens") == ai_config.ai_max_tokens()


def test_openai_verbosity_gpt5(monkeypatch):
    monkeypatch.setenv("AP_AI_PROVIDER", "openai")
    monkeypatch.setenv("AP_AI_API_KEY", "sk")
    monkeypatch.setenv("AP_AI_MODEL", "gpt-5.4-mini")
    monkeypatch.delenv("AP_AI_VERBOSITY", raising=False)
    from autopilot_platform.platform.ops.runtime_config import reload_runtime_config

    reload_runtime_config()
    body = ai_client._build_chat_body(messages=[{"role": "user", "content": "hi"}])
    assert "verbosity" not in body

    monkeypatch.setenv("AP_AI_VERBOSITY", "low")
    reload_runtime_config()
    body2 = ai_client._build_chat_body(messages=[{"role": "user", "content": "hi"}])
    assert body2.get("verbosity") == "low"

    monkeypatch.setenv("AP_AI_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk")
    monkeypatch.setenv("AP_AI_MODEL", "deepseek-v4-flash")
    monkeypatch.setenv("AP_AI_VERBOSITY", "high")
    reload_runtime_config()
    body3 = ai_client._build_chat_body(messages=[{"role": "user", "content": "hi"}])
    assert "verbosity" not in body3


def test_normalize_verbosity():
    from autopilot_platform.platform.ai.provider_profile import normalize_verbosity

    assert normalize_verbosity("LOW") == "low"
    assert normalize_verbosity("minimal") == "low"
    assert normalize_verbosity("max") == "high"
    assert normalize_verbosity("off") == "none"
