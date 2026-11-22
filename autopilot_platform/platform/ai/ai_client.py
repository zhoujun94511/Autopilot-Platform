"""OpenAI 兼容 Chat Completions 客户端（多厂商推理档位 / 空内容重试）。

- 空 content / 5xx / 网络错误有限次退避重试
- 推理参数经 ``provider_profile.apply_reasoning_to_body`` 映射
- DeepSeek flash 默认显式 disabled；不静默 remap 旧模型名
"""

from __future__ import annotations

import json
import logging
import random
import time
from typing import Any, Iterator

import httpx

from . import ai_config
from . import ai_usage
from .provider_profile import (
    apply_max_output_tokens,
    apply_reasoning_to_body,
    apply_verbosity_to_body,
    detect_provider,
    should_omit_temperature,
)

log = logging.getLogger("autopilot_platform.platform.ai")

_ANTHROPIC_VERSION = "2023-06-01"


def _is_anthropic_provider(model: str | None = None) -> bool:
    return (
        detect_provider(
            ai_config.ai_provider(),
            model or ai_config.ai_model(),
            ai_config.ai_base_url(),
        )
        == "anthropic"
    )


def _anthropic_messages_url(base_url: str) -> str:
    clean = (base_url or "https://api.anthropic.com").rstrip("/")
    if clean.endswith("/v1"):
        return f"{clean}/messages"
    return f"{clean}/v1/messages"


def _to_anthropic_content(content: Any) -> Any:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return str(content or "")
    blocks: list[dict[str, Any]] = []
    for part in content:
        if not isinstance(part, dict):
            continue
        ptype = part.get("type")
        if ptype == "text":
            blocks.append({"type": "text", "text": str(part.get("text") or "")})
        elif ptype == "image_url":
            url = str(((part.get("image_url") or {}).get("url")) or "")
            if url.startswith("data:") and ";base64," in url:
                header, b64 = url.split(";base64,", 1)
                media_type = header[5:] or "image/png"
                blocks.append(
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": b64,
                        },
                    }
                )
            elif url:
                blocks.append({"type": "image", "source": {"type": "url", "url": url}})
    return blocks or ""


