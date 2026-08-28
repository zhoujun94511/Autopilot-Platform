"""Sonic Plan B1-L / B1-P 本轮补齐：reclaim 审计、孤儿 busy、报告 purge。"""

from __future__ import annotations

import os
import sys
from datetime import timedelta
from pathlib import Path

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient
from sqlalchemy import select

from autopilot_platform.core.constants import DEFAULT_API_TOKEN, JobStatus
from autopilot_platform.platform.app import create_app
from autopilot_platform.platform.core.db import reset_engine, session_factory
from autopilot_platform.platform.core.models import DeviceRow, JobRow, ReportRow, new_id, utcnow
from list_page_helpers import page_items

TOKEN = {"X-API-Token": DEFAULT_API_TOKEN}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "mc_sonic_b1.db"
    url = f"sqlite:///{db_path.as_posix()}"
    monkeypatch.setenv("MC_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("MC_REPORTS_DIR", str(tmp_path / "reports"))
    monkeypatch.setenv("MC_ADMIN_USER", "admin")
    monkeypatch.setenv("MC_ADMIN_PASSWORD", "admin")
    monkeypatch.setenv("MC_SCHEDULE_ENABLED", "0")
    monkeypatch.setenv("MC_RUNTIME_CONFIG", str(tmp_path / "mc_runtime_config.json"))
    monkeypatch.setenv("MC_JOB_LOGS_DIR", str(tmp_path / "job_logs"))
    reset_engine()
    from autopilot_platform.platform.ops.runtime_config import reload_runtime_config

    reload_runtime_config()
    app = create_app(database_url=url)
    with TestClient(app) as c:
        yield c
    reset_engine()
    reload_runtime_config()


def _admin_headers(client: TestClient) -> dict:
    admin = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "admin"}
    ).json()
    return {"Authorization": f"Bearer {admin['access_token']}"}


def test_scheduler_reclaim_writes_system_audit(client: TestClient):
    """模拟 scheduler_loop：reclaim 后写 actor_kind=system 的 job.reclaim。"""
    rid = "r-sched-audit"
    client.post(
        "/api/v1/runners/register",
        headers=TOKEN,
        json={"runner_id": rid, "hostname": "h", "capabilities": ["android"]},
    )
    jid = client.post(
        "/api/v1/jobs",
        headers=TOKEN,
        json={ "project_id": "p-mc","name": "stale-aud", "project_dir": "/tmp/p", "platform": "android"},
    ).json()["id"]
    client.post(f"/api/v1/jobs/claim?runner_id={rid}", headers=TOKEN)

    factory = session_factory()
    assert factory is not None
    db = factory()
    try:
        from autopilot_platform.platform.core.models import RunnerRow

        job = db.get(JobRow, jid)
        assert job is not None
        job.updated_at = utcnow() - timedelta(seconds=7200)
        runner = db.get(RunnerRow, rid)
        assert runner is not None
        runner.last_heartbeat_at = utcnow() - timedelta(seconds=7200)
        db.commit()
    finally:
        db.close()

    from autopilot_platform.platform.services.execution.jobs.recovery import reclaim_stale_jobs
    from autopilot_platform.platform.ops import audit as audit_svc

    factory = session_factory()
    assert factory is not None
    db = factory()
    try:
        stale = reclaim_stale_jobs(db)
        assert jid in stale
        # 与 scheduler_loop 相同的审计落点
        audit_svc.write_audit(
            db,
            action="job.reclaim",
            actor="scheduler",
            actor_kind="system",
            resource_type="job",
            detail=f"count={len(stale)};job_ids={','.join(stale[:20])}",
        )
    finally:
        db.close()

    ah = _admin_headers(client)
    rows = page_items(client.get("/api/v1/audit?limit=100", headers=ah).json())
    hit = [
        x
        for x in rows
        if x.get("action") == "job.reclaim" and x.get("actor_kind") == "system"
    ]
    assert hit, rows
    assert hit[0].get("actor") == "scheduler"


