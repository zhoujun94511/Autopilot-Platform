"""Runner 在线状态判断。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from autopilot_platform.core.constants import HEARTBEAT_TIMEOUT_SEC

from ...core.models import utcnow


def is_online(last: datetime | None, *, now: datetime | None = None) -> bool:
    if last is None:
        return False
    current = now or utcnow()
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return (current - last) <= timedelta(seconds=HEARTBEAT_TIMEOUT_SEC)
