"""DB 并发硬化：WAL、SSE 短 Session、唯一约束、邀请原子占用。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from typing import cast

from sqlalchemy import Table, inspect, text

from autopilot_platform.platform.app import create_app
from autopilot_platform.platform.core.db import (
    apply_concurrency_indexes,
    get_engine,
    init_db,
    reset_engine,
)
from autopilot_platform.platform.core.models import (
    DeviceRow,
    JobRow,
    OrganizationMemberRow,
    ProjectMemberRow,
    UserRow,
)

FE_JOBS = (
    Path(ROOT)
    / "autopilot_platform"
    / "platform"
    / "api"
    / "jobs.py"
)
FE_DESIGN = (
    Path(ROOT)
    / "autopilot_platform"
    / "platform"
    / "services"
    / "design"
    / "cases"
    / "generation.py"
)
FE_INVITES = (
    Path(ROOT)
    / "autopilot_platform"
    / "platform"
    / "tenancy"
    / "project_invites.py"
)
FE_USERS = (
    Path(ROOT)
    / "autopilot_platform"
    / "platform"
    / "artifacts"
    / "users_artifacts.py"
)


def test_job_log_sse_does_not_hold_request_session():
    src = FE_JOBS.read_text(encoding="utf-8")
    chunk = src.split("def api_stream_job_logs")[1].split("def api_cancel_job")[0]
    assert "db: Session = Depends(get_session)" not in chunk
    assert "session_factory()" in chunk
    assert "db.close()" in chunk
    assert "job_is_terminal" in chunk


def test_design_ends_txn_before_llm_and_sqlite_serializes_parallel():
    src = FE_DESIGN.read_text(encoding="utf-8")
    assert "db.commit()" in src.split("def _generate_logical_cases_inner")[1].split(
        "generate_logical_case_drafts"
    )[0]
    assert "sqlite_single_writer" in src
    assert "database_url().startswith('sqlite')" in src


def test_invite_consume_is_conditional_update():
    src = FE_INVITES.read_text(encoding="utf-8")
    assert "def _consume_invite_use" in src
    assert "use_count < ProjectInviteRow.max_uses" in src
    assert "rowcount" in src
    users = FE_USERS.read_text(encoding="utf-8")
    assert "IntegrityError" in users
    assert "AUTH_USERNAME_EXISTS" in users


def test_orm_unique_constraints_declared():
    org_table = cast(Table, inspect(OrganizationMemberRow).local_table)
    proj_table = cast(Table, inspect(ProjectMemberRow).local_table)
    dev_table = cast(Table, inspect(DeviceRow).local_table)
    org_names = {c.name for c in org_table.constraints if c.name}
    proj_names = {c.name for c in proj_table.constraints if c.name}
    dev_names = {c.name for c in dev_table.constraints if c.name}
    assert "uq_org_member_user" in org_names
    assert "uq_project_member_user" in proj_names
    assert "uq_device_runner_udid" in dev_names
    job_idx = {i.name for i in cast(Table, JobRow.__table__).indexes}
    user_idx = {i.name for i in cast(Table, UserRow.__table__).indexes}
    assert "ix_jobs_status_created_at" in job_idx
    assert "uq_users_oidc_sub" in user_idx
    assert "uq_users_saml_nameid" in user_idx


def test_file_sqlite_enables_wal_and_concurrency_indexes(tmp_path, monkeypatch):
    db_path = tmp_path / "wal.db"
    url = f"sqlite:///{db_path.as_posix()}"
    monkeypatch.setenv("MC_SCHEDULE_ENABLED", "0")
    monkeypatch.setenv("MC_ADMIN_USER", "admin")
    monkeypatch.setenv("MC_ADMIN_PASSWORD", "admin")
    monkeypatch.setenv("MC_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("MC_JOB_LOGS_DIR", str(tmp_path / "job_logs"))
    monkeypatch.setenv("MC_RUNTIME_CONFIG", str(tmp_path / "rt.json"))
    monkeypatch.setenv("MC_DATA_DIR", str(tmp_path / "data"))
    reset_engine()
    init_db(url)
    engine = get_engine()
    with engine.connect() as conn:
        mode = str(conn.execute(text("PRAGMA journal_mode")).scalar() or "").lower()
        timeout = int(conn.execute(text("PRAGMA busy_timeout")).scalar() or 0)
        idx = {row[1] for row in conn.execute(text("PRAGMA index_list('organization_members')"))}
        job_idx = {row[1] for row in conn.execute(text("PRAGMA index_list('jobs')"))}
        device_idx = {row[1] for row in conn.execute(text("PRAGMA index_list('devices')"))}
    reset_engine()
    assert mode == "wal"
    assert timeout >= 30000
    assert "uq_org_member_user" in idx
    assert "ix_jobs_status_created_at" in job_idx
    assert "uq_device_runner_udid" in device_idx


def test_memory_sqlite_still_bootstraps(monkeypatch):
    monkeypatch.delenv("MC_ENV", raising=False)
    monkeypatch.setenv("MC_HOST", "127.0.0.1")
    monkeypatch.setenv("MC_ALLOW_LEGACY_TOKEN_ADMIN", "1")
    for name in ("MC_API_TOKEN", "MC_JWT_SECRET", "MC_ADMIN_PASSWORD", "MC_ADMIN_API_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    reset_engine()
    app = create_app(database_url="sqlite:///:memory:")
    assert app is not None
    engine = get_engine()
    names = set(inspect(engine).get_table_names())
    reset_engine()
    assert "users" in names
    assert "jobs" in names


def test_apply_concurrency_indexes_is_idempotent(tmp_path, monkeypatch):
    db_path = tmp_path / "idx.db"
    url = f"sqlite:///{db_path.as_posix()}"
    monkeypatch.setenv("MC_SCHEDULE_ENABLED", "0")
    reset_engine()
    init_db(url)
    engine = get_engine()
    with engine.begin() as conn:
        apply_concurrency_indexes(conn)
        apply_concurrency_indexes(conn)
    reset_engine()


def test_apply_concurrency_indexes_skips_legacy_devices_without_runner_id(tmp_path):
    from sqlalchemy import create_engine

    from autopilot_platform.platform.core.db import migrate_schema

    engine = create_engine(f"sqlite:///{(tmp_path / 'legacy.sqlite').as_posix()}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE devices (id VARCHAR(64) PRIMARY KEY)"))
        conn.execute(text("INSERT INTO devices (id) VALUES ('d1')"))
    migrate_schema(engine)
    with engine.connect() as conn:
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(devices)"))}
        idx = {row[1] for row in conn.execute(text("PRAGMA index_list('devices')"))}
    assert "id" in cols
    assert "uq_device_runner_udid" not in idx
