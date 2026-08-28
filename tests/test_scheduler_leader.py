"""AUD-P1-006：schedule_loop DB leader 租约。"""

from __future__ import annotations

import os
import sys
from datetime import timedelta

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from autopilot_platform.platform.core.db import init_db, reset_engine, session_factory
from autopilot_platform.platform.core.models import OpsLockRow, db_get, utcnow
from autopilot_platform.platform.ops.scheduler_lock import (
    SCHEDULER_LOCK_NAME,
    try_acquire_scheduler_lease,
)


@pytest.fixture()
def db(tmp_path, monkeypatch):
    db_path = tmp_path / "scheduler_lock.db"
    url = f"sqlite:///{db_path.as_posix()}"
    monkeypatch.setenv("MC_DATABASE_URL", url)
    monkeypatch.setenv("MC_SCHEDULE_ENABLED", "0")
    monkeypatch.setenv("MC_SCHEDULE_TICK_SEC", "15")
    reset_engine()
    init_db(url)
    factory = session_factory()
    assert factory is not None
    session = factory()
    try:
        yield session
    finally:
        session.close()
        reset_engine()


def test_scheduler_lease_exclusive(db):
    assert try_acquire_scheduler_lease(db, holder="a:1", ttl_sec=60) is True
    assert try_acquire_scheduler_lease(db, holder="b:2", ttl_sec=60) is False
    # 持有者可续租
    assert try_acquire_scheduler_lease(db, holder="a:1", ttl_sec=60) is True
    row = db_get(db, OpsLockRow, SCHEDULER_LOCK_NAME)
    assert row is not None
    assert row.holder == "a:1"


def test_scheduler_lease_steal_when_expired(db):
    assert try_acquire_scheduler_lease(db, holder="a:1", ttl_sec=60) is True
    row = db_get(db, OpsLockRow, SCHEDULER_LOCK_NAME)
    assert row is not None
    row.lease_until = utcnow() - timedelta(seconds=5)
    db.commit()
    assert try_acquire_scheduler_lease(db, holder="b:2", ttl_sec=60) is True
    row = db_get(db, OpsLockRow, SCHEDULER_LOCK_NAME)
    assert row is not None
    assert row.holder == "b:2"
