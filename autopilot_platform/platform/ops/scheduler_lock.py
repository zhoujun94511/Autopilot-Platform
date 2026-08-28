"""调度循环跨实例 leader 租约（AUD-P1-006）。

同一数据库上仅一个进程执行 schedule tick / stale reclaim / fleet alert。
计划单拍触发另有 ``_claim_schedule_fire``；本模块覆盖整段后台 tick。
"""

from __future__ import annotations

import logging
import os
import socket
from datetime import timedelta

from sqlalchemy import or_, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from ..core.models import OpsLockRow, db_get, utcnow
from ..core.settings import schedule_tick_sec

logger = logging.getLogger(__name__)

SCHEDULER_LOCK_NAME = "schedule_loop"


def scheduler_holder_id() -> str:
    host = socket.gethostname() or "host"
    return f"{host}:{os.getpid()}"


def scheduler_lease_ttl_sec() -> int:
    """租约略长于 tick，避免边界抖动丢 leader。"""
    return max(45, int(schedule_tick_sec()) * 3)


def try_acquire_scheduler_lease(
    db: Session,
    *,
    holder: str | None = None,
    ttl_sec: int | None = None,
) -> bool:
    """尝试续租 / 抢占 ``schedule_loop`` 锁；成功则本进程为本拍 leader。"""
    hid = (holder or scheduler_holder_id()).strip() or scheduler_holder_id()
    ttl = int(ttl_sec) if ttl_sec is not None else scheduler_lease_ttl_sec()
    ttl = max(15, ttl)
    now = utcnow()
    lease_until = now + timedelta(seconds=ttl)

    row = db_get(db, OpsLockRow, SCHEDULER_LOCK_NAME)
    if row is None:
        try:
            db.add(
                OpsLockRow(
                    name=SCHEDULER_LOCK_NAME,
                    holder=hid,
                    lease_until=lease_until,
                    updated_at=now,
                )
            )
            db.commit()
            return True
        except IntegrityError:
            db.rollback()
        except SQLAlchemyError:
            db.rollback()
            raise

    result = db.execute(
        update(OpsLockRow)
        .where(
            OpsLockRow.name == SCHEDULER_LOCK_NAME,
            or_(
                OpsLockRow.holder == hid,
                OpsLockRow.lease_until.is_(None),
                OpsLockRow.lease_until <= now,
            ),
        )
        .values(holder=hid, lease_until=lease_until, updated_at=now)
        .execution_options(synchronize_session=False)
    )
    db.commit()
    return int(getattr(result, "rowcount", 0) or 0) == 1
