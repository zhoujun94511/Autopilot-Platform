"""需求条目 PATCH/DELETE。"""

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


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "mc_test.db"
    url = f"sqlite:///{db_path.as_posix()}"
    monkeypatch.setenv("MC_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("MC_ADMIN_USER", "admin")
    monkeypatch.setenv("MC_ADMIN_PASSWORD", "admin")
    monkeypatch.setenv("MC_SCHEDULE_ENABLED", "0")
    monkeypatch.setenv("MC_RUNTIME_CONFIG", str(tmp_path / "mc_runtime_config.json"))
    monkeypatch.setenv("MC_JOB_LOGS_DIR", str(tmp_path / "job_logs"))
    monkeypatch.setenv("MC_DATA_DIR", str(tmp_path / "data"))
    reset_engine()
    from autopilot_platform.platform.ops.runtime_config import reload_runtime_config

    reload_runtime_config()
    app = create_app(database_url=url)
    with TestClient(app) as c:
        yield c
    reset_engine()
    reload_runtime_config()


def _login(client: TestClient) -> dict:
    r = client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_requirement_update_delete(client: TestClient):
    h = _login(client)
    r = client.post(
        "/api/v1/design/requirements",
        headers=h,
        json={"project_id": "p1", "title": "登录", "content": "用户可登录", "priority": "high"},
    )
    assert r.status_code == 200, r.text
    rid = r.json()["id"]

    r = client.patch(
        f"/api/v1/design/requirements/{rid}",
        headers=h,
        json={"title": "登录校验", "priority": "medium"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["title"] == "登录校验"

    r = client.delete(f"/api/v1/design/requirements/{rid}", headers=h)
    assert r.status_code == 204, r.text

    r = client.get(f"/api/v1/design/requirements/{rid}", headers=h)
    assert r.status_code == 404


def test_rag_health_endpoint(client: TestClient):
    h = _login(client)
    r = client.get("/api/v1/ops/rag-health", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "success_count" in body
    assert "failure_count" in body
    assert "configured_mode" in body
