"""控制面启动时的设备池 / Runner 在线态重置。

语义（对齐实验室调度常见做法）：
- **注册名单**（allowlist、DeviceRow）持久化在 DB，供执行节点页 inventory 使用；
- **在线设备看板**只认 Runner 心跳后的实时在线态；
- Platform 进程重启后，不得沿用旧心跳让节点/设备误显示为「在线」。

Runner 下次 register/heartbeat 后设备重新入池；是否启动 Runner 由用户自行决定。
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.models import RunnerRow

_log = logging.getLogger(__name__)


def reset_fleet_liveness_on_startup(db: Session) -> dict[str, int]:
    """清空 Runner 心跳戳，使调度面重启后全部节点离线直至重新上报。"""
    from ..remote.reservations import expire_reservations
    from ..remote.sessions import close_active_remote_sessions_on_startup

    cleared = 0
    for row in db.scalars(select(RunnerRow)).all():
        if row.last_heartbeat_at is not None:
            row.last_heartbeat_at = None
            cleared += 1
    expired = expire_reservations(db, commit=False)
    remote_closed = close_active_remote_sessions_on_startup(db, commit=False)
    db.commit()
    expired_n = len(expired)
    if cleared or remote_closed:
        _log.info(
            "fleet startup: cleared heartbeat on %s runner(s); "
            "reservations expired=%s; remote sessions closed=%s",
            cleared,
            expired_n,
            remote_closed,
        )
    return {
        "runners_cleared": cleared,
        "reservations_expired": expired_n,
        "remote_sessions_closed": remote_closed,
    }
