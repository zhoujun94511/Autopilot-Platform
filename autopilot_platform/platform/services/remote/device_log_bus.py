"""远控设备日志内存总线。

浏览器 SSE 与 Runner HTTP 投递共用；**不**走 media/frame 队列，避免与画面竞态。
"""

from __future__ import annotations

import threading
import time
from collections import deque

MAX_BUFFER = 4000
MAX_LINE = 8192
REPLAY_CAP = 1000

_lock = threading.Lock()
_states: dict[str, "_State"] = {}


class _State:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.cv = threading.Condition(self.lock)
        self.lines: deque[str] = deque(maxlen=MAX_BUFFER)
        self.seq = 0
        self.subscribers = 0


def _state(session_id: str) -> _State:
    sid = (session_id or "").strip()
    with _lock:
        found = _states.get(sid)
        if found is None:
            found = _State()
            _states[sid] = found
        return found


def drop(session_id: str) -> None:
    sid = (session_id or "").strip()
    with _lock:
        _states.pop(sid, None)


def append(session_id: str, lines: list[str]) -> int:
    cleaned: list[str] = []
    for raw in lines:
        text = str(raw).replace("\r", " ").replace("\n", " ").strip()
        if not text:
            continue
        cleaned.append(text[:MAX_LINE])
    if not cleaned:
        return 0
    st = _state(session_id)
    with st.cv:
        st.lines.extend(cleaned)
        st.seq += len(cleaned)
        st.cv.notify_all()
    return len(cleaned)


def subscribe(session_id: str) -> tuple[int, list[str]]:
    st = _state(session_id)
    with st.cv:
        st.subscribers += 1
        snapshot = list(st.lines)
        if len(snapshot) > REPLAY_CAP:
            snapshot = snapshot[-REPLAY_CAP:]
        return st.seq, snapshot


def unsubscribe(session_id: str) -> int:
    st = _state(session_id)
    with st.cv:
        st.subscribers = max(0, st.subscribers - 1)
        n = st.subscribers
        st.cv.notify_all()
        return n


def subscriber_count(session_id: str) -> int:
    st = _state(session_id)
    with st.lock:
        return st.subscribers


def wait_lines(session_id: str, cursor: int, timeout: float) -> tuple[int, list[str]]:
    st = _state(session_id)
    deadline = time.monotonic() + max(0.05, float(timeout))
    with st.cv:
        while st.seq <= cursor:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return cursor, []
            st.cv.wait(remaining)
        n_new = st.seq - cursor
        buf = list(st.lines)
        out = buf if n_new >= len(buf) else buf[-n_new:]
        return st.seq, out
