"""舰队健康告警（薄版）：Runner 离线边沿 + 设备池清空边沿 + 冷却。"""

from __future__ import annotations

import logging
import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ...core.models import DeviceRow, RunnerRow, utcnow
from ...core.settings import (
    alert_on_device_empty,
    alert_on_runner_offline,
    alert_runner_offline_cooldown_sec,
    alert_webhook_url,
)
from ..shared import BEST_EFFORT_ERRS, is_online

logger = logging.getLogger(__name__)

# 进程内边沿状态；重启后不告警历史离线，避免冷启动风暴
_last_online: dict[str, bool] = {}
_last_alert_mono: dict[str, float] = {}
_last_online_device_count: int | None = None
_device_empty_alert_mono: float = 0.0

_DEVICE_EMPTY_KEY = "__device_pool_empty__"


def reset_fleet_alert_state() -> None:
    """测试用：清空边沿与冷却记忆。"""
    global _last_online_device_count, _device_empty_alert_mono
    _last_online.clear()
    _last_alert_mono.clear()
    _last_online_device_count = None
    _device_empty_alert_mono = 0.0


def runner_offline_cooldown_sec() -> int:

    return alert_runner_offline_cooldown_sec()


def check_runner_offline_alerts(db: Session) -> list[str]:
    """扫描 Runner：若某节点由在线变为离线则告警。

    返回本次发出告警的 runner_id 列表（便于单测/日志）。
    """

    if not alert_on_runner_offline():
        return []
    if not alert_webhook_url():
        return []

    now = utcnow()
    cooldown = max(60, int(runner_offline_cooldown_sec()))
    rows = list(db.scalars(select(RunnerRow)).all())
    newly: list[tuple[str, str]] = []
    mono = time.monotonic()

    for row in rows:
        rid = str(row.runner_id or "").strip()
        if not rid:
            continue
        online = is_online(row.last_heartbeat_at, now=now)
        prev = _last_online.get(rid)
        _last_online[rid] = online
        if prev is not True or online:
            continue
        last = _last_alert_mono.get(rid, 0.0)
        if mono - last < cooldown:
            continue
        _last_alert_mono[rid] = mono
        label = str(row.hostname or "").strip() or rid
        newly.append((rid, label))

    if not newly:
        return []

    ids = [r for r, _ in newly]
    try:
        from ...ops.notify import notify_alert  # 延迟：通知通道可选

        detail: dict[str, Any] = {
            "runner_ids": ids[:20],
            "count": len(ids),
        }
        if len(newly) == 1:
            summary = f"Runner 离线: {newly[0][1]} ({newly[0][0]})"
        else:
            summary = f"{len(newly)} 个 Runner 离线: {', '.join(ids[:5])}"
        notify_alert("runners.offline", summary=summary, detail=detail)
    except BEST_EFFORT_ERRS as exc:
        logger.warning("runner offline alert failed: %s", exc)
    return ids


def _count_online_runners(db: Session, *, now) -> int:
    n = 0
    for row in db.scalars(select(RunnerRow)).all():
        if is_online(row.last_heartbeat_at, now=now):
            n += 1
    return n


def _count_online_devices(db: Session, *, now) -> int:
    rows = list(
        db.scalars(select(DeviceRow).options(selectinload(DeviceRow.runner))).all()
    )
    n = 0
    for d in rows:
        r = d.runner
        if r is not None and is_online(r.last_heartbeat_at, now=now):
            n += 1
    return n


def check_device_pool_empty_alerts(db: Session) -> bool:
    """在线 Runner>0 且在线设备数由 >0 变为 0 时告警。

    返回是否发出告警。
    """
    global _last_online_device_count, _device_empty_alert_mono


    if not alert_on_device_empty():
        return False
    if not alert_webhook_url():
        return False

    now = utcnow()
    online_runners = _count_online_runners(db, now=now)
    online_devices = _count_online_devices(db, now=now)
    prev = _last_online_device_count
    _last_online_device_count = online_devices

    if prev is None or prev <= 0 or online_devices > 0:
        return False
    if online_runners <= 0:
        # 无在线 Runner 时由 Runner 离线告警覆盖，避免双响
        return False

    cooldown = max(60, int(runner_offline_cooldown_sec()))
    mono = time.monotonic()
    if mono - _device_empty_alert_mono < cooldown:
        return False
    _device_empty_alert_mono = mono
    _last_alert_mono[_DEVICE_EMPTY_KEY] = mono

    try:
        from ...ops.notify import notify_alert  # 延迟：通知通道可选

        notify_alert(
            "devices.pool_empty",
            summary=f"在线设备池已清空（仍有 {online_runners} 个 Runner 在线）",
            detail={
                "online_runners": online_runners,
                "prev_online_devices": prev,
                "online_devices": online_devices,
            },
        )
    except BEST_EFFORT_ERRS as exc:
        logger.warning("device pool empty alert failed: %s", exc)
    return True


def tick_fleet_alerts(db: Session) -> dict[str, Any]:
    """scheduler 单次调用：Runner 离线 + 设备池清空。"""
    offline_ids = check_runner_offline_alerts(db)
    empty = check_device_pool_empty_alerts(db)
    return {"runner_offline": offline_ids, "device_pool_empty": empty}
