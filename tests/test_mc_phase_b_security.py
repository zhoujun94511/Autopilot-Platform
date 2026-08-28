"""阶段 B 安全修复：Zip Slip、Runner ACL、设备占用、取消占用。"""

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

from list_page_helpers import page_items

from autopilot_platform.core.constants import DEFAULT_API_TOKEN
from autopilot_platform.core.safe_zip import safe_extractall
from autopilot_platform.platform.app import create_app
from autopilot_platform.platform.core.db import reset_engine

TOKEN = {"X-API-Token": DEFAULT_API_TOKEN}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "mc_sec.db"
    url = f"sqlite:///{db_path.as_posix()}"
    monkeypatch.setenv("MC_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("MC_APP_BUILDS_DIR", str(tmp_path / "app_builds"))
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


def _zip_bytes(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


def test_safe_extract_rejects_zip_slip(tmp_path):
    evil = _zip_bytes({"../evil.txt": b"pwned", "ok/a.txt": b"x"})
    dest = tmp_path / "out"
    dest.mkdir()
    with zipfile.ZipFile(io.BytesIO(evil), "r") as zf:
        with pytest.raises(ValueError, match="unsafe zip path"):
            safe_extractall(zf, dest)
    assert not (tmp_path / "evil.txt").exists()


def test_artifact_upload_rejects_zip_slip(client: TestClient):
    evil = _zip_bytes({"../evil.txt": b"pwned"})
    r = client.post(
        "/api/v1/artifacts",
        headers=TOKEN,
        files={"file": ("evil.zip", evil, "application/zip")},
        data={ "project_id": "p-mc","name": "evil"},
    )
    assert r.status_code == 400
    detail = (r.json().get("message") or r.json().get("detail") or "").lower()
    assert "unsafe" in detail or "zip" in detail


def test_runner_token_cannot_download_unassigned_artifact(client: TestClient):
    rid = "acl-runner"
    client.post(
        "/api/v1/runners/register",
        headers=TOKEN,
        json={"runner_id": rid, "hostname": "h", "capabilities": ["android"]},
    )
    admin = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "admin"}
    ).json()
    ah = {"Authorization": f"Bearer {admin['access_token']}"}
    tok = client.post(f"/api/v1/runners/{rid}/token", headers=ah).json()["api_token"]
    runner_h = {"X-API-Token": tok}

    good = _zip_bytes({"proj/a.tc.yaml": b"name: t\n"})
    art = client.post(
        "/api/v1/artifacts",
        headers=TOKEN,
        files={"file": ("p.zip", good, "application/zip")},
        data={ "project_id": "p-mc","name": "p"},
    ).json()
    aid = art["id"]

    # 未 claim：独立 Runner Token 不可下载
    r = client.get(f"/api/v1/artifacts/{aid}/download", headers=runner_h)
    assert r.status_code == 403

    # claim 后可下载
    client.post(
        "/api/v1/runners/heartbeat",
        headers=TOKEN,
        json={"runner_id": rid, "inventory": [], "devices": []},
    )
    job = client.post(
        "/api/v1/jobs",
        headers=TOKEN,
        json={ "project_id": "p-mc",
            "name": "j",
            "artifact_id": aid,
            "platform": "android",
            "preferred_runner_id": rid,
        },
    ).json()
    claimed = client.post(
        f"/api/v1/jobs/claim?runner_id={rid}", headers=runner_h
    ).json()
    assert claimed["id"] == job["id"]
    r = client.get(f"/api/v1/artifacts/{aid}/download", headers=runner_h)
    assert r.status_code == 200


def test_report_upload_requires_runner_id(client: TestClient):
    rid = "rep-runner"
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
        json={ "project_id": "p-mc","name": "r", "project_dir": "/tmp/p", "platform": "android"},
    ).json()["id"]
    client.post(f"/api/v1/jobs/claim?runner_id={rid}", headers=TOKEN)
    client.post(f"/api/v1/jobs/{jid}/running?runner_id={rid}", headers=TOKEN)
    client.post(
        f"/api/v1/jobs/{jid}/complete?runner_id={rid}",
        headers=TOKEN,
        json={"status": "succeeded"},
    )
    html = b"<html>x</html>"
    r = client.post(
        f"/api/v1/jobs/{jid}/report",
        headers=TOKEN,
        files={"file": ("report.html", html, "text/html")},
    )
    assert r.status_code == 403
    r = client.post(
        f"/api/v1/jobs/{jid}/report?runner_id={rid}",
        headers=TOKEN,
        files={"file": ("report.html", html, "text/html")},
    )
    assert r.status_code == 200


