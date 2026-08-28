"""抽查修复：报告 ACL/对比、ops 设备口径、密钥掩码、告警签名。"""

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
    db_path = tmp_path / "mc_spot.db"
    url = f"sqlite:///{db_path.as_posix()}"
    monkeypatch.setenv("MC_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("MC_APP_BUILDS_DIR", str(tmp_path / "app_builds"))
    monkeypatch.setenv("MC_REPORTS_DIR", str(tmp_path / "reports"))
    monkeypatch.setenv("MC_ADMIN_USER", "admin")
    monkeypatch.setenv("MC_ADMIN_PASSWORD", "admin")
    monkeypatch.setenv("MC_SCHEDULE_ENABLED", "0")
    monkeypatch.setenv("MC_RUNTIME_CONFIG", str(tmp_path / "mc_runtime_config.json"))
    monkeypatch.setenv("MC_JOB_LOGS_DIR", str(tmp_path / "job_logs"))
    monkeypatch.delenv("MC_ADMIN_API_TOKEN", raising=False)
    reset_engine()
    from autopilot_platform.platform.ops.runtime_config import reload_runtime_config

    reload_runtime_config()
    app = create_app(database_url=url)
    with TestClient(app) as c:
        yield c
    reset_engine()
    reload_runtime_config()


def _admin(client: TestClient) -> dict:
    tok = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "admin"}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