def _build_anthropic_body(
    *,
    messages: list[dict[str, Any]],
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> dict[str, Any]:
    resolved_model = (model or "").strip() or ai_config.ai_model()
    resolved_max = (
        max(1, int(max_tokens))
        if max_tokens is not None
        else ai_config.ai_max_tokens()
    )
    system_parts: list[str] = []
    converted: list[dict[str, Any]] = []
    for msg in messages:
        role = str(msg.get("role") or "user").strip().lower()
        raw_content = msg.get("content")
        if role == "system":
            if isinstance(raw_content, str) and raw_content.strip():
                system_parts.append(raw_content.strip())
            continue
        norm_role = "assistant" if role == "assistant" else "user"
        converted.append(
            {"role": norm_role, "content": _to_anthropic_content(raw_content)}
        )

    body: dict[str, Any] = {
        "model": resolved_model,
        "max_tokens": resolved_max,
        "messages": converted or [{"role": "user", "content": ""}],
    }
    if system_parts:
        body["system"] = "\n\n".join(system_parts)
    if not should_omit_temperature("anthropic", resolved_model):
        temp = (
            ai_config.ai_temperature()
            if temperature is None
            else _clamp_temperature(temperature)
        )
        body["temperature"] = temp
    return body


def _extract_anthropic_content(data: dict[str, Any]) -> str:
    blocks = data.get("content")
    if not isinstance(blocks, list):
        raise ValueError(f"Anthropic 响应结构异常: {data!r}")
    texts = [
        str(b.get("text") or "")
        for b in blocks
        if isinstance(b, dict) and b.get("type") == "text" and b.get("text")
    ]
    joined = "".join(texts)
    if joined.strip():
        return joined
    stop_reason = str(data.get("stop_reason") or "n/a")
    raise ValueError(f"empty_content finish_reason={stop_reason}")


def _extract_message_content(data: dict[str, Any]) -> str:
    if isinstance(data.get("content"), list) and "choices" not in data:
        return _extract_anthropic_content(data)
    try:
        msg = data["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError(f"模型响应结构异常: {data!r}") from exc
    content = msg.get("content")
    if isinstance(content, str) and content.strip():
        return content
    # thinking 模式下 CoT 在 reasoning_content，最终答案仍应在 content；
    # 用例生成要 JSON，不能把推理链当正文。
    finish = ""
    try:
        finish = str(data["choices"][0].get("finish_reason") or "")
    except (KeyError, IndexError, TypeError):
        pass
    raise ValueError(f"empty_content finish_reason={finish or 'n/a'}")


def _clamp_temperature(value: float) -> float:
    return max(0.0, min(2.0, float(value)))


def _build_chat_body(
    *,
    messages: list[dict[str, Any]],
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> dict[str, Any]:
    resolved_model = (model or "").strip() or ai_config.ai_model()
    hint = ai_config.ai_model_deprecation_hint(resolved_model)
    if hint:
        log.warning("%s", hint)

    resolved_max = (
        max(1, int(max_tokens))
        if max_tokens is not None
        else ai_config.ai_max_tokens()
    )
    body: dict[str, Any] = {
        "model": resolved_model,
        "messages": messages,
    }
    apply_max_output_tokens(body, resolved_model, resolved_max)

    provider = ai_config.ai_provider()
    effort = ai_config.ai_reasoning_effort()
    ds_override = None
    mapped_effort = effort
    if provider == "deepseek":
        ds_override = ai_config.resolve_deepseek_thinking_for_model(resolved_model)
        # pro 默认开思考时，effort=none 仍需写入官方 high
        if ds_override and effort == "none":
            mapped_effort = "high"

    apply_reasoning_to_body(
        body,
        provider=provider,
        model=resolved_model,
        effort=mapped_effort,
        base_url=ai_config.ai_base_url(),
        deepseek_thinking_override=ds_override,
    )
    apply_verbosity_to_body(
        body,
        provider=provider,
        model=resolved_model,
        verbosity=ai_config.ai_verbosity(),
        base_url=ai_config.ai_base_url(),
    )

    thinking_on = body.get("thinking") == {"type": "enabled"}
    # 先写推理字段，再决定 temperature（DeepSeek thinking 时官方无效，省略）
    if not should_omit_temperature(
        provider, resolved_model, thinking_enabled=bool(thinking_on)
    ):
        temp = (
            ai_config.ai_temperature()
            if temperature is None
            else _clamp_temperature(temperature)
        )
        if temp >= 0.7:
            log.warning(
                "temperature=%.2f 偏高，角色约束可能变弱（值来自运维或请求覆盖）",
                temp,
            )
        body["temperature"] = temp
    return body


def chat_completions(
    messages: list[dict[str, Any]],
    *,
    timeout: float | None = None,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    max_attempts: int | None = None,
    usage_source: str = "chat",
) -> str:
    """POST /chat/completions，返回 message content 文本。

    ``usage_source`` 区分用量归属（chat / codegen / …），便于账单按入口拆分。
    """
    if not ai_config.ai_enabled():
        raise RuntimeError("AI API Key 未配置")

    ai_usage.check_budget_before_call()

    use_anthropic = _is_anthropic_provider(model)
    if use_anthropic:
        url = _anthropic_messages_url(ai_config.ai_base_url())
        headers = {
            "x-api-key": ai_config.ai_api_key(),
            "anthropic-version": _ANTHROPIC_VERSION,
            "Content-Type": "application/json",
        }
        body = _build_anthropic_body(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    else:
        url = f"{ai_config.ai_base_url().rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {ai_config.ai_api_key()}",
            "Content-Type": "application/json",
        }
        body = _build_chat_body(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    timeout_s = float(timeout if timeout is not None else ai_config.ai_timeout_sec())
    attempts = (
        max(1, min(5, int(max_attempts)))
        if max_attempts is not None
        else ai_config.ai_chat_max_attempts()
    )
    last_exc: Exception | None = None

    for attempt in range(1, attempts + 1):
        try:
            with httpx.Client(timeout=timeout_s) as client:
                resp = client.post(url, headers=headers, json=body)
            if resp.status_code >= 500:
                raise httpx.HTTPStatusError(
                    f"server error {resp.status_code}",
                    request=resp.request,
                    response=resp,
                )
            if resp.status_code >= 400:
                # 4xx 不重试
                resp.raise_for_status()
            data = resp.json()
            payload = data if isinstance(data, dict) else {}
            content = _extract_message_content(payload)
            ai_usage.record_usage(
                ai_usage.extract_usage(payload),
                source=usage_source or "chat",
                model=str(body.get("model") or ""),
            )
            try:
                from ..core import metrics as mc_metrics  # 延迟：metrics 会 import ai_usage，避免与本模块循环

                u = ai_usage.extract_usage(payload)
                if u["total_tokens"] or u["prompt_tokens"] or u["cached_tokens"]:
                    kind_to_key = {
                        "prompt": "prompt_tokens",
                        "completion": "completion_tokens",
                        "cached": "cached_tokens",
                        "cache_miss": "cache_miss_tokens",
                        "total": "total_tokens",
                    }
                    for kind, key in kind_to_key.items():
                        amount = float(u.get(key) or 0)
                        if amount:
                            mc_metrics.inc(
                                "mc_ai_tokens_total",
                                labels={"kind": kind},
                                amount=amount,
                            )
                    mc_metrics.inc("mc_ai_chat_calls_total", amount=1.0)
            except (ImportError, AttributeError, TypeError, ValueError, RuntimeError):
                pass
            return content
        except ValueError as exc:
            # empty content
            last_exc = exc
            if "empty_content" not in str(exc):
                raise
            if attempt >= attempts:
                break
            delay = 0.3 * (2 ** (attempt - 1)) + random.uniform(0, 0.15)
            log.warning(
                "AI empty content, retry %s/%s after %.2fs (%s)",
                attempt,
                attempts,
                delay,
                ai_config.ai_provider(),
            )
            time.sleep(delay)
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            last_exc = exc
            status = int(getattr(getattr(exc, "response", None), "status_code", 0) or 0)
            if status and 400 <= status < 500:
                raise
            if attempt >= attempts:
                break
            delay = 0.3 * (2 ** (attempt - 1)) + random.uniform(0, 0.15)
            log.warning(
                "AI transient error, retry %s/%s after %.2fs: %s",
                attempt,
                attempts,
                delay,
                exc,
            )
            time.sleep(delay)

    assert last_exc is not None
    raise last_exc


def _extract_stream_delta(data: dict[str, Any]) -> str:
    """从 OpenAI-compatible 或 Anthropic Messages SSE chunk 取出 content delta。"""
    if data.get("type") == "content_block_delta":
        delta = data.get("delta") or {}
        if isinstance(delta, dict) and delta.get("type") == "text_delta":
            text = delta.get("text")
            if isinstance(text, str) and text:
                return text
        return ""
    try:
        delta = data["choices"][0].get("delta") or {}
    except (KeyError, IndexError, TypeError):
        return ""
    content = delta.get("content")
    if isinstance(content, str) and content:
        return content
    return ""


def _extract_stream_usage(data: dict[str, Any]) -> dict[str, int]:
    if data.get("type") == "message_start" and isinstance(data.get("message"), dict):
        return ai_usage.extract_usage(data["message"])
    return ai_usage.extract_usage(data)


def chat_completions_stream(
    messages: list[dict[str, Any]],
    *,
    timeout: float | None = None,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> Iterator[str]:
    """POST /chat/completions?stream=true，按 token/增量 yield content 文本。

    对齐 OpenAI-compatible SSE（DeepSeek / Gemini OpenAI 兼容层 / Qwen 等）。
    上游不支持或协议异常时抛出，由调用方决定是否降级到非流式。
    """
    if not ai_config.ai_enabled():
        raise RuntimeError("AI API Key 未配置")

    ai_usage.check_budget_before_call()

    use_anthropic = _is_anthropic_provider(model)
    if use_anthropic:
        url = _anthropic_messages_url(ai_config.ai_base_url())
        headers = {
            "x-api-key": ai_config.ai_api_key(),
            "anthropic-version": _ANTHROPIC_VERSION,
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        body = _build_anthropic_body(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    else:
        url = f"{ai_config.ai_base_url().rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {ai_config.ai_api_key()}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        body = _build_chat_body(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    body["stream"] = True
    timeout_s = float(timeout if timeout is not None else ai_config.ai_timeout_sec())

    yielded = False
    last_usage: dict[str, int] | None = None
    with httpx.Client(timeout=timeout_s) as client:
        with client.stream("POST", url, headers=headers, json=body) as resp:
            if resp.status_code >= 400:
                # 读完 body 便于错误信息；流式 4xx 通常不重试
                detail = ""
                try:
                    detail = (resp.read() or b"").decode("utf-8", errors="replace")[:500]
                except (OSError, httpx.HTTPError, TypeError, ValueError, AttributeError):
                    pass
                raise httpx.HTTPStatusError(
                    f"stream error {resp.status_code}: {detail}",
                    request=resp.request,
                    response=resp,
                )
            for line in resp.iter_lines():
                if not line:
                    continue
                raw = line.strip()
                if raw.startswith("data:"):
                    raw = raw[5:].strip()
                if not raw or raw == "[DONE]":
                    if raw == "[DONE]":
                        break
                    continue
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if not isinstance(payload, dict):
                    continue
                u = _extract_stream_usage(payload)
                if u["total_tokens"] or u["prompt_tokens"] or u["completion_tokens"]:
                    last_usage = u
                piece = _extract_stream_delta(payload)
                if piece:
                    yielded = True
                    yield piece

    if last_usage:
        ai_usage.record_usage(
            last_usage,
            source="chat_stream",
            model=str(body.get("model") or ""),
        )
    else:
        # 流式无 usage 时记一次 0，便于 calls 计数与排查
        ai_usage.record_usage(
            {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            source="chat_stream",
            model=str(body.get("model") or ""),
        )

    if not yielded:
        raise ValueError("empty_stream_content")
