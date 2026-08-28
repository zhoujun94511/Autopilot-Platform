"""多 Runner 同 UDID 冲突、心跳自愈注册、claim 全局排他。"""

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

from list_page_helpers import page_items

from autopilot_platform.core.constants import (
    BACKEND_ANDROID_APPIUM,
    DEFAULT_API_TOKEN,
)
from autopilot_platform.platform.app import create_app
from autopilot_platform.platform.core.db import reset_engine

TOKEN = {"X-API-Token": DEFAULT_API_TOKEN}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "mc_runner_conflict.db"
    url = f"sqlite:///{db_path.as_posix()}"
    monkeypatch.setenv("MC_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("MC_APP_BUILDS_DIR", str(tmp_path / "app_builds"))
    monkeypatch.setenv("MC_DATABASE_URL", url)
    monkeypatch.setenv("MC_ADMIN_USER", "admin")
    monkeypatch.setenv("MC_ADMIN_PASSWORD", "admin")
    monkeypatch.setenv("MC_SCHEDULE_ENABLED", "0")
    monkeypatch.setenv("MC_RUNTIME_CONFIG", str(tmp_path / "mc_runtime_config.json"))
    monkeypatch.setenv("MC_JOB_LOGS_DIR", str(tmp_path / "job_logs"))
    monkeypatch.setenv("MC_API_TOKEN", DEFAULT_API_TOKEN)
    reset_engine()
    app = create_app()
    with TestClient(app) as c:
        yield c
    reset_engine()


def _dev(udid: str = "phone-1") -> dict:
    return {
        "udid": udid,
        "platform": "android",
        "name": udid,
        "state": "ready",
        "backends": [BACKEND_ANDROID_APPIUM],
    }


def _hb(client: TestClient, rid: str, devices: list[dict] | None = None) -> None:
    r = client.post(
        "/api/v1/runners/heartbeat",
        headers=TOKEN,
        json={
            "runner_id": rid,
            "inventory": devices if devices is not None else [_dev()], "devices": devices if devices is not None else [_dev()],
            "capabilities": ["android", BACKEND_ANDROID_APPIUM],
            "host_backends": [BACKEND_ANDROID_APPIUM],
        },
    )
    assert r.status_code == 200, r.text


def _reg(client: TestClient, rid: str) -> None:
    r = client.post(
        "/api/v1/runners/register",
        headers=TOKEN,
        json={
            "runner_id": rid,
            "hostname": rid,
            "capabilities": ["android", BACKEND_ANDROID_APPIUM],
            "host_backends": [BACKEND_ANDROID_APPIUM],
        },
    )
    assert r.status_code == 200, r.text


def test_heartbeat_auto_registers_missing_runner(client: TestClient):
    """未先 register 时，heartbeat 应自愈创建 Runner。"""
    _hb(client, "orphan-runner")
    r = client.get("/api/v1/runners", headers=TOKEN)
    assert r.status_code == 200
    ids = {x["runner_id"] for x in page_items(r.json())}
    assert "orphan-runner" in ids


def test_dual_runner_same_udid_marks_conflict(client: TestClient):
    _reg(client, "runner-a")
    _reg(client, "runner-b")
    _hb(client, "runner-a")
    _hb(client, "runner-b")

    r = client.get("/api/v1/devices", headers=TOKEN)
    assert r.status_code == 200
    rows = [d for d in page_items(r.json()) if d["udid"] == "phone-1"]
    # 看板容错：同 UDID 只展示 primary 一行
    assert len(rows) == 1
    assert rows[0]["runner_id"] == "runner-a"
    assert rows[0]["state"] == "ready"
    assert rows[0].get("conflict") is False
    assert "multi-runner" not in (rows[0].get("health_note") or "")
    assert "runner-b" in (rows[0].get("alt_runner_ids") or [])

    # 库内 conflict 仍生效：非 primary 不可 claim
    j = client.post(
        "/api/v1/jobs",
        headers=TOKEN,
        json={ "project_id": "p-mc",
            "name": "shadow",
            "project_dir": str(ROOT),
            "platform": "android",
            "device_udids": ["phone-1"],
            "backend_mode": "uia2",
            "preferred_runner_id": "runner-b",
        },
    )
    assert j.status_code == 200, j.text
    c = client.post("/api/v1/jobs/claim", headers=TOKEN, params={"runner_id": "runner-b"})
    assert c.status_code == 200
    assert c.json() is None or c.text in ("", "null")


def test_dual_runner_same_udid_second_cannot_claim(client: TestClient):
    _reg(client, "runner-a")
    _reg(client, "runner-b")
    _hb(client, "runner-a")
    _hb(client, "runner-b")

    r = client.post(
        "/api/v1/jobs",
        headers=TOKEN,
        json={ "project_id": "p-mc",
            "name": "j1",
            "project_dir": str(ROOT),
            "platform": "android",
            "device_udids": ["phone-1"],
            "backend_mode": "uia2",
            "preferred_runner_id": "runner-b",
        },
    )
    assert r.status_code == 200, r.text

    # conflict 侧即便 preferred 也不得领
    c = client.post("/api/v1/jobs/claim", headers=TOKEN, params={"runner_id": "runner-b"})
    assert c.status_code == 200
    assert c.json() is None or c.text in ("", "null")

    # primary 可领
    r2 = client.post(
        "/api/v1/jobs",
        headers=TOKEN,
        json={ "project_id": "p-mc",
            "name": "j2",
            "project_dir": str(ROOT),
            "platform": "android",
            "device_udids": ["phone-1"],
            "backend_mode": "uia2",
            "preferred_runner_id": "runner-a",
        },
    )
    assert r2.status_code == 200, r2.text
    c2 = client.post("/api/v1/jobs/claim", headers=TOKEN, params={"runner_id": "runner-a"})
    assert c2.status_code == 200
    body = c2.json()
    assert body and body.get("id")
    assert body.get("runner_id") == "runner-a"


def test_offline_peer_clears_conflict_on_next_heartbeat(client: TestClient, monkeypatch):
    from datetime import timedelta

    import autopilot_platform.platform.core.models as models_mod
    from autopilot_platform.platform.core.db import session_factory
    from autopilot_platform.platform.core.models import RunnerRow

    _reg(client, "runner-a")
    _reg(client, "runner-b")
    _hb(client, "runner-a")
    _hb(client, "runner-b")

    # 人为让 runner-a 心跳过期
    _factory = session_factory()
    assert _factory is not None
    with _factory() as db:
        row = db.get(RunnerRow, "runner-a")
        assert row is not None
        row.last_heartbeat_at = models_mod.utcnow() - timedelta(seconds=600)
        db.commit()

    _hb(client, "runner-b")
    r = client.get("/api/v1/devices", headers=TOKEN)
    rows = [d for d in page_items(r.json()) if d["udid"] == "phone-1"]
    # 仅 runner-b 在线
    assert len(rows) == 1
    assert rows[0]["runner_id"] == "runner-b"
    assert rows[0]["state"] == "ready"
    assert rows[0].get("conflict") is False


def test_register_idempotent(client: TestClient):
    _reg(client, "runner-x")
    _reg(client, "runner-x")
    r = client.get("/api/v1/runners", headers=TOKEN)
    assert sum(1 for x in page_items(r.json()) if x["runner_id"] == "runner-x") == 1