def test_orphan_busy_cleared_on_reconcile(client: TestClient):
    rid = "r-orphan-busy"
    client.post(
        "/api/v1/runners/register",
        headers=TOKEN,
        json={"runner_id": rid, "hostname": "h"},
    )
    client.post(
        "/api/v1/runners/heartbeat",
        headers=TOKEN,
        json={
            "runner_id": rid,
            "inventory": [{"udid": "dev-orphan", "platform": "android"}], "devices": [{"udid": "dev-orphan", "platform": "android"}],
        },
    )
    jid = client.post(
        "/api/v1/jobs",
        headers=TOKEN,
        json={ "project_id": "p-mc",
            "name": "orphan",
            "project_dir": "/tmp/p",
            "device_udids": ["dev-orphan"],
            "preferred_runner_id": rid,
        },
    ).json()["id"]
    assert (
        client.post(f"/api/v1/jobs/claim?runner_id={rid}", headers=TOKEN).json()["id"]
        == jid
    )

    factory = session_factory()
    assert factory is not None
    db = factory()
    try:
        job = db.get(JobRow, jid)
        assert job is not None
        job.status = JobStatus.FAILED.value
        db.commit()
        d = db.scalar(
            select(DeviceRow).where(
                DeviceRow.udid == "dev-orphan", DeviceRow.runner_id == rid
            )
        )
        assert d is not None
        assert d.busy_job_id == jid
    finally:
        db.close()

    from autopilot_platform.platform.services.execution.devices.operations import (
        reconcile_orphan_device_busy,
    )

    factory = session_factory()
    assert factory is not None
    db = factory()
    try:
        cleared = reconcile_orphan_device_busy(db)
        assert "dev-orphan" in cleared
        d = db.scalar(
            select(DeviceRow).where(
                DeviceRow.udid == "dev-orphan", DeviceRow.runner_id == rid
            )
        )
        assert d is not None
        assert d.busy_job_id is None
    finally:
        db.close()


def test_job_report_purge_terminal_only(client: TestClient, monkeypatch):
    monkeypatch.setenv("MC_JOB_REPORT_RETENTION_DAYS", "30")
    from autopilot_platform.platform.ops.runtime_config import reload_runtime_config

    reload_runtime_config()

    rid = "r-rep-purge"
    client.post(
        "/api/v1/runners/register",
        headers=TOKEN,
        json={"runner_id": rid, "hostname": "h", "capabilities": ["android"]},
    )
    client.post(
        "/api/v1/runners/heartbeat",
        headers=TOKEN,
        json={"runner_id": rid, "inventory": [], "devices": []},
    )
    jid = client.post(
        "/api/v1/jobs",
        headers=TOKEN,
        json={ "project_id": "p-mc","name": "rep-purge", "project_dir": "/tmp/p", "platform": "android"},
    ).json()["id"]
    client.post(f"/api/v1/jobs/claim?runner_id={rid}", headers=TOKEN)
    client.post(f"/api/v1/jobs/{jid}/running?runner_id={rid}", headers=TOKEN)
    client.post(
        f"/api/v1/jobs/{jid}/complete?runner_id={rid}",
        headers=TOKEN,
        json={
            "status": "succeeded",
            "report": {
                "report_path": "/runner/local/report.html",
                "passed": 1,
                "failed": 0,
                "total": 1,
                "duration_ms": 10,
                "summary": "ok",
            },
        },
    )
    html = b"<html>purge-me</html>"
    r = client.post(
        f"/api/v1/jobs/{jid}/report?runner_id={rid}",
        headers=TOKEN,
        files={"file": ("report.html", html, "text/html")},
    )
    assert r.status_code == 200
    assert client.get(f"/api/v1/jobs/{jid}/report", headers=TOKEN).status_code == 200

    factory = session_factory()
    assert factory is not None
    db = factory()
    try:
        rep = db.scalar(select(ReportRow).where(ReportRow.job_id == jid))
        assert rep is not None
        rep.created_at = utcnow() - timedelta(days=60)
        db.commit()
    finally:
        db.close()

    ah = _admin_headers(client)
    r = client.post("/api/v1/reports/purge?older_than_days=30", headers=ah)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["deleted"] >= 1
    assert body["older_than_days"] == 30
    assert client.get(f"/api/v1/jobs/{jid}/report", headers=TOKEN).status_code == 404

    reports_dir = Path(os.environ["MC_REPORTS_DIR"]) / jid
    assert not reports_dir.is_dir()

    rows = page_items(client.get("/api/v1/audit?limit=50", headers=ah).json())
    assert any(x.get("action") == "report.purge" for x in rows)


