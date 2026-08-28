"""IDE → 浏览器一次性交接码（不把 JWT 写进 URL）。"""

from __future__ import annotations

import hashlib
import os
import secrets
import threading
import time

# 默认 10 分钟：覆盖浏览器冷启动 / 前端首次编译，仍远短于 access token。
_DEFAULT_TTL_SEC = 600
_MIN_TTL_SEC = 120
_MAX_TTL_SEC = 1800


def handoff_ttl_sec() -> int:
    raw = os.environ.get("MC_IDE_HANDOFF_TTL_SEC", "").strip()
    if raw:
        try:
            return max(_MIN_TTL_SEC, min(_MAX_TTL_SEC, int(raw)))
        except ValueError:
            pass
    return _DEFAULT_TTL_SEC


_lock = threading.Lock()
_store: dict[str, tuple[str, float]] = {}  # sha256(code) -> (user_id, expires_at)


def _hash(code: str) -> str:
    return hashlib.sha256((code or "").encode("utf-8")).hexdigest()


def _purge_unlocked(now: float) -> None:
    dead = [k for k, (_uid, exp) in _store.items() if exp <= now]
    for k in dead:
        del _store[k]


def issue(user_id: str) -> tuple[str, int]:
    """签发一次性码；同一用户只保留最新一张。返回 (code, ttl_sec)。"""
    uid = (user_id or "").strip()
    if not uid:
        raise ValueError("user_id required")
    ttl = handoff_ttl_sec()
    raw = secrets.token_urlsafe(32)
    digest = _hash(raw)
    now = time.time()
    exp = now + ttl
    with _lock:
        _purge_unlocked(now)
        stale = [k for k, (u, _) in _store.items() if u == uid]
        for k in stale:
            del _store[k]
        _store[digest] = (uid, exp)
    return raw, ttl


def consume(code: str) -> str | None:
    """单次兑换。成功返回 user_id，失败返回 None。"""
    raw = (code or "").strip()
    if not raw:
        return None
    digest = _hash(raw)
    now = time.time()
    with _lock:
        _purge_unlocked(now)
        row = _store.pop(digest, None)
    if row is None:
        return None
    uid, exp = row
    if exp <= now:
        return None
    return uid


def reset_for_tests() -> None:
    with _lock:
        _store.clear()
