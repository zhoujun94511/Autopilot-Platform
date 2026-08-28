"""复审遗留项（R-01…）：Runner 不得建 Job、release 告警、safe_zip 行为。"""

from __future__ import annotations

import io
import os
import sys
import zipfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient

from autopilot_platform.core.safe_zip import safe_extractall
from autopilot_platform.platform.app import create_app
from autopilot_platform.platform.core.db import reset_engine


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "mc_r.db"
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
    reset_engine()
    from autopilot_platform.platform.ops.runtime_config import reload_runtime_config

    reload_runtime_config()
    app = create_app(database_url=url)
    with TestClient(app) as c:
        yield c
    reset_engine()
    reload_runtime_config()


def test_per_runner_token_cannot_create_job(client: TestClient):
    admin_tok = {"X-API-Token": "admin-ops-token"}
    rid = "no-create-runner"
    client.post(
        "/api/v1/runners/register",
        headers=admin_tok,
        json={"runner_id": rid, "hostname": "h", "capabilities": ["android"]},
    )
    login = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "admin"}
    ).json()
    ah = {"Authorization": f"Bearer {login['access_token']}"}
    tok = client.post(f"/api/v1/runners/{rid}/token", headers=ah).json()["api_token"]
    runner_h = {"X-API-Token": tok}

    r = client.post(
        "/api/v1/jobs",
        headers=runner_h,
        json={ "project_id": "p-mc","name": "sneaky", "project_dir": "/tmp/p"},
    )
    assert r.status_code == 403


def test_execution_token_cannot_create_job_when_admin_token_split(client: TestClient):
    r = client.post(
        "/api/v1/jobs",
        headers={"X-API-Token": "runner-global-token"},
        json={ "project_id": "p-mc","name": "sneaky2", "project_dir": "/tmp/p"},
    )
    assert r.status_code == 403


def test_admin_token_can_create_job(client: TestClient):
    r = client.post(
        "/api/v1/jobs",
        headers={"X-API-Token": "admin-ops-token"},
        json={ "project_id": "p-mc","name": "ok", "project_dir": "/tmp/p"},
    )
    assert r.status_code == 200
    assert r.json()["name"] == "ok"


def test_release_device_returns_warning_when_active(client: TestClient):
    admin_tok = {"X-API-Token": "admin-ops-token"}
    rid = "rel-runner"
    client.post(
        "/api/v1/runners/register",
        headers=admin_tok,
        json={"runner_id": rid, "hostname": "h", "capabilities": ["android"]},
    )
    client.post(
        "/api/v1/runners/heartbeat",
        headers=admin_tok,
        json={
            "runner_id": rid,
            "inventory": [{"udid": "dev-rel", "platform": "android", "name": "d"}], "devices": [{"udid": "dev-rel", "platform": "android", "name": "d"}],
        },
    )
    job = client.post(
        "/api/v1/jobs",
        headers=admin_tok,
        json={ "project_id": "p-mc",
            "name": "busy",
            "project_dir": "/tmp/p",
            "device_udids": ["dev-rel"],
            "preferred_runner_id": rid,
        },
    ).json()
    client.post(f"/api/v1/jobs/claim?runner_id={rid}", headers=admin_tok)
    client.post(f"/api/v1/jobs/{job['id']}/running?runner_id={rid}", headers=admin_tok)

    r = client.post("/api/v1/devices/dev-rel/release", headers=admin_tok)
    assert r.status_code == 200
    body = r.json()
    assert body["cancelled_job_id"] == job["id"]
    assert "warning" in body
    assert "immediately" in (body["warning"] or "").lower() or "runner" in (
        body["warning"] or ""
    ).lower()


def test_mc_safe_zip_rejects_path_traversal():
    """MC 自有 safe_zip：拒绝路径穿越。"""
    from pathlib import Path
    import tempfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../x.txt", b"no")
    with tempfile.TemporaryDirectory() as d:
        with zipfile.ZipFile(io.BytesIO(buf.getvalue()), "r") as zf:
            with pytest.raises(ValueError):
                safe_extractall(zf, Path(d))
