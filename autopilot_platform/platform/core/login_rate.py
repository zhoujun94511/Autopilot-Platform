"""登录失败限速（防暴力破解）。

默认写入共享库表 ``login_rate_buckets``，多 worker / 多实例共库时生效（AUD-P2-005）。
无 Session 时回退进程内字典（仅单测 / 无 DB 场景）。
"""

from __future__ import annotations

import json
import threading
import time
from collections import defaultdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

_lock = threading.Lock()
# key -> 失败时间戳列表（仅 memory 回退）
_failures: dict[str, list[float]] = defaultdict(list)

# 窗口内最多失败次数；超限返回 429
WINDOW_SEC = 60.0
MAX_FAILURES = 8
LOCKOUT_SEC = 60.0


def _prune_times(times: list[float], now: float) -> list[float]:
    cutoff = now - WINDOW_SEC
    return [t for t in times if t >= cutoff]


def _prune(key: str, now: float) -> None:
    _failures[key] = _prune_times(_failures[key], now)


def _load_db_times(db: Session, key: str) -> list[float]:
    from .models import LoginRateRow, db_get

    row = db_get(db, LoginRateRow, key)
    if row is None:
        return []
    try:
        raw = json.loads(row.failures_json or "[]")
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    if not isinstance(raw, list):
        return []
    out: list[float] = []
    for item in raw:
        try:
            out.append(float(item))
        except (TypeError, ValueError):
            continue
    return out


def _save_db_times(db: Session, key: str, times: list[float]) -> None:
    from sqlalchemy.exc import IntegrityError

    from .models import LoginRateRow, db_get, utcnow

    payload = json.dumps(times)
    row = db_get(db, LoginRateRow, key)
    if row is None:
        try:
            db.add(
                LoginRateRow(
                    rate_key=key,
                    failures_json=payload,
                    updated_at=utcnow(),
                )
            )
            db.commit()
            return
        except IntegrityError:
            db.rollback()
            row = db_get(db, LoginRateRow, key)
            if row is None:
                return
    row.failures_json = payload
    row.updated_at = utcnow()
    db.commit()


def assert_login_allowed(key: str, db: Session | None = None) -> None:
    """超限时抛 PermissionError（由路由映射为 429）。"""
    from .api_messages import LOGIN_RATE_LIMITED

    now = time.time()
    if db is not None:
        times = _prune_times(_load_db_times(db, key), now)
        if len(times) >= MAX_FAILURES:
            oldest = times[0]
            wait = LOCKOUT_SEC - (now - oldest)
            if wait > 0:
                raise PermissionError(
                    LOGIN_RATE_LIMITED.format(seconds=int(wait) + 1)
                )
        return

    with _lock:
        _prune(key, now)
        times = _failures[key]
        if len(times) >= MAX_FAILURES:
            oldest = times[0]
            wait = LOCKOUT_SEC - (now - oldest)
            if wait > 0:
                raise PermissionError(
                    LOGIN_RATE_LIMITED.format(seconds=int(wait) + 1)
                )


def note_login_failure(key: str, db: Session | None = None) -> None:
    now = time.time()
    if db is not None:
        times = _prune_times(_load_db_times(db, key), now)
        times.append(now)
        _save_db_times(db, key, times)
        return
    with _lock:
        _prune(key, now)
        _failures[key].append(now)


def note_login_success(key: str, db: Session | None = None) -> None:
    if db is not None:
        from .models import LoginRateRow, db_get

        row = db_get(db, LoginRateRow, key)
        if row is not None:
            db.delete(row)
            db.commit()
        return
    with _lock:
        _failures.pop(key, None)


def reset_for_tests() -> None:
    with _lock:
        _failures.clear()
    try:
        from .db import session_factory

        factory = session_factory()
        if factory is None:
            return
        from sqlalchemy import delete

        from .models import LoginRateRow

        db = factory()
        try:
            db.execute(delete(LoginRateRow))
            db.commit()
        finally:
            db.close()
    except (OSError, RuntimeError, TypeError, ValueError, ImportError):
        pass