def test_scheduler_auto_purge_reports_when_retention_set(client: TestClient, monkeypatch):
    """scheduler tick 在 retention>0 时调用 purge_job_reports。"""
    monkeypatch.setenv("MC_JOB_REPORT_RETENTION_DAYS", "30")
    from autopilot_platform.platform.ops.runtime_config import reload_runtime_config

    reload_runtime_config()

    rid = "r-auto-purge"
    client.post(
        "/api/v1/runners/register",
        headers=TOKEN,
        json={"runner_id": rid, "hostname": "h", "capabilities": ["android"]},
    )
    jid = client.post(
        "/api/v1/jobs",
        headers=TOKEN,
        json={ "project_id": "p-mc","name": "auto-purge", "project_dir": "/tmp/p", "platform": "android"},
    ).json()["id"]
    client.post(f"/api/v1/jobs/claim?runner_id={rid}", headers=TOKEN)
    client.post(f"/api/v1/jobs/{jid}/running?runner_id={rid}", headers=TOKEN)
    client.post(
        f"/api/v1/jobs/{jid}/complete?runner_id={rid}",
        headers=TOKEN,
        json={
            "status": "succeeded",
            "report": {
                "report_path": "r.html",
                "passed": 1,
                "failed": 0,
                "total": 1,
                "duration_ms": 1,
                "summary": "ok",
            },
        },
    )
    client.post(
        f"/api/v1/jobs/{jid}/report?runner_id={rid}",
        headers=TOKEN,
        files={"file": ("report.html", b"<html>x</html>", "text/html")},
    )

    factory = session_factory()
    assert factory is not None
    db = factory()
    try:
        rep = db.scalar(select(ReportRow).where(ReportRow.job_id == jid))
        assert rep is not None
        rep.created_at = utcnow() - timedelta(days=60)
        db.commit()
    finally:
        db.close()

    from autopilot_platform.platform.services.reports.storage import purge_job_reports

    factory = session_factory()
    assert factory is not None
    db = factory()
    try:
        deleted, days = purge_job_reports(db)
        assert deleted >= 1
        assert days == 30
    finally:
        db.close()

    assert client.get(f"/api/v1/jobs/{jid}/report", headers=TOKEN).status_code == 404


def test_job_report_purge_skips_running(client: TestClient, monkeypatch):
    monkeypatch.setenv("MC_JOB_REPORT_RETENTION_DAYS", "1")
    from autopilot_platform.platform.ops.runtime_config import reload_runtime_config

    reload_runtime_config()

    rid = "r-rep-run"
    client.post(
        "/api/v1/runners/register",
        headers=TOKEN,
        json={"runner_id": rid, "hostname": "h", "capabilities": ["android"]},
    )
    jid = client.post(
        "/api/v1/jobs",
        headers=TOKEN,
        json={ "project_id": "p-mc","name": "running-rep", "project_dir": "/tmp/p", "platform": "android"},
    ).json()["id"]
    client.post(f"/api/v1/jobs/claim?runner_id={rid}", headers=TOKEN)
    client.post(f"/api/v1/jobs/{jid}/running?runner_id={rid}", headers=TOKEN)

    factory = session_factory()
    assert factory is not None
    db = factory()
    try:
        db.add(
            ReportRow(
                id=new_id(),
                job_id=jid,
                report_path="x",
                stored_path="",
                created_at=utcnow() - timedelta(days=10),
            )
        )
        db.commit()
    finally:
        db.close()

    ah = _admin_headers(client)
    r = client.post("/api/v1/reports/purge?older_than_days=1", headers=ah)
    assert r.status_code == 200
    assert r.json()["deleted"] == 0

    factory = session_factory()
    assert factory is not None
    db = factory()
    try:
        still = db.scalar(select(ReportRow).where(ReportRow.job_id == jid))
        assert still is not None
    finally:
        db.close()
