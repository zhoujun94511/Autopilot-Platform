"""WDA session 失效检测与恢复钩子。"""

from __future__ import annotations

from typing import Callable, Optional

_SESSION_LOST_MARKERS = (
    "invalid session id",
    "session is either terminated",
    "a session is either terminated",
    "no such driver",
)


def is_session_lost_error(message: str) -> bool:
    low = (message or "").lower()
    return any(m in low for m in _SESSION_LOST_MARKERS)


RecoverFn = Callable[[], None]


class SessionRecovery:
    """挂到 WdaClient：session 404/invalid 时调用 recover 并重试一次。"""

    def __init__(self, recover: Optional[RecoverFn] = None) -> None:
        self.recover = recover

    def maybe_recover(self, exc: Exception) -> bool:
        if self.recover is None or not is_session_lost_error(str(exc)):
            return False
        self.recover()
        return True
