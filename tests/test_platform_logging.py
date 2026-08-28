"""Platform 日志与请求上下文单测。"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from autopilot_platform.platform.app import create_app
from autopilot_platform.platform.core.db import reset_engine
from autopilot_platform.platform.core.logging_setup import (
    ROOT_LOGGER,
    setup_platform_logging,
)
from autopilot_platform.platform.core.request_context import REQUEST_ID_HEADER
from list_page_helpers import page_items


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "logging.db"
    url = f"sqlite:///{db_path.as_posix()}"
    monkeypatch.setenv("MC_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("MC_APP_BUILDS_DIR", str(tmp_path / "app_builds"))
    monkeypatch.setenv("MC_ADMIN_USER", "admin")
    monkeypatch.setenv("MC_ADMIN_PASSWORD", "admin")
    monkeypatch.setenv("MC_SCHEDULE_ENABLED", "0")
    monkeypatch.setenv("MC_RUNTIME_CONFIG", str(tmp_path / "mc_runtime_config.json"))
    monkeypatch.setenv("MC_JOB_LOGS_DIR", str(tmp_path / "job_logs"))
    monkeypatch.setenv("MC_PLATFORM_LOGS_DIR", str(tmp_path / "logs"))
    monkeypatch.delenv("MC_ADMIN_API_TOKEN", raising=False)
    reset_engine()
    from autopilot_platform.platform.ops.runtime_config import reload_runtime_config

    reload_runtime_config()
    app = create_app(database_url=url)
    with TestClient(app) as c:
        yield c
    reset_engine()


def test_setup_platform_logging_writes_rotating_file(tmp_path, monkeypatch):
    monkeypatch.setenv("MC_PLATFORM_LOGS_DIR", str(tmp_path))
    monkeypatch.setenv("MC_LOG_LEVEL", "WARNING")
    path = setup_platform_logging(force=True)
    assert path
    assert Path(path).name.startswith("platform_")
    assert Path(path).parent == tmp_path

    log = logging.getLogger(f"{ROOT_LOGGER}.test")
    log.warning("platform logging smoke")
    for handler in logging.getLogger(ROOT_LOGGER).handlers:
        handler.flush()

    assert "platform logging smoke" in Path(path).read_text(encoding="utf-8")


def test_setup_platform_logging_json_format(tmp_path, monkeypatch):
    monkeypatch.setenv("MC_PLATFORM_LOGS_DIR", str(tmp_path))
    monkeypatch.setenv("MC_LOG_FORMAT", "json")
    path = setup_platform_logging(force=True)
    log = logging.getLogger(f"{ROOT_LOGGER}.json_test")
    log.error("json line")
    for handler in logging.getLogger(ROOT_LOGGER).handlers:
        handler.flush()

    lines = [ln for ln in Path(path).read_text(encoding="utf-8").splitlines() if ln.strip()]
    payload = json.loads(lines[-1])
    assert payload["level"] == "ERROR"
    assert payload["message"] == "json line"


def test_request_id_echoes_incoming_header(client: TestClient):
    rid = "trace-abc-123"
    r = client.get("/health", headers={REQUEST_ID_HEADER: rid})
    assert r.status_code == 200
    assert r.headers.get(REQUEST_ID_HEADER) == rid


def test_request_id_generated_when_missing(client: TestClient):
    r = client.get("/health")
    assert r.status_code == 200
    got = (r.headers.get(REQUEST_ID_HEADER) or "").strip()
    assert len(got) >= 8


def test_login_failure_writes_audit(client: TestClient):
    admin = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "admin"}
    ).json()
    ah = {"Authorization": f"Bearer {admin['access_token']}"}

    bad = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "wrong-password"},
    )
    assert bad.status_code == 401

    r = client.get("/api/v1/audit?action=auth.login_failed&page_size=20", headers=ah)
    assert r.status_code == 200
    items = page_items(r.json())
    assert any(x["action"] == "auth.login_failed" for x in items)
    failed = next(x for x in items if x["action"] == "auth.login_failed")
    assert failed["actor"] == "admin"
    assert "ip=" in (failed.get("detail") or "")


def test_purge_job_logs_removes_old_terminal_files(client: TestClient, tmp_path, monkeypatch):
    from datetime import timedelta

    from autopilot_platform.platform.core.models import JobRow, utcnow
    from autopilot_platform.platform.core.db import session_factory
    from autopilot_platform.platform.services.execution.jobs.lifecycle import (
        append_job_log,
        purge_job_logs,
    )

    monkeypatch.setenv("MC_JOB_LOG_RETENTION_DAYS", "30")
    log_dir = tmp_path / "job_logs"
    monkeypatch.setenv("MC_JOB_LOGS_DIR", str(log_dir))

    factory = session_factory()
    assert factory is not None
    with factory() as db:
        row = JobRow(
            id="job-old-log",
            project_id="p1",
            name="old",
            status="succeeded",
            updated_at=utcnow() - timedelta(days=60),
        )
        db.add(row)
        db.commit()

    append_job_log("job-old-log", "hello\n")
    assert (log_dir / "job-old-log.log").is_file()

    with factory() as db:
        deleted, days = purge_job_logs(db)
    assert deleted == 1
    assert days == 30
    assert not (log_dir / "job-old-log.log").is_file()


def test_purge_audit_logs_removes_old_rows(client: TestClient, monkeypatch):
    from datetime import timedelta

    from sqlalchemy import select

    from autopilot_platform.platform.core.db import session_factory
    from autopilot_platform.platform.core.models import AuditLogRow, new_id, utcnow
    from autopilot_platform.platform.ops.audit import purge_audit_logs

    monkeypatch.setenv("MC_AUDIT_LOG_RETENTION_DAYS", "30")
    factory = session_factory()
    assert factory is not None
    with factory() as db:
        db.add(
            AuditLogRow(
                id=new_id(),
                action="test.old",
                actor="system",
                created_at=utcnow() - timedelta(days=90),
            )
        )
        db.add(
            AuditLogRow(
                id=new_id(),
                action="test.new",
                actor="system",
                created_at=utcnow(),
            )
        )
        db.commit()

    with factory() as db:
        deleted, days = purge_audit_logs(db)
        remaining = list(db.scalars(select(AuditLogRow)).all())

    assert deleted == 1
    assert days == 30
    assert len(remaining) == 1
    assert remaining[0].action == "test.new"