def test_compare_case_level_new_fail_and_fixed(client: TestClient, tmp_path):
    import json

    from autopilot_platform.platform.core.db import session_factory
    from autopilot_platform.platform.core.models import JobRow, ReportRow, new_id, utcnow
    from autopilot_platform.platform.core.settings import reports_root

    _factory = session_factory()
    assert _factory is not None
    db = _factory()
    try:
        j1 = JobRow(
            id=new_id(),
            name="base",
            status="succeeded",
            project_dir="/tmp/a",
            platform="http",
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        j2 = JobRow(
            id=new_id(),
            name="new",
            status="failed",
            project_dir="/tmp/b",
            platform="http",
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        db.add(j1)
        db.add(j2)
        db.flush()
        left_dir = reports_root() / j1.id
        right_dir = reports_root() / j2.id
        left_dir.mkdir(parents=True, exist_ok=True)
        right_dir.mkdir(parents=True, exist_ok=True)
        left_json = left_dir / "result.json"
        right_json = right_dir / "result.json"
        left_json.write_text(
            json.dumps(
                {
                    "cases": [
                        {"logical_case_id": "login", "name": "login", "status": "passed"},
                        {
                            "logical_case_id": "pay",
                            "name": "pay",
                            "status": "failed",
                            "fail_class": "assertion",
                        },
                    ]
                }
            ),
            encoding="utf-8",
        )
        right_json.write_text(
            json.dumps(
                {
                    "cases": [
                        {
                            "logical_case_id": "login",
                            "name": "login",
                            "status": "failed",
                            "fail_class": "timeout",
                        },
                        {"logical_case_id": "pay", "name": "pay", "status": "passed"},
                    ]
                }
            ),
            encoding="utf-8",
        )
        db.add(
            ReportRow(
                id=new_id(),
                job_id=j1.id,
                passed=1,
                failed=1,
                total=2,
                duration_ms=100,
                result_json_path=str(left_json.resolve()),
            )
        )
        db.add(
            ReportRow(
                id=new_id(),
                job_id=j2.id,
                passed=1,
                failed=1,
                total=2,
                duration_ms=120,
                result_json_path=str(right_json.resolve()),
            )
        )
        db.commit()
        left_id, right_id = j1.id, j2.id
    finally:
        db.close()

    r = client.get(
        f"/api/v1/reports/compare?left={left_id}&right={right_id}",
        headers=TOKEN,
    )
    assert r.status_code == 200
    data = r.json()
    assert data["cases"]["available"] is True
    assert data["cases"]["counts"]["new_fail"] == 1
    assert data["cases"]["counts"]["fixed"] == 1
    assert data["verdict"] == "mixed"
    assert data["cases"]["new_fail"][0]["name"] == "login"


def test_compare_rejects_same_job(client: TestClient):
    jid = client.post(
        "/api/v1/jobs",
        headers=TOKEN,
        json={ "project_id": "p-mc","name": "c", "project_dir": "/tmp/p"},
    ).json()["id"]
    r = client.get(
        f"/api/v1/reports/compare?left={jid}&right={jid}",
        headers=TOKEN,
    )
    assert r.status_code == 400


def test_ops_summary_counts_only_online_runner_devices(client: TestClient, monkeypatch):
    from datetime import datetime, timedelta
    from typing import cast

    from autopilot_platform.platform.core.db import session_factory
    from autopilot_platform.platform.core.models import RunnerRow, utcnow
    from autopilot_platform.platform.services.shared.status import is_online

    rid = "spot-offline"
    client.post(
        "/api/v1/runners/register",
        headers=TOKEN,
        json={"runner_id": rid, "hostname": "h", "capabilities": ["android"]},
    )
    client.post(
        "/api/v1/runners/heartbeat",
        headers=TOKEN,
        json={
            "runner_id": rid,
            "inventory": [{"udid": "ghost", "platform": "android", "name": "g"}], "devices": [{"udid": "ghost", "platform": "android", "name": "g"}],
        },
    )
    # 强制离线
    _factory = session_factory()
    assert _factory is not None
    with _factory() as db:
        row = db.get(RunnerRow, rid)
        assert row is not None
        row.last_heartbeat_at = utcnow() - timedelta(hours=2)
        db.commit()
        hb = cast(datetime | None, row.last_heartbeat_at)
        assert hb is not None
        assert not is_online(hb)

    ah = _admin(client)
    data = client.get("/api/v1/ops/summary", headers=ah).json()
    assert data["devices_total"] == 0
    assert data["runners_online"] == 0


def test_ops_config_masks_secrets(client: TestClient, monkeypatch):
    monkeypatch.setenv("MC_WEBHOOK_SECRET", "super-secret-webhook")
    monkeypatch.setenv("MC_ALERT_SECRET", "super-secret-alert")
    from autopilot_platform.platform.ops.runtime_config import reload_runtime_config

    reload_runtime_config()
    ah = _admin(client)
    out = client.get("/api/v1/ops/config", headers=ah).json()
    assert out["values"]["MC_WEBHOOK_SECRET"] == "********"
    assert out["values"]["MC_ALERT_SECRET"] == "********"
    assert out["secret_configured"]["MC_WEBHOOK_SECRET"] is True
    # 保存掩码不覆盖
    client.put(
        "/api/v1/ops/config",
        headers=ah,
        json={"values": {"MC_WEBHOOK_SECRET": "********", "MC_JOB_STALE_SEC": "3600"}},
    )
    import autopilot_platform.platform.core.settings as mc_settings

    assert mc_settings.webhook_secret() == "super-secret-webhook"


def test_alert_json_uses_alert_secret(monkeypatch):
    import autopilot_platform.platform.ops.notify as notify

    monkeypatch.setenv("MC_ALERT_WEBHOOK_URL", "http://127.0.0.1:9/alert")
    monkeypatch.setenv("MC_ALERT_CHANNEL", "json")
    monkeypatch.setenv("MC_ALERT_SECRET", "alert-only")
    monkeypatch.setenv("MC_WEBHOOK_SECRET", "webhook-only")
    seen = {}

    def fake_post(_url, _payload, *, secret="", kind="", use_mc_signature=True):
        seen["secret"] = secret
        seen["kind"] = kind
        seen["use_mc_signature"] = use_mc_signature
        return True

    monkeypatch.setattr(notify, "_post", fake_post)
    ok = notify.send_alert_sync("ops.alert_test", summary="t")
    assert ok is True
    assert seen["secret"] == "alert-only"


def test_resolve_report_path_rejects_outside_root(client: TestClient, tmp_path, monkeypatch):
    from autopilot_platform.platform.core.db import session_factory
    from autopilot_platform.platform.core.models import JobRow, ReportRow, new_id
    from autopilot_platform.platform.services import reports as reports_svc

    jid = client.post(
        "/api/v1/jobs",
        headers=TOKEN,
        json={ "project_id": "p-mc","name": "r", "project_dir": "/tmp/p"},
    ).json()["id"]
    evil = tmp_path / "outside.html"
    evil.write_text("<html>x</html>", encoding="utf-8")
    _factory = session_factory()
    assert _factory is not None
    with _factory() as db:
        job = db.get(JobRow, jid)
        assert job is not None
        rep = ReportRow(id=new_id(), job_id=jid, stored_path=str(evil.resolve()))
        db.add(rep)
        db.commit()
        with pytest.raises(FileNotFoundError, match="报告路径无效|outside"):
            reports_svc.resolve_job_report_path(db, jid)