def test_cancel_running_keeps_device_busy_until_runner_ack(client: TestClient):
    rid = "busy-runner"
    udid = "dev-1"
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
            "inventory": [{"udid": udid, "platform": "android", "name": "d"}], "devices": [{"udid": udid, "platform": "android", "name": "d"}],
        },
    )
    jid = client.post(
        "/api/v1/jobs",
        headers=TOKEN,
        json={ "project_id": "p-mc",
            "name": "c",
            "project_dir": "/tmp/p",
            "platform": "android",
            "device_udids": [udid],
        },
    ).json()["id"]
    client.post(f"/api/v1/jobs/claim?runner_id={rid}", headers=TOKEN)
    client.post(f"/api/v1/jobs/{jid}/running?runner_id={rid}", headers=TOKEN)

    devices = page_items(client.get("/api/v1/devices", headers=TOKEN).json())
    assert any(d["udid"] == udid and d.get("busy") for d in devices)

    r = client.post(f"/api/v1/jobs/{jid}/cancel", headers=TOKEN)
    assert r.status_code == 200
    assert r.json()["status"] == "cancelled"

    devices = page_items(client.get("/api/v1/devices", headers=TOKEN).json())
    assert any(d["udid"] == udid and d.get("busy_job_id") == jid for d in devices)

    client.post(
        "/api/v1/jobs",
        headers=TOKEN,
        json={ "project_id": "p-mc",
            "name": "must-wait",
            "project_dir": "/tmp/p2",
            "platform": "android",
            "device_udids": [udid],
        },
    )
    assert client.post(
        f"/api/v1/jobs/claim?runner_id={rid}", headers=TOKEN
    ).json() is None

    # Runner ACK 后保持 cancelled，并在此时释放设备
    client.post(
        f"/api/v1/jobs/{jid}/complete?runner_id={rid}",
        headers=TOKEN,
        json={"status": "failed", "error": "cancelled while running"},
    )
    devices = page_items(client.get("/api/v1/devices", headers=TOKEN).json())
    assert any(d["udid"] == udid and not d.get("busy") for d in devices)


def test_occupy_devices_atomic_second_claim_fails(client: TestClient):
    rid = "occ-runner"
    udid = "shared-udid"
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
            "inventory": [{"udid": udid, "platform": "android", "name": "d"}], "devices": [{"udid": udid, "platform": "android", "name": "d"}],
        },
    )
    j1 = client.post(
        "/api/v1/jobs",
        headers=TOKEN,
        json={ "project_id": "p-mc",
            "name": "a",
            "project_dir": "/tmp/a",
            "platform": "android",
            "device_udids": [udid],
        },
    ).json()["id"]
    j2 = client.post(
        "/api/v1/jobs",
        headers=TOKEN,
        json={ "project_id": "p-mc",
            "name": "b",
            "project_dir": "/tmp/b",
            "platform": "android",
            "device_udids": [udid],
        },
    ).json()["id"]
    c1 = client.post(f"/api/v1/jobs/claim?runner_id={rid}", headers=TOKEN).json()
    assert c1["id"] == j1
    c2 = client.post(f"/api/v1/jobs/claim?runner_id={rid}", headers=TOKEN)
    # 设备忙：不应领到 j2
    assert c2.json() is None or c2.status_code == 200 and c2.json() is None
    st = client.get(f"/api/v1/jobs/{j2}", headers=TOKEN).json()["status"]
    assert st == "pending"


def test_admin_api_token_split(client: TestClient, monkeypatch, tmp_path):
    """设置 MC_ADMIN_API_TOKEN 后，全局 MC_API_TOKEN 不可访问审计。"""
    monkeypatch.setenv("MC_ADMIN_API_TOKEN", "ops-secret-token")
    monkeypatch.setenv("MC_API_TOKEN", "runner-only-token")
    # 重建 app 使 settings 生效
    reset_engine()
    from autopilot_platform.platform.ops.runtime_config import reload_runtime_config

    reload_runtime_config()
    db_path = tmp_path / "split.db"
    monkeypatch.setenv("MC_ARTIFACTS_DIR", str(tmp_path / "art2"))
    monkeypatch.setenv("MC_JOB_LOGS_DIR", str(tmp_path / "logs2"))
    monkeypatch.setenv("MC_RUNTIME_CONFIG", str(tmp_path / "rt2.json"))
    app = create_app(database_url=f"sqlite:///{db_path.as_posix()}")
    with TestClient(app) as c:
        r = c.get("/api/v1/audit", headers={"X-API-Token": "runner-only-token"})
        assert r.status_code == 403
        r = c.get("/api/v1/audit", headers={"X-API-Token": "ops-secret-token"})
        assert r.status_code == 200
    reset_engine()
    reload_runtime_config()


def test_resolve_file_under_root_rejects_outside(tmp_path):
    from autopilot_platform.platform.core.storage_paths import resolve_file_under_root

    root = tmp_path / "artifacts"
    root.mkdir()
    outside = tmp_path / "outside.zip"
    outside.write_bytes(b"data")
    with pytest.raises(PermissionError, match="outside storage root"):
        resolve_file_under_root(str(outside), root)


