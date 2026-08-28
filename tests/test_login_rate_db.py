"""AUD-P2-005：登录限速跨 Session 共享（模拟多 worker）。"""

from __future__ import annotations

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

pytest.importorskip("sqlalchemy")

from autopilot_platform.platform.core.db import init_db, reset_engine, session_factory
from autopilot_platform.platform.core.login_rate import (
    MAX_FAILURES,
    assert_login_allowed,
    note_login_failure,
    note_login_success,
    reset_for_tests,
)


@pytest.fixture()
def db_factory(tmp_path, monkeypatch):
    db_path = tmp_path / "login_rate.db"
    url = f"sqlite:///{db_path.as_posix()}"
    monkeypatch.setenv("MC_DATABASE_URL", url)
    monkeypatch.setenv("MC_SCHEDULE_ENABLED", "0")
    reset_engine()
    init_db(url)
    reset_for_tests()
    factory = session_factory()
    assert factory is not None
    yield factory
    reset_for_tests()
    reset_engine()


def test_login_rate_shared_across_sessions(db_factory):
    key = "127.0.0.1|attacker"
    for _ in range(MAX_FAILURES):
        db = db_factory()
        try:
            note_login_failure(key, db)
        finally:
            db.close()
    db = db_factory()
    try:
        with pytest.raises(PermissionError):
            assert_login_allowed(key, db)
    finally:
        db.close()
    db = db_factory()
    try:
        note_login_success(key, db)
        assert_login_allowed(key, db)  # 成功后清桶
    finally:
        db.close()
