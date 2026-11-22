"""E2：Job depends_on 线性依赖门禁。"""

from __future__ import annotations

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient

from autopilot_platform.platform.app import create_app
from autopilot_platform.platform.core.db import reset_engine


TOKEN = {"X-API-Token": "runner-global-token"}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "deps.db"
    url = f"sqlite:///{db_path.as_posix()}"
    monkeypatch.setenv("MC_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("MC_APP_BUILDS_DIR", str(tmp_path / "app_builds"))
    monkeypatch.setenv("MC_ADMIN_USER", "admin")
    monkeypatch.setenv("MC_ADMIN_PASSWORD", "admin")
    monkeypatch.setenv("MC_SCHEDULE_ENABLED", "0")
    monkeypatch.setenv("MC_RUNTIME_CONFIG", str(tmp_path / "mc_runtime_config.json"))
    monkeypatch.setenv("MC_JOB_LOGS_DIR", str(tmp_path / "job_logs"))
    monkeypatch.setenv("MC_API_TOKEN", "runner-global-token")
    monkeypatch.setenv("MC_ADMIN_API_TOKEN", "admin-ops-token")
    monkeypatch.delenv("MC_ENV", raising=False)
    reset_engine()
    from autopilot_platform.platform.ops.runtime_config import reload_runtime_config

    reload_runtime_config()
    app = create_app(database_url=url)
    with TestClient(app) as c:
        yield c
    reset_engine()
    reload_runtime_config()


def _ah(client: TestClient) -> dict:
    login = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "admin"}
    ).json()
    return {"Authorization": f"Bearer {login['access_token']}"}


def _seed_web_runner(client: TestClient, runner_id: str = "runner-deps") -> None:
    registered = client.post(
        "/api/v1/runners/register",
        headers=TOKEN,
        json={"runner_id": runner_id, "hostname": runner_id, "capabilities": ["web"]},
    )
    assert registered.status_code == 200, registered.text
    heartbeat = client.post(
        "/api/v1/runners/heartbeat",
        headers=TOKEN,
        json={"runner_id": runner_id, "inventory": [], "devices": [], "capabilities": ["web"]},
    )
    assert heartbeat.status_code == 200, heartbeat.text


def _claim(client: TestClient) -> dict | None:
    response = client.post("/api/v1/jobs/claim", headers=TOKEN, params={"runner_id": "runner-deps"})
    assert response.status_code == 200, response.text
    return response.json()


def _create_job(client: TestClient, ah: dict, **extra) -> dict:
    body = {
        "name": extra.pop("name", "job"),
        "project_dir": "/tmp/deps",
        "platform": "web",
        "preferred_runner_id": "runner-deps",
        "project_id": extra.pop("project_id", "p-mc"),
        **extra,
    }
    r = client.post("/api/v1/jobs", headers=ah, json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_depends_on_blocks_claim_until_succeeded(client: TestClient):
    ah = _ah(client)
    _seed_web_runner(client)
    a = _create_job(client, ah, name="A")
    b = _create_job(client, ah, name="B", depends_on=[a["id"]])
    assert b["depends_on"] == [a["id"]]

    # B 依赖未完成：只能 claim 到 A
    claimed = _claim(client)
    assert claimed is not None
    assert claimed["id"] == a["id"]

    # A 仍 claimed 时再次 claim 不应拿到 B
    again = _claim(client)
    assert again is None
    assert client.get(f"/api/v1/jobs/{b['id']}", headers=ah).json()["status"] == "pending"

    completed = client.post(
        f"/api/v1/jobs/{a['id']}/complete?runner_id=runner-deps",
        headers=TOKEN,
        json={"status": "succeeded"},
    )
    assert completed.status_code == 200, completed.text
    claimed_b = _claim(client)
    assert claimed_b is not None
    assert claimed_b["id"] == b["id"]


def test_depends_on_fails_when_parent_failed(client: TestClient):
    ah = _ah(client)
    _seed_web_runner(client)
    a = _create_job(client, ah, name="A-fail")
    b = _create_job(client, ah, name="B-child", depends_on=[a["id"]])

    claimed = _claim(client)
    assert claimed is not None
    assert claimed["id"] == a["id"]
    completed = client.post(
        f"/api/v1/jobs/{a['id']}/complete?runner_id=runner-deps",
        headers=TOKEN,
        json={"status": "failed", "error": "boom"},
    )
    assert completed.status_code == 200, completed.text
    st_b = client.get(f"/api/v1/jobs/{b['id']}", headers=ah).json()
    assert st_b["status"] == "failed"
    assert "前置任务" in (st_b.get("error") or "")

    # 不应再被 claim
    assert _claim(client) is None


def test_depends_on_missing_dep_rejected(client: TestClient):
    ah = _ah(client)
    r = client.post(
        "/api/v1/jobs",
        headers=ah,
        json={ "project_id": "p-mc",
            "name": "orphan",
            "project_dir": "/tmp/deps",
            "platform": "web",
            "depends_on": ["does-not-exist"],
        },
    )
    assert r.status_code == 404


def test_dependency_must_share_project():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from autopilot_platform.core.schemas import JobCreate
    from autopilot_platform.platform.core import api_messages as msg
    from autopilot_platform.platform.core.models import JobRow
    from autopilot_platform.platform.services.execution.jobs import create_job
    from autopilot_platform.platform.services.execution.jobs.lifecycle import (
        _deps_claim_gate,
        _fail_pending_dependents,
    )

    engine = create_engine("sqlite://")
    try:
        JobRow.__table__.create(engine)
        with Session(engine) as db:
            db.add(JobRow(id="predecessor", status="failed", project_id="other-project"))
            db.commit()
            desired_job = JobCreate(
                project_id="current-project",
                project_dir="/tmp/deps",
                platform="web",
                depends_on=["predecessor"],
            )
            with pytest.raises(LookupError, match=msg.JOB_DEPENDENCY_NOT_FOUND.format(job_id="predecessor")):
                create_job(db, desired_job)

            existing_job = JobRow(id="existing-job", status="pending", project_id="current-project")
            existing_job.depends_on = ["predecessor"]
            db.add(existing_job)
            db.flush()
            _fail_pending_dependents(db, "predecessor")
            assert existing_job.status == "pending"
            assert _deps_claim_gate(db, existing_job.depends_on, existing_job.project_id) == (
                "blocked",
                msg.JOB_DEPENDENCY_NOT_FOUND.format(job_id="predecessor"),
            )
    finally:
        engine.dispose()
