"""知识条目 PATCH/DELETE API。"""

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

from autopilot_platform.core.constants import DEFAULT_API_TOKEN
from autopilot_platform.platform.app import create_app
from autopilot_platform.platform.core.db import reset_engine

TOKEN = {"X-API-Token": DEFAULT_API_TOKEN}


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
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_knowledge_update_delete(client: TestClient):
    h = _login(client)
    r = client.post(
        "/api/v1/design/knowledge",
        headers=h,
        json={
            "project_id": "p1",
            "title": "登录提示",
            "content": "密码错误三次锁定",
            "category": "business_rules",
            "confirmed": True,
        },
    )
    assert r.status_code == 200, r.text
    kid = r.json()["id"]

    r = client.patch(
        f"/api/v1/design/knowledge/{kid}",
        headers=h,
        json={"title": "登录锁定", "confirmed": False},
    )
    assert r.status_code == 200, r.text
    assert r.json()["title"] == "登录锁定"
    assert r.json()["confirmed"] is False

    r = client.delete(f"/api/v1/design/knowledge/{kid}", headers=h)
    assert r.status_code == 204, r.text

    r = client.get(f"/api/v1/design/knowledge/{kid}", headers=h)
    assert r.status_code == 404
