"""Vision / Intent 调用的 token 用量记录（本地 JSONL，非厂商账单）。

归一字段与 Platform ``ai_usage`` 对齐：
  prompt_tokens / completion_tokens / total_tokens
  cached_tokens / cache_miss_tokens / cache_write_tokens
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)
_lock = threading.Lock()

_USAGE_KEYS = (
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "cached_tokens",
    "cache_miss_tokens",
    "cache_write_tokens",
)


def _as_nonneg_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def empty_usage() -> dict[str, int]:
    return {k: 0 for k in _USAGE_KEYS}


def normalize_usage(usage: dict[str, Any] | None) -> dict[str, int]:
    u = empty_usage()
    if not isinstance(usage, dict):
        return u
    for key in _USAGE_KEYS:
        u[key] = _as_nonneg_int(usage.get(key))
    if u["total_tokens"] <= 0 and (u["prompt_tokens"] or u["completion_tokens"]):
        u["total_tokens"] = u["prompt_tokens"] + u["completion_tokens"]
    return u


def extract_usage(payload: Any) -> dict[str, int]:
    """从厂商响应取出用量；缺省字段为 0。"""
    if not isinstance(payload, dict):
        return empty_usage()

    raw = payload.get("usage")
    if isinstance(raw, dict):
        prompt = _as_nonneg_int(raw.get("prompt_tokens") or raw.get("input_tokens"))
        completion = _as_nonneg_int(
            raw.get("completion_tokens") or raw.get("output_tokens")
        )
        total = _as_nonneg_int(raw.get("total_tokens"))

        cached = 0
        details = raw.get("prompt_tokens_details")
        if isinstance(details, dict):
            cached = _as_nonneg_int(details.get("cached_tokens"))
        if raw.get("prompt_cache_hit_tokens") is not None:
            cached = max(cached, _as_nonneg_int(raw.get("prompt_cache_hit_tokens")))
        cache_miss = _as_nonneg_int(raw.get("prompt_cache_miss_tokens"))
        if raw.get("cache_read_input_tokens") is not None:
            cached = max(cached, _as_nonneg_int(raw.get("cache_read_input_tokens")))
        cache_write = _as_nonneg_int(raw.get("cache_creation_input_tokens"))
        if not cached:
            cached = _as_nonneg_int(raw.get("cached_tokens"))
        if not cache_write:
            cache_write = _as_nonneg_int(raw.get("cache_write_tokens"))
        if not cache_miss:
            cache_miss = _as_nonneg_int(raw.get("cache_miss_tokens"))
        if total <= 0 and (prompt or completion):
            total = prompt + completion
        return {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": total,
            "cached_tokens": cached,
            "cache_miss_tokens": cache_miss,
            "cache_write_tokens": cache_write,
        }

    meta = payload.get("usageMetadata") or payload.get("usage_metadata")
    if isinstance(meta, dict):
        prompt = _as_nonneg_int(
            meta.get("promptTokenCount") or meta.get("prompt_token_count")
        )
        completion = _as_nonneg_int(
            meta.get("candidatesTokenCount")
            or meta.get("candidates_token_count")
            or meta.get("completionTokenCount")
        )
        total = _as_nonneg_int(
            meta.get("totalTokenCount") or meta.get("total_token_count")
        )
        cached = _as_nonneg_int(
            meta.get("cachedContentTokenCount")
            or meta.get("cached_content_token_count")
        )
        u = empty_usage()
        u["prompt_tokens"] = prompt
        u["completion_tokens"] = completion
        u["total_tokens"] = total if total else (prompt + completion)
        u["cached_tokens"] = cached
        return u

    return empty_usage()


def _usage_path() -> Path:
    raw = (os.environ.get("AUTOPILOT_VISION_USAGE_DIR") or "").strip()
    if raw:
        root = Path(raw)
    else:
        try:
            from ..runtime import settings

            root = Path(settings.config_dir()) / "vision_usage"
        except (ImportError, AttributeError, OSError, TypeError, RuntimeError):
            root = Path.home() / ".autopilot" / "vision_usage"
    root.mkdir(parents=True, exist_ok=True)
    return root / f"usage-{date.today().isoformat()}.jsonl"


def record_vision_usage(
    usage: dict[str, int] | None,
    *,
    model: str = "",
) -> dict[str, int]:
    u = normalize_usage(usage)
    event = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "source": "vision",
        "model": model or "",
        "usage": u,
    }
    with _lock:
        try:
            with _usage_path().open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event, ensure_ascii=False) + "\n")
        except OSError as exc:
            log.debug("vision usage append failed: %s", exc)
    if u["total_tokens"] or u["prompt_tokens"] or u["cached_tokens"]:
        log.info(
            "vision usage model=%s prompt=%s completion=%s cached=%s miss=%s "
            "write=%s total=%s",
            model,
            u["prompt_tokens"],
            u["completion_tokens"],
            u["cached_tokens"],
            u["cache_miss_tokens"],
            u["cache_write_tokens"],
            u["total_tokens"],
        )
    return u
