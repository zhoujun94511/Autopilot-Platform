"""统一错误信封单测。"""

from __future__ import annotations

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from autopilot_platform.platform.app import create_app
from autopilot_platform.platform.core.db import reset_engine


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "mc_err.db"
    monkeypatch.setenv("MC_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("MC_ADMIN_USER", "admin")
    monkeypatch.setenv("MC_ADMIN_PASSWORD", "admin")
    monkeypatch.setenv("MC_SCHEDULE_ENABLED", "0")
    monkeypatch.setenv("MC_RUNTIME_CONFIG", str(tmp_path / "mc_runtime_config.json"))
    monkeypatch.setenv("MC_JOB_LOGS_DIR", str(tmp_path / "job_logs"))
    reset_engine()
    from autopilot_platform.platform.ops.runtime_config import reload_runtime_config

    reload_runtime_config()
    app = create_app(database_url=f"sqlite:///{db_path.as_posix()}")
    with TestClient(app) as c:
        yield c


def test_error_envelope_shape_on_401(client: TestClient):
    r = client.post("/api/v1/auth/login", json={"username": "admin", "password": "nope"})
    assert r.status_code == 401
    body = r.json()
    assert set(body) >= {"code", "message", "error_type", "trace_id", "details"}
    assert body["code"] == "E4001"
    assert body["error_type"] == "auth_failed"
    assert "用户名或密码" in body["message"]
    assert isinstance(body["trace_id"], str) and body["trace_id"]


def test_error_envelope_on_missing_auth(client: TestClient):
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 401
    body = r.json()
    assert body["code"] == "E4001"
    assert body["message"]
