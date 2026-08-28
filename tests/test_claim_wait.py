"""B1-T：POST /jobs/claim?wait_sec= 长轮询。"""

from __future__ import annotations

import os
import sys
import threading
import time

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
    db_path = tmp_path / "mc_claim_wait.db"
    url = f"sqlite:///{db_path.as_posix()}"
    monkeypatch.setenv("MC_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
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


def _ready_runner(client: TestClient, rid: str) -> None:
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


def test_claim_wait_sec_zero_immediate_null(client: TestClient):
    rid = "r-wait-0"
    _ready_runner(client, rid)
    t0 = time.monotonic()
    r = client.post(
        "/api/v1/jobs/claim",
        headers=TOKEN,
        params={"runner_id": rid, "wait_sec": 0},
    )
    assert r.status_code == 200
    assert r.json() is None
    assert time.monotonic() - t0 < 1.5


def test_claim_wait_timeout_null(client: TestClient):
    rid = "r-wait-to"
    _ready_runner(client, rid)
    t0 = time.monotonic()
    r = client.post(
        "/api/v1/jobs/claim",
        headers=TOKEN,
        params={"runner_id": rid, "wait_sec": 2},
    )
    assert r.status_code == 200
    assert r.json() is None
    elapsed = time.monotonic() - t0
    assert elapsed >= 1.5
    assert elapsed < 5.0


def test_claim_wait_gets_job_created_during_wait(client: TestClient):
    rid = "r-wait-job"
    _ready_runner(client, rid)

    result: dict = {}

    def _claim() -> None:
        r = client.post(
            "/api/v1/jobs/claim",
            headers=TOKEN,
            params={"runner_id": rid, "wait_sec": 8},
        )
        result["status"] = r.status_code
        result["body"] = r.json()

    th = threading.Thread(target=_claim, daemon=True)
    th.start()
    time.sleep(0.4)
    created = client.post(
        "/api/v1/jobs",
        headers=TOKEN,
        json={ "project_id": "p-mc","name": "during-wait", "project_dir": "/tmp/p", "platform": "android"},
    )
    assert created.status_code == 200
    jid = created.json()["id"]
    th.join(timeout=12)
    assert result.get("status") == 200
    body = result.get("body") or {}
    assert body.get("id") == jid


def test_claim_immediate_still_works(client: TestClient):
    rid = "r-imm"
    _ready_runner(client, rid)
    jid = client.post(
        "/api/v1/jobs",
        headers=TOKEN,
        json={ "project_id": "p-mc","name": "imm", "project_dir": "/tmp/p", "platform": "android"},
    ).json()["id"]
    r = client.post(f"/api/v1/jobs/claim?runner_id={rid}", headers=TOKEN)
    assert r.status_code == 200
    assert r.json()["id"] == jid