def test_local_artifact_store_resolve_rejects_outside(tmp_path, monkeypatch):
    from autopilot_platform.platform.artifacts.storage import (
        LocalArtifactStore,
        reset_artifact_store,
    )

    art_root = tmp_path / "artifacts"
    art_root.mkdir()
    monkeypatch.setenv("MC_ARTIFACTS_DIR", str(art_root))
    reset_artifact_store()
    evil = tmp_path / "evil.zip"
    evil.write_bytes(b"PK")
    with pytest.raises(PermissionError):
        LocalArtifactStore.resolve_zip_path(str(evil))


def test_production_global_runner_token_rejected_on_complete(client, monkeypatch):
    """生产环境：全局 MC_API_TOKEN 不得 complete；per-runner token 正常。"""
    monkeypatch.setattr(
        "autopilot_platform.platform.auth.is_production",
        lambda: True,
    )
    rid = "prod-scope-runner"
    admin = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "admin"}
    ).json()
    ah = {"Authorization": f"Bearer {admin['access_token']}"}
    client.post(
        "/api/v1/runners/register",
        headers=ah,
        json={
            "runner_id": rid,
            "hostname": "h",
            "capabilities": ["android"],
            "registration_source": "ide",
        },
    )
    runner_tok = client.post(f"/api/v1/runners/{rid}/token", headers=ah).json()[
        "api_token"
    ]
    runner_h = {"X-API-Token": runner_tok}
    client.post(
        "/api/v1/runners/heartbeat",
        headers=runner_h,
        json={"runner_id": rid, "inventory": [], "devices": []},
    )
    jid = client.post(
        "/api/v1/jobs",
        headers=TOKEN,
        json={
            "project_id": "p-mc",
            "name": "scope",
            "project_dir": "/tmp/p",
            "platform": "android",
        },
    ).json()["id"]
    client.post(f"/api/v1/jobs/claim?runner_id={rid}", headers=runner_h)
    client.post(f"/api/v1/jobs/{jid}/running?runner_id={rid}", headers=runner_h)
    r = client.post(
        f"/api/v1/jobs/{jid}/complete?runner_id={rid}",
        headers=TOKEN,
        json={"status": "succeeded"},
    )
    assert r.status_code == 403
    detail = r.json().get("message") or r.json().get("detail") or ""
    assert "Runner Token" in detail


def test_production_security_errors_require_cors_origins(monkeypatch):
    monkeypatch.setenv("MC_ENV", "production")
    monkeypatch.setenv("MC_API_TOKEN", "custom-runner-token-x")
    monkeypatch.setenv("MC_JWT_SECRET", "custom-jwt-secret-x-long-enough")
    monkeypatch.setenv("MC_ADMIN_PASSWORD", "custom-admin-pass")
    monkeypatch.setenv("MC_ADMIN_API_TOKEN", "custom-admin-api-token-x")
    monkeypatch.delenv("MC_CORS_ORIGINS", raising=False)
    from autopilot_platform.platform.core.settings import production_security_errors

    errors = production_security_errors()
    assert any("MC_CORS_ORIGINS" in err for err in errors)


def test_production_app_hides_openapi_docs(monkeypatch, tmp_path):
    monkeypatch.setenv("MC_ENV", "production")
    monkeypatch.setenv("MC_API_TOKEN", "custom-runner-token-x")
    monkeypatch.setenv("MC_JWT_SECRET", "custom-jwt-secret-x-long-enough")
    monkeypatch.setenv("MC_ADMIN_PASSWORD", "custom-admin-pass")
    monkeypatch.setenv("MC_ADMIN_API_TOKEN", "custom-admin-api-token-x")
    monkeypatch.setenv("MC_CORS_ORIGINS", "https://example.com")
    monkeypatch.setenv("MC_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("MC_APP_BUILDS_DIR", str(tmp_path / "app_builds"))
    monkeypatch.setenv("MC_JOB_LOGS_DIR", str(tmp_path / "job_logs"))
    monkeypatch.setenv("MC_RUNTIME_CONFIG", str(tmp_path / "mc_runtime_config.json"))
    monkeypatch.setenv("MC_SCHEDULE_ENABLED", "0")
    db_path = tmp_path / "prod_docs.db"
    reset_engine()
    from autopilot_platform.platform.ops.runtime_config import reload_runtime_config

    reload_runtime_config()
    app = create_app(database_url=f"sqlite:///{db_path.as_posix()}")
    with TestClient(app) as c:
        assert c.get("/docs").status_code == 404
        assert c.get("/openapi.json").status_code == 404
    reset_engine()
    reload_runtime_config()
