"""设计域 APPROVED webhook。"""

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
    monkeypatch.setenv("MC_DESIGN_WEBHOOK_URL", "http://127.0.0.1:9/hooks/intent")
    monkeypatch.setenv("MC_WEBHOOK_SECRET", "test-secret")
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


def test_approve_fires_design_webhook(client: TestClient, monkeypatch):
    captured: list[dict] = []

    def _fake_notify(event, *, project_id, case, override_url=""):
        captured.append(
            {"event": event, "project_id": project_id, "case": case, "url": override_url}
        )

    monkeypatch.setattr(
        "autopilot_platform.platform.ops.notify.notify_design_event",
        _fake_notify,
    )
    # design service imports notify inside function — patch there too via notify module
    h = _login(client)
    r = client.post(
        "/api/v1/design/logical-cases",
        headers=h,
        json={
            "project_id": "p-wh",
            "title": "待审",
            "logical_steps": ["点击登录"],
            "expected_results": ["ok"],
            "review_status": "AI_DRAFT",
        },
    )
    assert r.status_code == 200, r.text
    case_id = r.json()["logical_case_id"]
    assert captured == []

    r = client.patch(
        f"/api/v1/design/logical-cases/{case_id}",
        headers=h,
        json={"review_status": "APPROVED"},
    )
    assert r.status_code == 200, r.text
    assert len(captured) == 1
    assert captured[0]["event"] == "logical_case.approved"
    assert captured[0]["project_id"] == "p-wh"
    assert captured[0]["case"]["logical_case_id"] == case_id


def test_design_webhook_fallback_to_job(tmp_path, monkeypatch):
    from autopilot_platform.platform.ops.runtime_config import reload_runtime_config
    from autopilot_platform.platform.core.settings import design_webhook_url

    # 隔离运维配置文件，否则本机 data/mc_runtime_config.json 里的 webhook 会被读进来
    monkeypatch.setenv("MC_RUNTIME_CONFIG", str(tmp_path / "mc_runtime_config.json"))
    monkeypatch.delenv("MC_DESIGN_WEBHOOK_URL", raising=False)
    monkeypatch.setenv("MC_WEBHOOK_URL", "http://job.example/hook")
    monkeypatch.setenv("MC_DESIGN_WEBHOOK_USE_JOB_URL", "0")
    reload_runtime_config()
    assert design_webhook_url() == ""

    monkeypatch.setenv("MC_DESIGN_WEBHOOK_USE_JOB_URL", "1")
    reload_runtime_config()
    assert design_webhook_url() == "http://job.example/hook"
