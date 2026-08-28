"""RAG / Embedding 运行健康指标（进程内计数，供运维只读）。"""

from __future__ import annotations

import threading
import time
from typing import Any

_lock = threading.Lock()
_state: dict[str, Any] = {
    "embedder_name": "",
    "success_count": 0,
    "failure_count": 0,
    "last_success_at": 0.0,
    "last_failure_at": 0.0,
    "last_error": "",
    "last_fallback": "",
}


def record_success(*, embedder: str = "") -> None:
    with _lock:
        if embedder:
            _state["embedder_name"] = embedder
        _state["success_count"] = int(_state["success_count"]) + 1
        _state["last_success_at"] = time.time()


def record_failure(*, embedder: str = "", error: str = "", fallback: str = "") -> None:
    with _lock:
        if embedder:
            _state["embedder_name"] = embedder
        _state["failure_count"] = int(_state["failure_count"]) + 1
        _state["last_failure_at"] = time.time()
        _state["last_error"] = (error or "")[:500]
        if fallback:
            _state["last_fallback"] = fallback


def snapshot() -> dict[str, Any]:
    with _lock:
        out = dict(_state)
    # ISO 友好字段
    for key in ("last_success_at", "last_failure_at"):
        ts = float(out.get(key) or 0)
        out[key] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts)) if ts else ""
    return out
