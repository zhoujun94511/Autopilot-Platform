"""AutoPilot Platform Platform API 单测（临时 SQLite）。"""

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

from autopilot_platform.core.constants import DEFAULT_API_TOKEN, JobStatus
from autopilot_platform.platform.app import create_app
from autopilot_platform.platform.core.db import reset_engine

from list_page_helpers import page_items

TOKEN = {"X-API-Token": DEFAULT_API_TOKEN}


def create_org_project(client, headers, *, org_id, project_id, name=None):
    """测试夹具：先建组织再建模，满足项目必须有 org_id。"""
    client.post("/api/v1/orgs", headers=headers, json={"id": org_id, "name": org_id})
    return client.post(
        "/api/v1/projects",
        headers={**headers, "X-Org-Id": org_id},
        json={"id": project_id, "name": name or project_id, "org_id": org_id},
    )


def api_error_message(resp) -> str:
    """读取统一错误信封的 message（兼容旧 detail）。"""
    try:
        body = resp.json()
    except (ValueError, TypeError):
        return resp.text or ""
    if not isinstance(body, dict):
        return str(body)
    return str(body.get("message") or body.get("detail") or "")


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
    reset_engine()
    from autopilot_platform.platform.ops.runtime_config import reload_runtime_config

    reload_runtime_config()
    app = create_app(database_url=url)
    with TestClient(app) as c:
        yield c
    reset_engine()
    reload_runtime_config()


def test_health_no_token(client: TestClient):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_auth_required(client: TestClient):
    r = client.get("/api/v1/runners")
    assert r.status_code == 401


def test_register_heartbeat_devices_job_flow(client: TestClient):
    rid = "runner-test-1"
    r = client.post(
        "/api/v1/runners/register",
        headers=TOKEN,
        json={
            "runner_id": rid,
            "hostname": "host-a",
            "version": "0.1.0",
            "capabilities": ["android"],
        },
    )
    assert r.status_code == 200
    assert r.json()["runner_id"] == rid
    assert r.json()["online"] is True

    r = client.post(
        "/api/v1/runners/heartbeat",
        headers=TOKEN,
        json={
            "runner_id": rid,
            "status": "idle",
            "inventory": [
                {"udid": "emu-1", "platform": "android", "name": "Pixel"},
            ], "devices": [
                {"udid": "emu-1", "platform": "android", "name": "Pixel"},
            ],
        },
    )
    assert r.status_code == 200

    r = client.get("/api/v1/devices", headers=TOKEN)
    assert r.status_code == 200
    devices = page_items(r.json())
    assert len(devices) == 1
    assert devices[0]["udid"] == "emu-1"
    assert devices[0]["runner_id"] == rid

    r = client.post(
        "/api/v1/jobs",
        headers=TOKEN,
        json={ "project_id": "p-mc",
            "name": "batch-1",
            "project_dir": str(os.path.join(ROOT, "tests", "sample")),
            "platform": "android",
            "device_udids": ["emu-1"],
            "preferred_runner_id": rid,
        },
    )
    assert r.status_code == 200
    job = r.json()
    job_id = job["id"]
    assert job["status"] == JobStatus.PENDING.value

    r = client.post(f"/api/v1/jobs/claim?runner_id={rid}", headers=TOKEN)
    assert r.status_code == 200
    claimed = r.json()
    assert claimed is not None
    assert claimed["id"] == job_id
    assert claimed["status"] == JobStatus.CLAIMED.value
    assert claimed["runner_id"] == rid

    # 无更多 pending
    r = client.post(f"/api/v1/jobs/claim?runner_id={rid}", headers=TOKEN)
    assert r.status_code == 200
    assert r.json() is None

    r = client.post(f"/api/v1/jobs/{job_id}/running?runner_id={rid}", headers=TOKEN)
    assert r.status_code == 200
    assert r.json()["status"] == JobStatus.RUNNING.value

    r = client.post(
        f"/api/v1/jobs/{job_id}/complete?runner_id={rid}",
        headers=TOKEN,
        json={
            "status": "succeeded",
            "report": {
                "report_path": "/tmp/report.html",
                "passed": 1,
                "failed": 0,
                "total": 1,
                "duration_ms": 10,
                "summary": "ok",
            },
        },
    )
    assert r.status_code == 200
    assert r.json()["status"] == JobStatus.SUCCEEDED.value

    r = client.get("/api/v1/reports", headers=TOKEN)
    assert r.status_code == 200
    reports = page_items(r.json())
    assert len(reports) == 1
    assert reports[0]["report_path"] == "/tmp/report.html"
    assert reports[0]["passed"] == 1


def test_offline_runner_devices_hidden(client: TestClient, monkeypatch):
    from autopilot_platform.platform.services.execution.devices import scheduling

    rid = "runner-stale"
    client.post(
        "/api/v1/runners/register",
        headers=TOKEN,
        json={"runner_id": rid, "hostname": "h"},
    )
    client.post(
        "/api/v1/runners/heartbeat",
        headers=TOKEN,
        json={
            "runner_id": rid,
            "inventory": [{"udid": "x", "platform": "ios"}], "devices": [{"udid": "x", "platform": "ios"}],
        },
    )
    # 强制判定离线
    monkeypatch.setattr(scheduling, "is_online", lambda *_a, **_k: False)
    r = client.get("/api/v1/devices", headers=TOKEN)
    assert page_items(r.json()) == []


def test_preferred_runner_skips_other(client: TestClient):
    client.post(
        "/api/v1/runners/register",
        headers=TOKEN,
        json={"runner_id": "r-a", "hostname": "a"},
    )
    client.post(
        "/api/v1/runners/register",
        headers=TOKEN,
        json={"runner_id": "r-b", "hostname": "b"},
    )
    client.post(
        "/api/v1/jobs",
        headers=TOKEN,
        json={ "project_id": "p-mc",
            "name": "only-a",
            "project_dir": "/tmp/proj",
            "preferred_runner_id": "r-a",
        },
    )
    r = client.post("/api/v1/jobs/claim?runner_id=r-b", headers=TOKEN)
    assert r.json() is None
    r = client.post("/api/v1/jobs/claim?runner_id=r-a", headers=TOKEN)
    assert r.json()["runner_id"] == "r-a"


def test_spa_index_and_static(client: TestClient):
    """需先在 autopilot_platform/frontend 执行 npm run build。"""
    from pathlib import Path

    dist = Path(__file__).resolve().parents[1] / "autopilot_platform" / "frontend" / "dist"
    if not (dist / "index.html").is_file():
        pytest.skip("Vue dist missing; run: cd autopilot_platform/frontend && npm run build")

    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")
    cache = (r.headers.get("cache-control") or "").lower()
    assert "no-cache" in cache or "no-store" in cache
    body = r.content.decode("utf-8")
    assert "AutoPilot" in body
    assert "/assets/" in body

    # Vite 产物：/assets/*.js
    import re

    m = re.search(r'/assets/[^"\']+\.js', body)
    assert m, "expected hashed js asset in index"
    r = client.get(m.group(0))
    assert r.status_code == 200

    r = client.get("/brand/autopilot.png")
    assert r.status_code == 200
    assert r.headers.get("content-type", "").startswith("image/")


def test_cancel_job_and_device_busy(client: TestClient):
    rid = "runner-busy-1"
    client.post(
        "/api/v1/runners/register",
        headers=TOKEN,
        json={"runner_id": rid, "hostname": "h"},
    )
    client.post(
        "/api/v1/runners/heartbeat",
        headers=TOKEN,
        json={
            "runner_id": rid,
            "inventory": [{"udid": "dev-a", "platform": "android"}], "devices": [{"udid": "dev-a", "platform": "android"}],
        },
    )
    r = client.post(
        "/api/v1/jobs",
        headers=TOKEN,
        json={ "project_id": "p-mc",
            "name": "j1",
            "project_dir": "/tmp/p",
            "device_udids": ["dev-a"],
            "preferred_runner_id": rid,
        },
    )
    job_id = r.json()["id"]

    r = client.post(f"/api/v1/jobs/claim?runner_id={rid}", headers=TOKEN)
    assert r.json()["id"] == job_id
    r = client.get("/api/v1/devices", headers=TOKEN)
    dev0 = page_items(r.json())[0]
    assert dev0["busy"] is True
    assert dev0["busy_job_id"] == job_id
    assert dev0["busy_job_name"] == "j1"
    assert dev0["busy_job_status"] == "claimed"

    r = client.get("/api/v1/devices/board", headers=TOKEN)
    assert r.status_code == 200
    board = r.json()
    assert board["summary"]["online"] == 1
    assert board["summary"]["busy"] == 1
    assert board["summary"]["free"] == 0
    assert board["summary"]["by_platform"]["android"]["busy"] == 1

    # 同设备第二任务不应被 claim
    client.post(
        "/api/v1/jobs",
        headers=TOKEN,
        json={ "project_id": "p-mc",
            "name": "j2",
            "project_dir": "/tmp/p2",
            "device_udids": ["dev-a"],
            "preferred_runner_id": rid,
        },
    )
    r = client.post(f"/api/v1/jobs/claim?runner_id={rid}", headers=TOKEN)
    assert r.json() is None

    admin = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "admin"}
    ).json()
    ah = {"Authorization": f"Bearer {admin['access_token']}"}
    r = client.post("/api/v1/devices/dev-a/release", headers=ah)
    assert r.status_code == 200
    body = r.json()
    assert body["released_job_id"] == job_id
    assert body["cancelled_job_id"] == job_id
    assert body["cleared"] is False
    r = client.get("/api/v1/devices", headers=TOKEN)
    assert page_items(r.json())[0]["busy"] is True
    # release 联动取消任务，但等 Runner ACK 后才清 busy
    r = client.get(f"/api/v1/jobs/{job_id}", headers=TOKEN)
    assert r.json()["status"] == "cancelled"
    r = client.post(
        f"/api/v1/jobs/{job_id}/complete?runner_id={rid}",
        headers=TOKEN,
        json={"status": "failed", "error": "cancel acknowledged"},
    )
    assert r.status_code == 200
    assert page_items(client.get("/api/v1/devices", headers=TOKEN).json())[0]["busy"] is False


def test_operator_cannot_create_admin(client: TestClient):
    # 先用 admin 建 operator
    login = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "admin"}
    ).json()
    admin_h = {"Authorization": f"Bearer {login['access_token']}"}
    r = client.post(
        "/api/v1/auth/users",
        headers=admin_h,
        json={"username": "op1", "password": "op1pass12", "duty": "user"},
    )
    assert r.status_code == 200

    op = client.post(
        "/api/v1/auth/login", json={"username": "op1", "password": "op1pass12"}
    ).json()
    op_h = {"Authorization": f"Bearer {op['access_token']}"}
    r = client.post(
        "/api/v1/auth/users",
        headers=op_h,
        json={"username": "x", "password": "xxxx1234", "duty": "sys_admin"},
    )
    assert r.status_code == 403


def test_project_membership_soft_tenant(client: TestClient):
    admin = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "admin"}
    ).json()
    ah = {"Authorization": f"Bearer {admin['access_token']}"}
    client.post(
        "/api/v1/auth/users",
        headers=ah,
        json={"username": "alice", "password": "alice123", "duty": "user"},
    )
    client.post(
        "/api/v1/auth/users",
        headers=ah,
        json={"username": "bob", "password": "bob12345", "duty": "user"},
    )
    r = create_org_project(
        client, ah, org_id="org-team", project_id="team-x", name="Team X"
    )
    # admin created but owner is admin user_id — add alice as member via admin
    assert r.status_code == 200
    r = client.post(
        "/api/v1/projects/team-x/members",
        headers=ah,
        json={"username": "alice", "role": "member"},
    )
    assert r.status_code == 200

    alice = client.post(
        "/api/v1/auth/login", json={"username": "alice", "password": "alice123"}
    ).json()
    alice_h = {"Authorization": f"Bearer {alice['access_token']}"}
    bob = client.post(
        "/api/v1/auth/login", json={"username": "bob", "password": "bob12345"}
    ).json()
    bob_h = {"Authorization": f"Bearer {bob['access_token']}"}

    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("a.txt", "1")
    data = buf.getvalue()

    r = client.post(
        "/api/v1/artifacts",
        headers=alice_h,
        files={"file": ("a.zip", data, "application/zip")},
        data={"name": "a", "project_id": "team-x"},
    )
    assert r.status_code == 200

    r = client.post(
        "/api/v1/artifacts",
        headers=bob_h,
        files={"file": ("b.zip", data, "application/zip")},
        data={"name": "b", "project_id": "team-x"},
    )
    assert r.status_code == 403

    r = client.get("/api/v1/projects", headers=bob_h)
    assert all(p["id"] != "team-x" for p in page_items(r.json()))
    r = client.get("/api/v1/projects", headers=alice_h)
    assert any(p["id"] == "team-x" for p in page_items(r.json()))


def test_cors_preflight_allows_dev_origin(client: TestClient):
    r = client.options(
        "/api/v1/runners",
        headers={
            "Origin": "http://127.0.0.1:5173",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "X-API-Token",
        },
    )
    assert r.status_code in (200, 204)
    assert r.headers.get("access-control-allow-origin") == "http://127.0.0.1:5173"


def test_login_jwt_and_me(client: TestClient):
    r = client.post("/api/v1/auth/login", json={"username": "admin", "password": "wrong"})
    assert r.status_code == 401
    body = r.json()
    assert body.get("code") == "E4001"
    assert body.get("error_type") == "auth_failed"
    assert "用户名或密码" in (body.get("message") or "")
    assert body.get("trace_id")

    r = client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin"})
    assert r.status_code == 200
    body = r.json()
    assert body["access_token"]
    assert body["user"]["username"] == "admin"
    assert body["user"]["role"] == "admin"

    headers = {"Authorization": f"Bearer {body['access_token']}"}
    r = client.get("/api/v1/auth/me", headers=headers)
    assert r.status_code == 200
    assert r.json()["username"] == "admin"

    r = client.get("/api/v1/runners", headers=headers)
    assert r.status_code == 200


def test_artifact_upload_and_job(client: TestClient, tmp_path):
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("demo/readme.txt", "hello")
    buf.seek(0)

    r = client.post(
        "/api/v1/artifacts",
        headers=TOKEN,
        files={"file": ("demo.zip", buf.getvalue(), "application/zip")},
        data={"name": "demo-art", "project_id": "space-a"},
    )
    assert r.status_code == 200
    art = r.json()
    assert art["name"] == "demo-art"
    assert art["project_id"] == "space-a"
    aid = art["id"]

    r = client.get("/api/v1/artifacts", headers=TOKEN)
    assert any(x["id"] == aid for x in page_items(r.json()))

    r = client.get("/api/v1/artifacts?project_id=space-a", headers=TOKEN)
    assert any(x["id"] == aid for x in page_items(r.json()))
    r = client.get("/api/v1/artifacts?project_id=other", headers=TOKEN)
    assert all(x["id"] != aid for x in page_items(r.json()))

    r = client.get(f"/api/v1/artifacts/{aid}/download", headers=TOKEN)
    assert r.status_code == 200
    assert r.content[:2] == b"PK"

    r = client.post(
        "/api/v1/jobs",
        headers=TOKEN,
        json={
            "name": "from-art",
            "artifact_id": aid,
            "platform": "android",
            "project_id": "space-a",
        },
    )
    assert r.status_code == 200
    job = r.json()
    assert job["artifact_id"] == aid
    assert job["project_id"] == "space-a"
    assert job["project_dir"]  # filled from extract_path

    r = client.get("/api/v1/jobs?project_id=space-a", headers=TOKEN)
    assert any(j["id"] == job["id"] for j in page_items(r.json()))


def test_artifact_upload_over_limit_returns_413(client: TestClient, monkeypatch):
    monkeypatch.setenv("MC_ARTIFACT_MAX_MB", "1")
    response = client.post(
        "/api/v1/artifacts",
        headers=TOKEN,
        files={"file": ("too-large.zip", b"x" * (1024 * 1024 + 1), "application/zip")},
    )
    assert response.status_code == 413


def test_artifact_entries_and_job_entry_paths(client: TestClient):
    """制品只暴露用例清单；Job 可带 entry_paths。"""
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("AIID/TEST001.tc.yaml", "name: t1\n")
        zf.writestr("AIID/TEST002.tc.yaml", "name: t2\n")
        zf.writestr("AIID/config/DataConfig.properties", "k=v\n")
        zf.writestr("AIID/images/btn.png", b"\x89PNG")
    buf.seek(0)

    r = client.post(
        "/api/v1/artifacts",
        headers=TOKEN,
        files={"file": ("AIID.zip", buf.getvalue(), "application/zip")},
        data={"name": "aiid", "project_id": "space-a"},
    )
    assert r.status_code == 200
    aid = r.json()["id"]

    r = client.get(f"/api/v1/artifacts/{aid}/entries", headers=TOKEN)
    assert r.status_code == 200
    entries = r.json()
    paths = [e["path"] for e in entries]
    assert paths == ["TEST001.tc.yaml", "TEST002.tc.yaml"]
    assert all(e["kind"] == "case" for e in entries)
    assert not any("config" in e["path"] or "images" in e["path"] for e in entries)

    r = client.post(
        "/api/v1/jobs",
        headers=TOKEN,
        json={
            "name": "picked",
            "artifact_id": aid,
            "platform": "android",
            "project_id": "space-a",
            "entry_paths": ["TEST002.tc.yaml"],
        },
    )
    assert r.status_code == 200
    job = r.json()
    assert job["entry_paths"] == ["TEST002.tc.yaml"]

    r = client.get(f"/api/v1/jobs/{job['id']}", headers=TOKEN)
    assert r.status_code == 200
    assert r.json()["entry_paths"] == ["TEST002.tc.yaml"]


def test_app_build_upload_and_job(client: TestClient):
    """应用资源独立域：上传/去重/校验/列表/改名/下载/删除，并可挂到 Job。"""
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("AndroidManifest.xml", "minimal")
    payload = buf.getvalue()
    assert payload.startswith(b"PK")

    r = client.post(
        "/api/v1/app-builds",
        headers=TOKEN,
        files={"file": ("demo.apk", payload, "application/vnd.android.package-archive")},
        data={"name": "demo-app", "project_id": "space-a"},
    )
    assert r.status_code == 200, r.text
    build = r.json()
    assert build["name"] == "demo-app"
    assert build["platform"] == "android"
    assert build["filename"] == "demo.apk"
    assert build["size_bytes"] == len(payload)
    assert build["sha256"]
    assert build.get("reused") is False
    bid = build["id"]

    # sha256 去重：同项目再传同一包 → 复用
    r = client.post(
        "/api/v1/app-builds",
        headers=TOKEN,
        files={"file": ("demo-again.apk", payload, "application/vnd.android.package-archive")},
        data={"name": "should-reuse", "project_id": "space-a"},
    )
    assert r.status_code == 200
    reused = r.json()
    assert reused["id"] == bid
    assert reused["reused"] is True

    # 非 ZIP 魔数拒收
    r = client.post(
        "/api/v1/app-builds",
        headers=TOKEN,
        files={"file": ("bad.apk", b"not-a-zip", "application/octet-stream")},
        data={ "project_id": "p-mc","name": "bad"},
    )
    assert r.status_code == 400

    r = client.get("/api/v1/app-builds", headers=TOKEN)
    assert any(x["id"] == bid for x in page_items(r.json()))
    r = client.get("/api/v1/app-builds?project_id=space-a", headers=TOKEN)
    assert any(x["id"] == bid for x in page_items(r.json()))
    r = client.get("/api/v1/app-builds?project_id=other", headers=TOKEN)
    assert all(x["id"] != bid for x in page_items(r.json()))

    r = client.patch(
        f"/api/v1/app-builds/{bid}",
        headers=TOKEN,
        json={"name": "demo-app-renamed"},
    )
    assert r.status_code == 200
    assert r.json()["name"] == "demo-app-renamed"

    r = client.get(f"/api/v1/app-builds/{bid}/download", headers=TOKEN)
    assert r.status_code == 200
    assert r.content == payload

    # 工程源仍必需；应用资源挂在 Job 上
    r = client.post(
        "/api/v1/jobs",
        headers=TOKEN,
        json={
            "name": "with-app",
            "project_dir": "/tmp/p",
            "app_build_id": bid,
            "platform": "android",
            "project_id": "space-a",
        },
    )
    assert r.status_code == 200
    job = r.json()
    assert job["app_build_id"] == bid

    # pending 任务仍引用 app_build：删除应 409；终态后可删
    r = client.delete(f"/api/v1/app-builds/{bid}", headers=TOKEN)
    assert r.status_code == 409
    from autopilot_platform.platform.core.db import session_factory
    from autopilot_platform.platform.core.models import JobRow
    from autopilot_platform.core.constants import JobStatus

    _factory = session_factory()
    assert _factory is not None
    db = _factory()
    try:
        row = db.get(JobRow, job["id"])
        assert row is not None
        row.status = JobStatus.SUCCEEDED.value
        db.commit()
    finally:
        db.close()

    r = client.delete(f"/api/v1/app-builds/{bid}", headers=TOKEN)
    assert r.status_code == 204
    r = client.get(f"/api/v1/app-builds/{bid}", headers=TOKEN)
    assert r.status_code == 404


def test_app_build_purge_and_acl(client: TestClient):
    """应用资源超期清理 + ACL 分享。"""
    import io
    import zipfile
    from datetime import timedelta

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("payload.bin", "x")
    payload = buf.getvalue()

    # 注册 bob
    r = client.post(
        "/api/v1/auth/users",
        headers=TOKEN,
        json={"username": "bob-app", "password": "bob12345", "duty": "user"},
    )
    assert r.status_code in (200, 409)

    r = client.post(
        "/api/v1/auth/login",
        json={"username": "bob-app", "password": "bob12345"},
    )
    assert r.status_code == 200
    bob_h = {"Authorization": f"Bearer {r.json()['access_token']}"}

    admin = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "admin"}
    ).json()
    ah = {"Authorization": f"Bearer {admin['access_token']}"}
    assert (
        create_org_project(client, ah, org_id="org-mc", project_id="p-mc").status_code
        == 200
    )
    assert (
        client.post(
            "/api/v1/orgs/org-mc/members",
            headers=ah,
            json={"username": "bob-app", "role": "member"},
        ).status_code
        == 200
    )

    r = client.post(
        "/api/v1/app-builds",
        headers=TOKEN,
        files={"file": ("priv.apk", payload, "application/octet-stream")},
        data={ "project_id": "p-mc","name": "private-app"},
    )
    assert r.status_code == 200
    bid = r.json()["id"]

    r = client.get(f"/api/v1/app-builds/{bid}", headers=bob_h)
    assert r.status_code == 403

    r = client.post(
        "/api/v1/acl",
        headers=TOKEN,
        json={
            "resource_type": "app_build",
            "resource_id": bid,
            "username": "bob-app",
            "permission": "read",
        },
    )
    assert r.status_code == 200, r.text
    r = client.get(f"/api/v1/app-builds/{bid}", headers=bob_h)
    assert r.status_code == 200

    # purge：拨回 created_at
    from autopilot_platform.platform.core.db import session_factory
    from autopilot_platform.platform.core.models import AppBuildRow, utcnow

    _factory = session_factory()
    assert _factory is not None
    db = _factory()
    try:
        row = db.get(AppBuildRow, bid)
        assert row is not None
        row.created_at = utcnow() - timedelta(days=120)
        db.commit()
    finally:
        db.close()

    r = client.post("/api/v1/app-builds/purge?older_than_days=30", headers=TOKEN)
    assert r.status_code == 200
    assert r.json()["deleted"] >= 1
    r = client.get(f"/api/v1/app-builds/{bid}", headers=TOKEN)
    assert r.status_code == 404


def test_job_retry_and_webhook(client: TestClient, monkeypatch):
    captured: list[tuple] = []

    def _capture(event, job, *, report=None, override_url=""):
        captured.append((event, job["id"], override_url, report))

    monkeypatch.setattr(
        "autopilot_platform.platform.ops.notify.notify_job_event",
        _capture,
    )

    r = client.post(
        "/api/v1/jobs",
        headers=TOKEN,
        json={ "project_id": "p-mc",
            "name": "retry-me",
            "project_dir": "/tmp/p",
            "platform": "android",
            "webhook_url": "http://example.invalid/hook",
        },
    )
    assert r.status_code == 200
    jid = r.json()["id"]
    assert r.json()["webhook_url"].endswith("/hook")

    r = client.post(f"/api/v1/jobs/{jid}/cancel", headers=TOKEN)
    assert r.status_code == 200
    assert r.json()["status"] == JobStatus.CANCELLED.value
    assert any(e[0] == "job.cancelled" and e[1] == jid for e in captured)

    r = client.post(f"/api/v1/jobs/{jid}/retry", headers=TOKEN)
    assert r.status_code == 200
    child = r.json()
    assert child["status"] == JobStatus.PENDING.value
    assert child["parent_job_id"] == jid
    assert child["id"] != jid
    assert child["webhook_url"].endswith("/hook")

    r = client.post(f"/api/v1/jobs/{jid}/retry", headers=TOKEN)
    assert r.status_code == 200  # terminal can retry again


def test_artifact_delete_and_purge(client: TestClient):
    import io
    import zipfile
    from datetime import timedelta

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("a.txt", "1")
    data = buf.getvalue()

    r = client.post(
        "/api/v1/artifacts",
        headers=TOKEN,
        files={"file": ("a.zip", data, "application/zip")},
        data={ "project_id": "p-mc","name": "to-del"},
    )
    assert r.status_code == 200
    aid = r.json()["id"]

    r = client.delete(f"/api/v1/artifacts/{aid}", headers=TOKEN)
    assert r.status_code == 204
    r = client.get(f"/api/v1/artifacts/{aid}", headers=TOKEN)
    assert r.status_code == 404

    r = client.post(
        "/api/v1/artifacts",
        headers=TOKEN,
        files={"file": ("b.zip", data, "application/zip")},
        data={ "project_id": "p-mc","name": "old"},
    )
    old_id = r.json()["id"]

    # 把 created_at 拨回以便 purge
    from autopilot_platform.platform.core.db import session_factory
    from autopilot_platform.platform.core.models import ArtifactRow, utcnow

    _factory = session_factory()
    assert _factory is not None
    db = _factory()
    try:
        row = db.get(ArtifactRow, old_id)
        assert row is not None
        row.created_at = utcnow() - timedelta(days=40)
        db.commit()
    finally:
        db.close()

    admin = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "admin"}
    ).json()
    ah = {"Authorization": f"Bearer {admin['access_token']}"}
    r = client.post("/api/v1/artifacts/purge?older_than_days=30", headers=ah)
    assert r.status_code == 200
    assert r.json()["deleted"] >= 1
    assert r.json()["older_than_days"] == 30
    r = client.get(f"/api/v1/artifacts/{old_id}", headers=TOKEN)
    assert r.status_code == 404


def test_artifact_delete_rejects_active_job_reference(client: TestClient):
    import io
    import zipfile

    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("case.tc.yaml", "name: case\n")
    artifact = client.post(
        "/api/v1/artifacts",
        headers=TOKEN,
        files={"file": ("active.zip", archive.getvalue(), "application/zip")},
        data={"project_id": "p-mc"},
    ).json()
    job = client.post(
        "/api/v1/jobs",
        headers=TOKEN,
        json={ "project_id": "p-mc","name": "active", "artifact_id": artifact["id"], "platform": "android"},
    )
    assert job.status_code == 200
    response = client.delete(f"/api/v1/artifacts/{artifact['id']}", headers=TOKEN)
    assert response.status_code == 409
    assert client.get(f"/api/v1/artifacts/{artifact['id']}", headers=TOKEN).status_code == 200


def test_resource_acl_private_and_share(client: TestClient):
    import io
    import zipfile

    admin = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "admin"}
    ).json()
    ah = {"Authorization": f"Bearer {admin['access_token']}"}
    client.post(
        "/api/v1/auth/users",
        headers=ah,
        json={"username": "alice", "password": "alice123", "duty": "user"},
    )
    client.post(
        "/api/v1/auth/users",
        headers=ah,
        json={"username": "bob", "password": "bob12345", "duty": "user"},
    )
    alice = client.post(
        "/api/v1/auth/login", json={"username": "alice", "password": "alice123"}
    ).json()
    alice_h = {"Authorization": f"Bearer {alice['access_token']}"}
    bob = client.post(
        "/api/v1/auth/login", json={"username": "bob", "password": "bob12345"}
    ).json()
    bob_h = {"Authorization": f"Bearer {bob['access_token']}"}

    r = create_org_project(
        client, ah, org_id="org-art", project_id="alice-art", name="Alice Art"
    )
    assert r.status_code == 200, r.text
    client.post(
        "/api/v1/projects/alice-art/members",
        headers=ah,
        json={"username": "alice", "role": "member"},
    )
    assert (
        client.post(
            "/api/v1/orgs/org-art/members",
            headers=ah,
            json={"username": "bob", "role": "member"},
        ).status_code
        == 200
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("x.txt", "1")
    data = buf.getvalue()

    r = client.post(
        "/api/v1/artifacts",
        headers=alice_h,
        files={"file": ("p.zip", data, "application/zip")},
        data={"name": "private", "project_id": "alice-art"},
    )
    assert r.status_code == 200
    aid = r.json()["id"]

    r = client.get("/api/v1/artifacts", headers=bob_h)
    assert all(x["id"] != aid for x in page_items(r.json()))
    r = client.get(f"/api/v1/artifacts/{aid}", headers=bob_h)
    assert r.status_code == 403

    r = client.post(
        "/api/v1/acl",
        headers=alice_h,
        json={
            "resource_type": "artifact",
            "resource_id": aid,
            "username": "bob",
            "permission": "read",
        },
    )
    assert r.status_code == 200
    acl_id = r.json()["id"]

    r = client.get(f"/api/v1/artifacts/{aid}", headers=bob_h)
    assert r.status_code == 200
    r = client.get("/api/v1/artifacts", headers=bob_h)
    assert any(x["id"] == aid for x in page_items(r.json()))

    # read ACL 不能删
    r = client.delete(f"/api/v1/artifacts/{aid}", headers=bob_h)
    assert r.status_code == 403

    r = client.delete(f"/api/v1/acl/{acl_id}", headers=alice_h)
    assert r.status_code == 204
    r = client.get(f"/api/v1/artifacts/{aid}", headers=bob_h)
    assert r.status_code == 403


def test_schedule_create_tick_and_stop_on_fail(client: TestClient):
    admin = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "admin"}
    ).json()
    ah = {"Authorization": f"Bearer {admin['access_token']}"}

    r = client.post(
        "/api/v1/schedules",
        headers=ah,
        json={ "project_id": "p-mc",
            "name": "nightly",
            "project_dir": "/tmp/suite",
            "platform": "android",
            "delay_sec": 0,
            "interval_sec": 0,
            "repeat": 1,
            "enabled": True,
            "device_udids": ["dev-a"],
        },
    )
    assert r.status_code == 200
    sid = r.json()["id"]
    assert r.json()["enabled"] is True
    assert r.json()["next_run_at"]

    r = client.post("/api/v1/schedules-tick", headers=ah)
    assert r.status_code == 200
    job_ids = r.json()
    assert len(job_ids) == 1

    r = client.get(f"/api/v1/jobs/{job_ids[0]}", headers=ah)
    assert r.status_code == 200
    assert r.json()["created_by"] == "admin"
    assert r.json().get("device_udids") == ["dev-a"]

    r = client.get(f"/api/v1/schedules/{sid}", headers=ah)
    assert r.status_code == 200
    assert r.json()["runs_done"] == 1
    assert r.json()["enabled"] is False  # one-shot done
    assert r.json()["last_job_id"] == job_ids[0]

    # 周期 + stop_on_fail
    r = client.post(
        "/api/v1/schedules",
        headers=ah,
        json={ "project_id": "p-mc",
            "name": "loop",
            "project_dir": "/tmp/suite",
            "delay_sec": 0,
            "interval_sec": 60,
            "repeat": 5,
            "stop_on_fail": True,
            "enabled": True,
        },
    )
    sid2 = r.json()["id"]
    r = client.post(f"/api/v1/schedules/{sid2}/run-now", headers=ah)
    assert r.status_code == 200
    assert r.json()["runs_done"] == 1
    last = r.json()["last_job_id"]
    assert last
    assert r.json()["enabled"] is True

    # 模拟任务失败 → 计划停
    rid = "sched-runner"
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
    from autopilot_platform.platform.core.db import session_factory
    from autopilot_platform.platform.core.models import JobRow
    from autopilot_platform.core.constants import JobStatus

    _factory = session_factory()
    assert _factory is not None
    db = _factory()
    try:
        job = db.get(JobRow, last)
        assert job is not None
        job.status = JobStatus.CLAIMED.value
        job.runner_id = rid
        db.commit()
    finally:
        db.close()

    r = client.post(
        f"/api/v1/jobs/{last}/complete?runner_id={rid}",
        headers=TOKEN,
        json={"status": "failed", "error": "boom"},
    )
    assert r.status_code == 200

    r = client.get(f"/api/v1/schedules/{sid2}", headers=ah)
    assert r.json()["enabled"] is False
    assert r.json()["last_passed"] is False

    r = client.delete(f"/api/v1/schedules/{sid}", headers=ah)
    assert r.status_code == 204


def test_schedule_fire_lease_is_claimed_by_only_one_session():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from autopilot_platform.platform.core.models import Base, ScheduleRow, utcnow
    from autopilot_platform.platform.services.execution.schedules.crud import _claim_schedule_fire

    now = utcnow()
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    schedule_id = "schedule-lease-race"
    with Session(engine) as setup:
        setup.add(
            ScheduleRow(
                id=schedule_id,
                name="lease",
                enabled=True,
                project_dir="/tmp/project",
                next_run_at=now,
                created_by="admin",
            )
        )
        setup.commit()

    with Session(engine) as first, Session(engine) as second:
        row_first = first.get(ScheduleRow, schedule_id)
        row_second = second.get(ScheduleRow, schedule_id)
        assert row_first is not None and row_second is not None
        assert _claim_schedule_fire(first, row_first, now) is True
        assert _claim_schedule_fire(second, row_second, now) is False


def test_oidc_status_disabled_by_default(client: TestClient):
    r = client.get("/api/v1/auth/oidc/status")
    assert r.status_code == 200
    assert r.json()["enabled"] is False


def test_oidc_login_flow_mocked(client: TestClient, monkeypatch):
    monkeypatch.setenv("MC_OIDC_ENABLED", "1")
    monkeypatch.setenv("MC_OIDC_ISSUER", "https://idp.example")
    monkeypatch.setenv("MC_OIDC_CLIENT_ID", "mc-client")
    monkeypatch.setenv("MC_OIDC_CLIENT_SECRET", "secret")
    monkeypatch.setenv("MC_OIDC_FRONTEND_REDIRECT", "http://front.test/")

    import autopilot_platform.platform.identity.oidc as oidc_mod

    oidc_mod.reset_oidc_cache()
    monkeypatch.setattr(
        oidc_mod,
        "get_discovery",
        lambda force=False: {
            "issuer": "https://idp.example",
            "authorization_endpoint": "https://idp.example/auth",
            "token_endpoint": "https://idp.example/token",
            "jwks_uri": "https://idp.example/jwks",
        },
    )

    r = client.get("/api/v1/auth/oidc/status")
    assert r.json()["enabled"] is True

    r = client.get("/api/v1/auth/oidc/start", follow_redirects=False)
    assert r.status_code == 302
    loc = r.headers["location"]
    assert loc.startswith("https://idp.example/auth?")
    assert "client_id=mc-client" in loc
    assert "state=" in loc

    state = oidc_mod.make_state()
    monkeypatch.setattr(
        oidc_mod,
        "_exchange_code",
        lambda code: {"id_token": "fake"},
    )
    monkeypatch.setattr(
        oidc_mod,
        "_decode_id_token",
        lambda _t: {"sub": "oidc-user-1", "preferred_username": "sso_alice"},
    )

    r = client.get(
        f"/api/v1/auth/oidc/callback?code=abc&state={state}",
        follow_redirects=False,
    )
    assert r.status_code == 302
    dest = r.headers["location"]
    assert dest.startswith("http://front.test/")
    assert "access_token=" in dest
    assert "username=sso_alice" in dest

    # 再次登录同一 sub 不重复建用户
    state2 = oidc_mod.make_state()
    r = client.get(
        f"/api/v1/auth/oidc/callback?code=abc2&state={state2}",
        follow_redirects=False,
    )
    assert r.status_code == 302
    from autopilot_platform.platform.core.db import session_factory
    from autopilot_platform.platform.core.models import UserRow
    from sqlalchemy import select

    _factory = session_factory()
    assert _factory is not None
    db = _factory()
    try:
        users = list(db.scalars(select(UserRow).where(UserRow.oidc_sub == "oidc-user-1")).all())
        assert len(users) == 1
    finally:
        db.close()


def test_job_report_upload_and_view(client: TestClient):
    rid = "report-runner"
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
    r = client.post(
        "/api/v1/jobs",
        headers=TOKEN,
        json={ "project_id": "p-mc","name": "rep", "project_dir": "/tmp/p", "platform": "android"},
    )
    jid = r.json()["id"]
    claimed = client.post(f"/api/v1/jobs/claim?runner_id={rid}", headers=TOKEN).json()
    assert claimed["id"] == jid
    client.post(f"/api/v1/jobs/{jid}/running?runner_id={rid}", headers=TOKEN)
    client.post(
        f"/api/v1/jobs/{jid}/complete?runner_id={rid}",
        headers=TOKEN,
        json={
            "status": "succeeded",
            "report": {
                "report_path": "/runner/local/report.html",
                "passed": 2,
                "failed": 0,
                "total": 2,
                "duration_ms": 100,
                "summary": "ok",
            },
        },
    )
    html = b"<html><body><h1>Report</h1></body></html>"
    r = client.post(
        f"/api/v1/jobs/{jid}/report?runner_id={rid}",
        headers=TOKEN,
        files={"file": ("report.html", html, "text/html")},
    )
    assert r.status_code == 200
    assert r.json()["stored"] is True
    assert r.json()["job_id"] == jid

    r = client.get("/api/v1/reports", headers=TOKEN)
    assert any(x.get("job_id") == jid and x.get("stored") for x in page_items(r.json()))

    r = client.get(f"/api/v1/jobs/{jid}/report", headers=TOKEN)
    assert r.status_code == 200
    assert b"Report" in r.content


def test_audit_log_records_login_and_job(client: TestClient):
    admin = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "admin"}
    ).json()
    ah = {"Authorization": f"Bearer {admin['access_token']}"}

    r = client.post(
        "/api/v1/jobs",
        headers=ah,
        json={ "project_id": "p-mc","name": "audited", "project_dir": "/tmp/p", "platform": "android"},
    )
    assert r.status_code == 200
    jid = r.json()["id"]

    r = client.get("/api/v1/audit?limit=50", headers=ah)
    assert r.status_code == 200
    actions = [x["action"] for x in page_items(r.json())]
    assert "auth.login" in actions
    assert "job.create" in actions
    assert any(x["action"] == "job.create" and x["resource_id"] == jid for x in page_items(r.json()))

    # operator 不可读审计
    client.post(
        "/api/v1/auth/users",
        headers=ah,
        json={"username": "op1", "password": "op1111aa", "duty": "user"},
    )
    op = client.post(
        "/api/v1/auth/login", json={"username": "op1", "password": "op1111aa"}
    ).json()
    r = client.get(
        "/api/v1/audit",
        headers={"Authorization": f"Bearer {op['access_token']}"},
    )
    assert r.status_code == 403


def test_saml_status_and_acs_login(client: TestClient, monkeypatch):
    import base64

    monkeypatch.setenv("MC_SAML_ENABLED", "1")
    monkeypatch.setenv("MC_SAML_IDP_SSO_URL", "https://idp.example/sso")
    monkeypatch.setenv("MC_SAML_IDP_ENTITY_ID", "https://idp.example")
    monkeypatch.setenv("MC_SAML_ALLOW_UNSIGNED", "1")
    monkeypatch.setenv("MC_SAML_FRONTEND_REDIRECT", "http://front.test/")

    r = client.get("/api/v1/auth/saml/status")
    assert r.status_code == 200
    assert r.json()["enabled"] is True

    r = client.get("/api/v1/auth/saml/metadata")
    assert r.status_code == 200
    assert b"EntityDescriptor" in r.content

    r = client.get("/api/v1/auth/saml/login", follow_redirects=False)
    assert r.status_code == 302
    assert "idp.example/sso" in r.headers["location"]
    assert "SAMLRequest=" in r.headers["location"]

    xml = """<?xml version="1.0"?>
<samlp:Response xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol"
  xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion">
  <saml:Issuer>https://idp.example</saml:Issuer>
  <saml:Assertion>
    <saml:Issuer>https://idp.example</saml:Issuer>
    <saml:Subject>
      <saml:NameID>saml-user-42</saml:NameID>
    </saml:Subject>
    <saml:AttributeStatement>
      <saml:Attribute Name="uid">
        <saml:AttributeValue>sso_bob</saml:AttributeValue>
      </saml:Attribute>
    </saml:AttributeStatement>
  </saml:Assertion>
</samlp:Response>"""
    b64 = base64.b64encode(xml.encode("utf-8")).decode("ascii")
    r = client.post(
        "/api/v1/auth/saml/acs",
        data={"SAMLResponse": b64},
        follow_redirects=False,
    )
    assert r.status_code == 302
    dest = r.headers["location"]
    assert dest.startswith("http://front.test/")
    assert "saml=1" in dest
    assert "username=sso_bob" in dest
    assert "access_token=" in dest


def test_saml_signature_verify_with_idp_cert(client: TestClient, monkeypatch, tmp_path):
    import base64
    from datetime import datetime, timedelta, timezone

    # noinspection PyPackageRequirements
    from cryptography import x509
    # noinspection PyPackageRequirements
    from cryptography.hazmat.primitives import hashes, serialization
    # noinspection PyPackageRequirements
    from cryptography.hazmat.primitives.asymmetric import rsa
    # noinspection PyPackageRequirements
    from cryptography.x509.oid import NameOID
    from lxml import etree
    # noinspection PyPackageRequirements
    from signxml import methods
    from signxml.signer import XMLSigner

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "idp-test")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(timezone.utc) - timedelta(days=1))
        .not_valid_after(datetime.now(timezone.utc) + timedelta(days=30))
        .sign(key, hashes.SHA256())
    )
    pem = cert.public_bytes(serialization.Encoding.PEM).decode()
    cert_path = tmp_path / "idp.pem"
    cert_path.write_text(pem, encoding="utf-8")

    monkeypatch.setenv("MC_SAML_ENABLED", "1")
    monkeypatch.setenv("MC_SAML_IDP_SSO_URL", "https://idp.example/sso")
    monkeypatch.setenv("MC_SAML_IDP_ENTITY_ID", "https://idp.example")
    monkeypatch.setenv("MC_SAML_ALLOW_UNSIGNED", "0")
    monkeypatch.setenv("MC_SAML_IDP_CERT_FILE", str(cert_path))
    monkeypatch.setenv("MC_SAML_SP_ENTITY_ID", "http://sp.example/mc")
    monkeypatch.setenv("MC_SAML_ACS_URL", "http://127.0.0.1:8000/api/v1/auth/saml/acs")
    monkeypatch.setenv("MC_SAML_FRONTEND_REDIRECT", "http://front.test/")

    r = client.get("/api/v1/auth/saml/status")
    assert r.json()["signature_verify"] is True
    assert r.json()["idp_cert_configured"] is True

    r = client.get("/api/v1/auth/saml/metadata")
    assert b'WantAssertionsSigned="true"' in r.content

    # 未签名应拒绝
    unsigned = """<?xml version="1.0"?>
<samlp:Response xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol"
  xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion" ID="_r0">
  <saml:Issuer>https://idp.example</saml:Issuer>
  <saml:Assertion ID="_a0">
    <saml:Issuer>https://idp.example</saml:Issuer>
    <saml:Subject><saml:NameID>x</saml:NameID></saml:Subject>
  </saml:Assertion>
</samlp:Response>"""
    r = client.post(
        "/api/v1/auth/saml/acs",
        data={"SAMLResponse": base64.b64encode(unsigned.encode()).decode()},
        follow_redirects=False,
    )
    assert r.status_code in (400, 401, 403)

    now = datetime.now(timezone.utc)
    nb = (now - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    na = (now + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    xml = f"""<?xml version="1.0"?>
<samlp:Response xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol"
  xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion" ID="_r1">
  <saml:Issuer>https://idp.example</saml:Issuer>
  <saml:Assertion ID="_a1">
    <saml:Issuer>https://idp.example</saml:Issuer>
    <saml:Conditions NotBefore="{nb}" NotOnOrAfter="{na}">
      <saml:AudienceRestriction>
        <saml:Audience>http://sp.example/mc</saml:Audience>
      </saml:AudienceRestriction>
    </saml:Conditions>
    <saml:Subject><saml:NameID>signed-user</saml:NameID></saml:Subject>
    <saml:AttributeStatement>
      <saml:Attribute Name="uid">
        <saml:AttributeValue>alice_sso</saml:AttributeValue>
      </saml:Attribute>
    </saml:AttributeStatement>
  </saml:Assertion>
</samlp:Response>"""
    root = etree.fromstring(xml.encode("utf-8"))
    signed = XMLSigner(method=methods.enveloped, signature_algorithm="rsa-sha256").sign(
        root, key=key, cert=[cert]
    )
    b64 = base64.b64encode(etree.tostring(signed)).decode("ascii")
    r = client.post(
        "/api/v1/auth/saml/acs",
        data={"SAMLResponse": b64},
        follow_redirects=False,
    )
    assert r.status_code == 302
    assert "username=alice_sso" in r.headers["location"]

    # 错误证书应失败
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    other_cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(other_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(timezone.utc) - timedelta(days=1))
        .not_valid_after(datetime.now(timezone.utc) + timedelta(days=30))
        .sign(other_key, hashes.SHA256())
    )
    bad_path = tmp_path / "wrong.pem"
    bad_path.write_text(
        other_cert.public_bytes(serialization.Encoding.PEM).decode(), encoding="utf-8"
    )
    monkeypatch.setenv("MC_SAML_IDP_CERT_FILE", str(bad_path))
    r = client.post(
        "/api/v1/auth/saml/acs",
        data={"SAMLResponse": b64},
        follow_redirects=False,
    )
    assert r.status_code in (400, 401, 403)


def test_runner_token_and_stale_reclaim(client: TestClient):
    rid = "tok-runner"
    client.post(
        "/api/v1/runners/register",
        headers=TOKEN,
        json={"runner_id": rid, "hostname": "h", "capabilities": ["android"]},
    )
    admin = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "admin"}
    ).json()
    ah = {"Authorization": f"Bearer {admin['access_token']}"}

    r = client.post(f"/api/v1/runners/{rid}/token", headers=ah)
    assert r.status_code == 200
    tok = r.json()["api_token"]
    assert tok
    runner_h = {"X-API-Token": tok}

    # 独立 token 可心跳本机
    r = client.post(
        "/api/v1/runners/heartbeat",
        headers=runner_h,
        json={"runner_id": rid, "inventory": [], "devices": []},
    )
    assert r.status_code == 200

    # 不可冒充其它 runner
    r = client.post(
        "/api/v1/runners/heartbeat",
        headers=runner_h,
        json={"runner_id": "other", "inventory": [], "devices": []},
    )
    assert r.status_code == 403

    # 不可读审计
    r = client.get("/api/v1/audit", headers=runner_h)
    assert r.status_code == 403

    # 僵死回收
    r = client.post(
        "/api/v1/jobs",
        headers=TOKEN,
        json={ "project_id": "p-mc","name": "stale", "project_dir": "/tmp/p", "platform": "android"},
    )
    jid = r.json()["id"]
    client.post(f"/api/v1/jobs/claim?runner_id={rid}", headers=TOKEN)
    from datetime import timedelta

    from autopilot_platform.platform.core.db import session_factory
    from autopilot_platform.platform.core.models import JobRow, utcnow

    _factory = session_factory()
    assert _factory is not None
    db = _factory()
    try:
        from autopilot_platform.platform.core.models import RunnerRow

        job = db.get(JobRow, jid)
        assert job is not None
        job.updated_at = utcnow() - timedelta(seconds=7200)
        runner = db.get(RunnerRow, rid)
        assert runner is not None
        # Runner 离线才可回收；仍在线时应跳过（见 test_reclaim_skips_online_runner）
        runner.last_heartbeat_at = utcnow() - timedelta(seconds=7200)
        db.commit()
    finally:
        db.close()

    r = client.post("/api/v1/jobs/reclaim?older_than_sec=60", headers=ah)
    assert r.status_code == 200
    assert jid in r.json()
    r = client.get(f"/api/v1/jobs/{jid}", headers=TOKEN)
    assert r.json()["status"] == "failed"


def test_metrics_and_ops_summary(client: TestClient, monkeypatch):
    from autopilot_platform.platform.core.metrics import reset_for_tests

    reset_for_tests()
    monkeypatch.setenv("MC_ALERT_WEBHOOK_URL", "")

    r = client.get("/metrics")
    assert r.status_code == 200
    body = r.text
    assert "mc_jobs" in body
    assert "mc_runners" in body

    # 完成失败任务 → 计数增加
    rid = "m-runner"
    client.post(
        "/api/v1/runners/register",
        headers=TOKEN,
        json={"runner_id": rid, "hostname": "h", "capabilities": ["android"]},
    )
    r = client.post(
        "/api/v1/jobs",
        headers=TOKEN,
        json={ "project_id": "p-mc","name": "m", "project_dir": "/tmp/p", "platform": "android"},
    )
    jid = r.json()["id"]
    client.post(f"/api/v1/jobs/claim?runner_id={rid}", headers=TOKEN)
    client.post(f"/api/v1/jobs/{jid}/running?runner_id={rid}", headers=TOKEN)
    client.post(
        f"/api/v1/jobs/{jid}/complete?runner_id={rid}",
        headers=TOKEN,
        json={"status": "failed", "error": "boom"},
    )

    r = client.get("/metrics")
    assert "mc_job_terminal_total" in r.text
    assert 'status="failed"' in r.text

    admin = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "admin"}
    ).json()
    ah = {"Authorization": f"Bearer {admin['access_token']}"}
    r = client.get("/api/v1/ops/summary", headers=ah)
    assert r.status_code == 200
    data = r.json()
    assert data["jobs_by_status"]["failed"] >= 1
    assert data["metrics_path"] == "/metrics"

    # operator 不可读 ops
    client.post(
        "/api/v1/auth/users",
        headers=ah,
        json={"username": "op1", "password": "op1op1aa", "duty": "user"},
    )
    tok = client.post(
        "/api/v1/auth/login", json={"username": "op1", "password": "op1op1aa"}
    ).json()["access_token"]
    r = client.get(
        "/api/v1/ops/summary", headers={"Authorization": f"Bearer {tok}"}
    )
    assert r.status_code == 403


def test_alert_channel_payloads_and_signing():
    from autopilot_platform.platform.ops.alerts import (
        apply_channel_signing,
        build_alert_payload,
        format_alert_text,
    )

    text = format_alert_text(
        "job.failed",
        "任务失败",
        {"job": {"id": "abc123456789", "name": "suite", "error": "boom"}},
    )
    assert "job.failed" in text and "boom" in text

    ding = build_alert_payload("dingtalk", "job.failed", "任务失败", {})
    assert ding["msgtype"] == "markdown"
    assert "AutoPilot 管理台 · job.failed" in ding["markdown"]["text"]

    feishu = build_alert_payload(
        "feishu",
        "jobs.stale_reclaimed",
        "回收",
        {"job_ids": ["a", "b"]},
        sign_timestamp="123",
        sign_value="sig",
    )
    assert feishu["msg_type"] == "text"
    assert feishu["timestamp"] == "123"
    assert feishu["sign"] == "sig"

    slack = build_alert_payload("slack", "x", "hello", None)
    assert slack["text"].startswith("[AutoPilot 管理台]")

    raw = build_alert_payload("json", "x", "s", {"k": 1})
    assert raw["event"] == "x" and raw["detail"]["k"] == 1

    url, extra = apply_channel_signing(
        "https://oapi.dingtalk.com/robot/send?access_token=t",
        "dingtalk",
        "SECabc",
    )
    assert "timestamp=" in url and "sign=" in url
    assert extra == {}

    url2, extra2 = apply_channel_signing(
        "https://open.feishu.cn/open-apis/bot/v2/hook/x",
        "feishu",
        "sec",
    )
    assert url2.endswith("/x")
    assert "timestamp" in extra2 and "sign" in extra2


def test_ops_alert_test_requires_url(client: TestClient, monkeypatch):
    monkeypatch.setenv("MC_ALERT_WEBHOOK_URL", "")
    admin = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "admin"}
    ).json()
    ah = {"Authorization": f"Bearer {admin['access_token']}"}
    r = client.post("/api/v1/ops/alert-test", headers=ah)
    assert r.status_code == 400

    monkeypatch.setenv("MC_ALERT_WEBHOOK_URL", "http://127.0.0.1:9/nope")
    monkeypatch.setenv("MC_ALERT_CHANNEL", "slack")
    r = client.post("/api/v1/ops/alert-test", headers=ah)
    assert r.status_code == 200
    assert r.json()["channel"] == "slack"
    # 连接失败也返回 ok=false，不抛 5xx
    assert r.json()["ok"] is False


def test_ops_config_runtime_override(client: TestClient, monkeypatch):
    monkeypatch.delenv("MC_ALERT_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("MC_JOB_STALE_SEC", raising=False)
    from autopilot_platform.platform.ops.runtime_config import reload_runtime_config

    reload_runtime_config()

    admin = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "admin"}
    ).json()
    ah = {"Authorization": f"Bearer {admin['access_token']}"}

    r = client.get("/api/v1/ops/config", headers=ah)
    assert r.status_code == 200
    body = r.json()
    assert "MC_ALERT_WEBHOOK_URL" in body["editable_keys"]
    assert "AP_AI_PROVIDER" in body["editable_keys"]
    assert "design_ai_summary" in body
    cat_ids = {c["id"] for c in (body.get("categories") or [])}
    assert "ai_model" in cat_ids
    assert "webhook_alert" in cat_ids
    assert "storage" in cat_ids
    assert body["sources"]["MC_JOB_STALE_SEC"] in ("default", "env")

    # Provider 目录（配置中心切换用）
    catalog = client.get("/api/v1/ops/config/ai-providers", headers=ah)
    assert catalog.status_code == 200
    providers = catalog.json()["providers"]
    assert {p["id"] for p in providers} == {
        "openai",
        "deepseek",
        "qwen",
        "gemini",
        "ollama",
    }
    deepseek = next(p for p in providers if p["id"] == "deepseek")
    assert deepseek["default_base_url"] == "https://api.deepseek.com"
    assert deepseek["default_model"] == "deepseek-v4-flash"
    assert "deepseek-v4-flash" in deepseek["models"]
    qwen = next(p for p in providers if p["id"] == "qwen")
    assert "compatible-mode/v1" in qwen["default_base_url"]
    assert qwen["default_model"] == "qwen-plus"

    # 设计域 AI 键可通过运维统一配置中心写入
    ok_ai = client.put(
        "/api/v1/ops/config",
        headers=ah,
        json={"values": {"AP_AI_PROVIDER": "openai"}},
    )
    assert ok_ai.status_code == 200
    assert ok_ai.json()["values"]["AP_AI_PROVIDER"] == "openai"

    # 非法设计域值仍应被校验拒绝
    bad = client.put(
        "/api/v1/ops/config",
        headers=ah,
        json={"values": {"AP_MAX_CASE_NUM": "9999"}},
    )
    assert bad.status_code == 400

    r = client.put(
        "/api/v1/ops/config",
        headers=ah,
        json={
            "values": {
                "MC_ALERT_WEBHOOK_URL": "http://127.0.0.1:9/hook",
                "MC_ALERT_CHANNEL": "slack",
                "MC_JOB_STALE_SEC": "120",
            }
        },
    )
    assert r.status_code == 200
    assert r.json()["values"]["MC_ALERT_CHANNEL"] == "slack"
    assert r.json()["sources"]["MC_ALERT_WEBHOOK_URL"] == "runtime"
    assert r.json()["values"]["MC_JOB_STALE_SEC"] == "120"

    # 运行时覆盖优先于环境变量
    monkeypatch.setenv("MC_JOB_STALE_SEC", "9999")
    r = client.get("/api/v1/ops/config", headers=ah)
    assert r.json()["values"]["MC_JOB_STALE_SEC"] == "120"

    r = client.post("/api/v1/ops/alert-test", headers=ah)
    assert r.status_code == 200
    assert r.json()["channel"] == "slack"


def test_job_logs_upload_and_read(client: TestClient):
    rid = "log-runner"
    client.post(
        "/api/v1/runners/register",
        headers=TOKEN,
        json={"runner_id": rid, "hostname": "h", "capabilities": ["android"]},
    )
    r = client.post(
        "/api/v1/jobs",
        headers=TOKEN,
        json={ "project_id": "p-mc","name": "logjob", "project_dir": "/tmp/p", "platform": "android"},
    )
    jid = r.json()["id"]
    client.post(f"/api/v1/jobs/claim?runner_id={rid}", headers=TOKEN)
    client.post(
        f"/api/v1/jobs/{jid}/complete?runner_id={rid}",
        headers=TOKEN,
        json={
            "status": "failed",
            "error": "x",
            "log": "line1\nline2\n",
        },
    )
    r = client.get(f"/api/v1/jobs/{jid}/logs", headers=TOKEN)
    assert r.status_code == 200
    assert "line1" in r.text and "line2" in r.text

    r = client.post(
        f"/api/v1/jobs/{jid}/logs?runner_id={rid}&replace=false",
        headers={**TOKEN, "Content-Type": "text/plain; charset=utf-8"},
        content=b"line3\n",
    )
    assert r.status_code == 200
    r = client.get(f"/api/v1/jobs/{jid}/logs", headers=TOKEN)
    assert "line3" in r.text


def test_job_logs_stream_reads_existing(client: TestClient):
    """写入日志后 SSE stream 首包能读到内容。"""
    import json

    rid = "log-stream-runner"
    client.post(
        "/api/v1/runners/register",
        headers=TOKEN,
        json={"runner_id": rid, "hostname": "h", "capabilities": ["android"]},
    )
    r = client.post(
        "/api/v1/jobs",
        headers=TOKEN,
        json={ "project_id": "p-mc","name": "streamjob", "project_dir": "/tmp/p", "platform": "android"},
    )
    jid = r.json()["id"]
    client.post(f"/api/v1/jobs/claim?runner_id={rid}", headers=TOKEN)
    client.post(
        f"/api/v1/jobs/{jid}/complete?runner_id={rid}",
        headers=TOKEN,
        json={"status": "succeeded", "log": "stream-hello\n"},
    )

    admin = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "admin"}
    ).json()
    user_headers = {"Authorization": f"Bearer {admin['access_token']}"}
    token = client.post(
        f"/api/v1/jobs/{jid}/logs/stream-token", headers=user_headers
    ).json()["access_token"]
    from autopilot_platform.platform.auth import require_stream_auth
    from autopilot_platform.platform.core.security import decode_access_token

    assert decode_access_token(token)["typ"] == "job_log_stream"
    assert require_stream_auth(token).stream_job_id == jid
    assert client.get(
        f"/api/v1/jobs/{jid}/logs/stream?access_token={admin['access_token']}"
    ).status_code == 401
    assert client.get(
        f"/api/v1/jobs/{jid}", headers={"Authorization": f"Bearer {token}"}
    ).status_code == 401

    with client.stream(
        "GET",
        f"/api/v1/jobs/{jid}/logs/stream?access_token={token}",
    ) as resp:
        if resp.status_code != 200:
            resp.read()
        assert resp.status_code == 200, resp.text
        assert "text/event-stream" in (resp.headers.get("content-type") or "")
        got = ""
        for line in resp.iter_lines():
            if not line:
                continue
            if line.startswith("data: ") and not line.startswith("data: {}"):
                payload = json.loads(line[6:])
                got = payload.get("text") or ""
                assert "offset" in payload
                break
        assert "stream-hello" in got


def test_reports_compare(client: TestClient):
    from autopilot_platform.platform.core.db import session_factory
    from autopilot_platform.platform.core.models import JobRow, ReportRow, new_id, utcnow

    _factory = session_factory()
    assert _factory is not None
    db = _factory()
    try:
        j1 = JobRow(
            id=new_id(),
            name="base",
            status="succeeded",
            project_dir="/tmp/a",
            platform="android",
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        j2 = JobRow(
            id=new_id(),
            name="new",
            status="failed",
            project_dir="/tmp/b",
            platform="android",
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        db.add(j1)
        db.add(j2)
        db.flush()
        db.add(
            ReportRow(
                id=new_id(),
                job_id=j1.id,
                passed=10,
                failed=0,
                total=10,
                duration_ms=1000,
                summary="ok",
                app_build_id="build-a",
                app_build_name="AppA",
                app_version_name="1.0.0",
                artifact_id="art-a",
                artifact_name="suite-a",
            )
        )
        db.add(
            ReportRow(
                id=new_id(),
                job_id=j2.id,
                passed=8,
                failed=2,
                total=10,
                duration_ms=1200,
                summary="worse",
                app_build_id="build-b",
                app_build_name="AppB",
                app_version_name="1.1.0",
                artifact_id="art-a",
                artifact_name="suite-a",
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
    assert data["delta"]["failed"] == 2
    assert data["delta"]["passed"] == -2
    assert data["delta"]["duration_ms"] == 200
    assert data["verdict"] == "regressed"
    assert data["same_app_build"] is False
    assert data["same_artifact"] is True
    assert data["left"]["app_version_name"] == "1.0.0"
    assert data["right"]["app_build_name"] == "AppB"
    assert data["cases"]["available"] is False

    r = client.get("/api/v1/reports?app_build_id=build-b", headers=TOKEN)
    assert r.status_code == 200
    ids = [x["job_id"] for x in page_items(r.json())]
    assert right_id in ids
    assert left_id not in ids


def test_ops_config_secrets_encrypted_at_rest(client: TestClient, tmp_path, monkeypatch):
    monkeypatch.setenv("MC_CONFIG_SECRET", "unit-test-config-secret-key!!")
    from autopilot_platform.platform.ops.runtime_config import (
        reload_runtime_config,
        runtime_config_path,
    )

    reload_runtime_config()
    admin = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "admin"}
    ).json()
    ah = {"Authorization": f"Bearer {admin['access_token']}"}

    r = client.put(
        "/api/v1/ops/config",
        headers=ah,
        json={
            "values": {
                "MC_WEBHOOK_SECRET": "hook-secret-plain",
                "MC_ALERT_SECRET": "SECalert",
            }
        },
    )
    assert r.status_code == 200
    assert r.json()["values"]["MC_WEBHOOK_SECRET"] == "********"
    assert r.json()["secrets_encrypted_at_rest"] is True

    raw = runtime_config_path().read_text(encoding="utf-8")
    assert "hook-secret-plain" not in raw
    assert "SECalert" not in raw
    assert "enc:v1:" in raw

    reload_runtime_config()
    r = client.get("/api/v1/ops/config", headers=ah)
    assert r.json()["values"]["MC_WEBHOOK_SECRET"] == "********"
    assert r.json()["values"]["MC_ALERT_SECRET"] == "********"
    assert r.json()["secret_configured"]["MC_WEBHOOK_SECRET"] is True
    assert r.json()["secret_configured"]["MC_ALERT_SECRET"] is True


def test_ops_config_export_import_unified(client: TestClient, tmp_path, monkeypatch):
    monkeypatch.setenv("MC_RUNTIME_CONFIG", str(tmp_path / "mc_runtime_config.json"))
    from autopilot_platform.platform.ops.runtime_config import reload_runtime_config

    reload_runtime_config()
    admin = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "admin"}
    ).json()
    ah = {"Authorization": f"Bearer {admin['access_token']}"}

    client.put(
        "/api/v1/ops/config",
        headers=ah,
        json={"values": {"AP_AI_MODEL": "gpt-test", "MC_JOB_STALE_SEC": "42"}},
    )
    exp = client.get("/api/v1/ops/config/export", headers=ah)
    assert exp.status_code == 200
    payload = exp.json()
    assert payload.get("format") == "autopilot-runtime-config"
    assert payload["values"]["AP_AI_MODEL"] == "gpt-test"
    assert payload["values"]["MC_JOB_STALE_SEC"] == "42"

    imp = client.post(
        "/api/v1/ops/config/import",
        headers=ah,
        json={"values": {"AP_MAX_WORKERS": "4", "MC_ALERT_CHANNEL": "feishu"}},
    )
    assert imp.status_code == 200, imp.text
    assert imp.json()["values"]["AP_MAX_WORKERS"] == "4"
    assert imp.json()["values"]["MC_ALERT_CHANNEL"] == "feishu"


def test_migrate_schema_adds_missing_columns(tmp_path):
    """模拟旧库缺列，migrate_schema 应补齐（方言无关路径，用 SQLite 验证）。"""
    from sqlalchemy import create_engine, text

    from autopilot_platform.platform.core.db import migrate_schema, reset_engine

    reset_engine()
    db = tmp_path / "legacy.db"
    url = f"sqlite:///{db.as_posix()}"
    engine = create_engine(url, future=True)
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE jobs (
                    id VARCHAR(64) PRIMARY KEY,
                    name VARCHAR(256),
                    status VARCHAR(32)
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE users (
                    id VARCHAR(64) PRIMARY KEY,
                    username VARCHAR(64),
                    password_hash VARCHAR(256),
                    role VARCHAR(32)
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE runners (
                    runner_id VARCHAR(128) PRIMARY KEY,
                    hostname VARCHAR(256)
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE reports (
                    id VARCHAR(64) PRIMARY KEY,
                    job_id VARCHAR(64)
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE artifacts (
                    id VARCHAR(64) PRIMARY KEY,
                    name VARCHAR(256)
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE devices (
                    id VARCHAR(64) PRIMARY KEY,
                    runner_id VARCHAR(128),
                    udid VARCHAR(256)
                )
                """
            )
        )

    applied = migrate_schema(engine)
    assert "jobs.created_by" in applied
    assert "jobs.artifact_id" in applied
    assert "users.oidc_sub" in applied
    assert "runners.token_hash" in applied
    assert "reports.stored_path" in applied
    assert "artifacts.project_id" in applied
    assert "devices.busy_job_id" in applied

    # 幂等
    assert migrate_schema(engine) == []
    engine.dispose()
    reset_engine()


def test_reports_project_filter_and_offset(client: TestClient):
    from autopilot_platform.platform.core.db import session_factory
    from autopilot_platform.platform.core.models import JobRow, ReportRow, new_id

    _factory = session_factory()
    assert _factory is not None
    db = _factory()
    try:
        jobs = [
            JobRow(id=new_id(), name="one", project_id="project-a"),
            JobRow(id=new_id(), name="two", project_id="project-a"),
            JobRow(id=new_id(), name="other", project_id="project-b"),
        ]
        db.add_all(jobs)
        db.flush()
        db.add_all(
            [
                ReportRow(id=new_id(), job_id=jobs[0].id),
                ReportRow(id=new_id(), job_id=jobs[1].id),
                ReportRow(id=new_id(), job_id=jobs[2].id),
            ]
        )
        project_a_job_ids = {jobs[0].id, jobs[1].id}
        db.commit()
    finally:
        db.close()

    r = client.get("/api/v1/reports?project_id=project-a&limit=10", headers=TOKEN)
    assert r.status_code == 200
    assert {report["job_id"] for report in page_items(r.json())} == project_a_job_ids
    r = client.get("/api/v1/reports?project_id=project-a&limit=1&offset=1", headers=TOKEN)
    assert r.status_code == 200
    assert len(page_items(r.json())) == 1


def test_project_member_remove_and_last_owner_protection(client: TestClient):
    admin = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "admin"}
    ).json()
    headers = {"Authorization": f"Bearer {admin['access_token']}"}
    user = client.post(
        "/api/v1/auth/users",
        headers=headers,
        json={"username": "member", "password": "member12", "duty": "user"},
    ).json()
    r = create_org_project(client, headers, org_id="org-rm", project_id="remove-test")
    assert r.status_code == 200
    r = client.post(
        "/api/v1/projects/remove-test/members",
        headers=headers,
        json={"username": "member", "role": "member"},
    )
    assert r.status_code == 200
    r = client.delete(f"/api/v1/projects/remove-test/members/{user['id']}", headers=headers)
    assert r.status_code == 204
    r = client.delete(
        f"/api/v1/projects/remove-test/members/{admin['user']['id']}", headers=headers
    )
    assert r.status_code == 400


def test_user_disable_password_reset_and_stream_token(client: TestClient):
    admin = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "admin"}
    ).json()
    headers = {"Authorization": f"Bearer {admin['access_token']}"}
    user = client.post(
        "/api/v1/auth/users",
        headers=headers,
        json={"username": "disabled-user", "password": "initial12", "duty": "user"},
    ).json()

    r = client.patch(
        f"/api/v1/auth/users/{user['id']}", headers=headers, json={"disabled": True}
    )
    assert r.status_code == 200
    assert r.json()["disabled"] is True
    assert client.post(
        "/api/v1/auth/login", json={"username": "disabled-user", "password": "initial12"}
    ).status_code == 401

    r = client.patch(
        f"/api/v1/auth/users/{user['id']}",
        headers=headers,
        json={"disabled": False, "password": "resetpass1"},
    )
    assert r.status_code == 200
    assert client.post(
        "/api/v1/auth/login", json={"username": "disabled-user", "password": "resetpass1"}
    ).status_code == 200

    job = client.post(
        "/api/v1/jobs", headers=headers, json={ "project_id": "p-mc","name": "log-token", "project_dir": "/tmp/p"}
    ).json()
    r = client.post(f"/api/v1/jobs/{job['id']}/logs/stream-token", headers=headers)
    assert r.status_code == 200
    assert r.json()["access_token"]
    assert r.json()["expires_in"] == 120


def test_claim_requires_device_on_runner(client: TestClient):
    """P0-1：指定 UDID 仅挂在 A 时，B 不可 claim。"""
    for rid, udid in (("r-aff-a", "udid-a"), ("r-aff-b", "udid-b")):
        client.post(
            "/api/v1/runners/register",
            headers=TOKEN,
            json={"runner_id": rid, "hostname": rid},
        )
        client.post(
            "/api/v1/runners/heartbeat",
            headers=TOKEN,
            json={
                "runner_id": rid,
                "inventory": [{"udid": udid, "platform": "android"}], "devices": [{"udid": udid, "platform": "android"}],
            },
        )
    r = client.post(
        "/api/v1/jobs",
        headers=TOKEN,
        json={ "project_id": "p-mc",
            "name": "aff",
            "project_dir": "/tmp/p",
            "device_udids": ["udid-a"],
        },
    )
    jid = r.json()["id"]
    assert client.post("/api/v1/jobs/claim?runner_id=r-aff-b", headers=TOKEN).json() is None
    claimed = client.post("/api/v1/jobs/claim?runner_id=r-aff-a", headers=TOKEN).json()
    assert claimed is not None
    assert claimed["id"] == jid
    assert claimed["runner_id"] == "r-aff-a"


def test_heartbeat_preserves_busy_job_id(client: TestClient):
    """P0-4：心跳 upsert 后 busy_job_id 不丢失；短暂未枚举仍保留占用行。"""
    rid = "r-hb-busy"
    client.post(
        "/api/v1/runners/register",
        headers=TOKEN,
        json={"runner_id": rid, "hostname": "h"},
    )
    client.post(
        "/api/v1/runners/heartbeat",
        headers=TOKEN,
        json={
            "runner_id": rid,
            "inventory": [{"udid": "dev-hb", "platform": "android"}], "devices": [{"udid": "dev-hb", "platform": "android"}],
        },
    )
    jid = client.post(
        "/api/v1/jobs",
        headers=TOKEN,
        json={ "project_id": "p-mc",
            "name": "hb",
            "project_dir": "/tmp/p",
            "device_udids": ["dev-hb"],
            "preferred_runner_id": rid,
        },
    ).json()["id"]
    assert client.post(f"/api/v1/jobs/claim?runner_id={rid}", headers=TOKEN).json()["id"] == jid

    client.post(
        "/api/v1/runners/heartbeat",
        headers=TOKEN,
        json={
            "runner_id": rid,
            "inventory": [{"udid": "dev-hb", "platform": "android", "name": "phone"}], "devices": [{"udid": "dev-hb", "platform": "android", "name": "phone"}],
        },
    )
    devices = page_items(client.get("/api/v1/devices", headers=TOKEN).json())
    d = next(x for x in devices if x["udid"] == "dev-hb")
    assert d["busy"] is True
    assert d["busy_job_id"] == jid

    # 枚举抖动：本次未上报该设备，但仍应保留占用行
    client.post(
        "/api/v1/runners/heartbeat",
        headers=TOKEN,
        json={"runner_id": rid, "inventory": [], "devices": []},
    )
    devices = page_items(client.get("/api/v1/devices", headers=TOKEN).json())
    d = next(x for x in devices if x["udid"] == "dev-hb")
    assert d["busy_job_id"] == jid


def test_late_complete_does_not_overwrite_reclaimed(client: TestClient):
    """P0-5：reclaim 为 failed 后，late complete 不得改成 succeeded。"""
    from datetime import timedelta

    from autopilot_platform.platform.core.db import session_factory
    from autopilot_platform.platform.core.models import JobRow, RunnerRow, utcnow

    rid = "r-late-complete"
    client.post(
        "/api/v1/runners/register",
        headers=TOKEN,
        json={"runner_id": rid, "hostname": "h"},
    )
    jid = client.post(
        "/api/v1/jobs",
        headers=TOKEN,
        json={ "project_id": "p-mc","name": "late", "project_dir": "/tmp/p"},
    ).json()["id"]
    client.post(f"/api/v1/jobs/claim?runner_id={rid}", headers=TOKEN)

    admin = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "admin"}
    ).json()
    ah = {"Authorization": f"Bearer {admin['access_token']}"}

    _factory = session_factory()
    assert _factory is not None
    db = _factory()
    try:
        job = db.get(JobRow, jid)
        runner = db.get(RunnerRow, rid)
        assert job is not None and runner is not None
        job.updated_at = utcnow() - timedelta(seconds=7200)
        runner.last_heartbeat_at = utcnow() - timedelta(seconds=7200)
        db.commit()
    finally:
        db.close()

    assert jid in client.post("/api/v1/jobs/reclaim?older_than_sec=60", headers=ah).json()
    r = client.post(
        f"/api/v1/jobs/{jid}/complete?runner_id={rid}",
        headers=TOKEN,
        json={"status": "succeeded"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "failed"


def test_reclaim_skips_online_runner(client: TestClient):
    """在线 Runner 的过期 updated_at 任务应被续租而非 failed。"""
    from datetime import timedelta

    from autopilot_platform.platform.core.db import session_factory
    from autopilot_platform.platform.core.models import JobRow, utcnow

    rid = "r-online-skip"
    client.post(
        "/api/v1/runners/register",
        headers=TOKEN,
        json={"runner_id": rid, "hostname": "h"},
    )
    # 心跳保持在线
    client.post(
        "/api/v1/runners/heartbeat",
        headers=TOKEN,
        json={"runner_id": rid, "inventory": [], "devices": []},
    )
    jid = client.post(
        "/api/v1/jobs",
        headers=TOKEN,
        json={ "project_id": "p-mc","name": "alive", "project_dir": "/tmp/p"},
    ).json()["id"]
    client.post(f"/api/v1/jobs/claim?runner_id={rid}", headers=TOKEN)

    _factory = session_factory()
    assert _factory is not None
    db = _factory()
    try:
        job = db.get(JobRow, jid)
        assert job is not None
        job.updated_at = utcnow() - timedelta(seconds=7200)
        db.commit()
    finally:
        db.close()

    admin = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "admin"}
    ).json()
    ah = {"Authorization": f"Bearer {admin['access_token']}"}
    r = client.post("/api/v1/jobs/reclaim?older_than_sec=60", headers=ah)
    assert r.status_code == 200
    assert jid not in r.json()
    assert client.get(f"/api/v1/jobs/{jid}", headers=TOKEN).json()["status"] == "claimed"


def test_project_resource_acl_share_for_non_member(client: TestClient):
    """P0-7：有 project_id 的资源可通过 ACL 分享给非成员。"""
    import io
    import zipfile

    admin = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "admin"}
    ).json()
    ah = {"Authorization": f"Bearer {admin['access_token']}"}
    client.post(
        "/api/v1/auth/users",
        headers=ah,
        json={"username": "alice", "password": "alice123", "duty": "user"},
    )
    client.post(
        "/api/v1/auth/users",
        headers=ah,
        json={"username": "bob", "password": "bob12345", "duty": "user"},
    )
    assert (
        create_org_project(
            client, ah, org_id="org-share", project_id="share-proj", name="Share Proj"
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/v1/projects/share-proj/members",
            headers=ah,
            json={"username": "alice", "role": "member"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/v1/orgs/org-share/members",
            headers=ah,
            json={"username": "bob", "role": "member"},
        ).status_code
        == 200
    )

    alice = client.post(
        "/api/v1/auth/login", json={"username": "alice", "password": "alice123"}
    ).json()
    alice_h = {"Authorization": f"Bearer {alice['access_token']}"}
    bob = client.post(
        "/api/v1/auth/login", json={"username": "bob", "password": "bob12345"}
    ).json()
    bob_h = {"Authorization": f"Bearer {bob['access_token']}"}

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("x.txt", "1")
    data = buf.getvalue()

    aid = client.post(
        "/api/v1/artifacts",
        headers=alice_h,
        files={"file": ("p.zip", data, "application/zip")},
        data={"name": "proj-art", "project_id": "share-proj"},
    ).json()["id"]

    assert client.get(f"/api/v1/artifacts/{aid}", headers=bob_h).status_code == 403

    assert (
        client.post(
            "/api/v1/acl",
            headers=alice_h,
            json={
                "resource_type": "artifact",
                "resource_id": aid,
                "username": "bob",
                "permission": "read",
            },
        ).status_code
        == 200
    )
    assert client.get(f"/api/v1/artifacts/{aid}", headers=bob_h).status_code == 200


def test_list_jobs_acl_overfetch_fills_page(client: TestClient):
    """P1-8：他人私有任务夹杂时，过采+ACL 后本页仍能凑满 limit。"""
    admin = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "admin"}
    ).json()
    ah = {"Authorization": f"Bearer {admin['access_token']}"}
    for name, pw in (("alice", "alice123"), ("bob", "bob12345")):
        client.post(
            "/api/v1/auth/users",
            headers=ah,
            json={"username": name, "password": pw, "duty": "user"},
        )
    alice = client.post(
        "/api/v1/auth/login", json={"username": "alice", "password": "alice123"}
    ).json()
    alice_h = {"Authorization": f"Bearer {alice['access_token']}"}
    bob = client.post(
        "/api/v1/auth/login", json={"username": "bob", "password": "bob12345"}
    ).json()
    bob_h = {"Authorization": f"Bearer {bob['access_token']}"}

    assert (
        create_org_project(
            client, ah, org_id="org-ab", project_id="proj-alice", name="Alice"
        ).status_code
        == 200
    )
    assert (
        create_org_project(
            client, ah, org_id="org-ab", project_id="proj-bob", name="Bob"
        ).status_code
        == 200
    )
    client.post(
        "/api/v1/projects/proj-alice/members",
        headers=ah,
        json={"username": "alice", "role": "member"},
    )
    client.post(
        "/api/v1/projects/proj-bob/members",
        headers=ah,
        json={"username": "bob", "role": "member"},
    )

    # bob 先塞若干私有任务（排在中间会挤占旧 SQL LIMIT）
    for i in range(5):
        assert (
            client.post(
                "/api/v1/jobs",
                headers=bob_h,
                json={"name": f"bob-{i}", "project_dir": "/tmp/b", "project_id": "proj-bob"},
            ).status_code
            == 200
        )
    alice_ids = []
    for i in range(3):
        r = client.post(
            "/api/v1/jobs",
            headers=alice_h,
            json={"name": f"alice-{i}", "project_dir": "/tmp/a", "project_id": "proj-alice"},
        )
        assert r.status_code == 200
        alice_ids.append(r.json()["id"])

    page = page_items(client.get("/api/v1/jobs?limit=3&offset=0", headers=alice_h).json())
    assert len(page) == 3
    assert all(j["id"] in alice_ids for j in page)


def test_schedule_update_source_fields_and_fire_uses_creator_acl(client: TestClient):
    """P1-9：ScheduleUpdate 可改源字段；触发时以创建者身份校验制品。"""
    import io
    import zipfile

    admin = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "admin"}
    ).json()
    ah = {"Authorization": f"Bearer {admin['access_token']}"}

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("a.txt", "1")
    data = buf.getvalue()
    aid = client.post(
        "/api/v1/artifacts",
        headers=ah,
        files={"file": ("s.zip", data, "application/zip")},
        data={ "project_id": "p-mc","name": "sched-art"},
    ).json()["id"]

    apk = io.BytesIO()
    with zipfile.ZipFile(apk, "w") as zf:
        zf.writestr("AndroidManifest.xml", "minimal")
    bid = client.post(
        "/api/v1/app-builds",
        headers=ah,
        files={"file": ("demo.apk", apk.getvalue(), "application/vnd.android.package-archive")},
        data={ "project_id": "p-mc","name": "sched-app"},
    ).json()["id"]

    r = client.post(
        "/api/v1/schedules",
        headers=ah,
        json={ "project_id": "p-mc",
            "name": "upd",
            "project_dir": "/tmp/old",
            "delay_sec": 0,
            "interval_sec": 0,
            "repeat": 1,
            "enabled": False,
        },
    )
    assert r.status_code == 200
    sid = r.json()["id"]

    r = client.patch(
        f"/api/v1/schedules/{sid}",
        headers=ah,
        json={
            "artifact_id": aid,
            "app_build_id": bid,
            "project_dir": "",
            "platform": "android",
            "parallel": True,
            "enabled": True,
            "delay_sec": 0,
            "interval_sec": 0,
            "repeat": 1,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["artifact_id"] == aid
    assert body["app_build_id"] == bid
    assert body["project_dir"] == ""
    assert body["parallel"] is True

    r = client.post(f"/api/v1/schedules/{sid}/run-now", headers=ah)
    assert r.status_code == 200
    jid = r.json().get("last_job_id")
    assert jid
    job = client.get(f"/api/v1/jobs/{jid}", headers=ah).json()
    assert job["artifact_id"] == aid
    assert job["app_build_id"] == bid
    assert job["created_by"] == "admin"


def test_require_job_devices_rejects_empty_udids(client: TestClient, monkeypatch):
    """P2-2：MC_REQUIRE_JOB_DEVICES=1 时禁止空 device_udids。"""
    monkeypatch.setenv("MC_REQUIRE_JOB_DEVICES", "1")
    r = client.post(
        "/api/v1/jobs",
        headers=TOKEN,
        json={ "project_id": "p-mc","name": "no-dev", "project_dir": "/tmp/p"},
    )
    assert r.status_code == 400
    assert "device_udids" in api_error_message(r)

    r = client.post(
        "/api/v1/jobs",
        headers=TOKEN,
        json={ "project_id": "p-mc",
            "name": "with-dev",
            "project_dir": "/tmp/p",
            "device_udids": ["dev-x"],
        },
    )
    assert r.status_code == 200
    assert r.json()["device_udids"] == ["dev-x"]


def test_require_job_devices_allows_web_without_udids(client: TestClient, monkeypatch):
    """platform=web 时 MC_REQUIRE_JOB_DEVICES 不强制 UDID。"""
    monkeypatch.setenv("MC_REQUIRE_JOB_DEVICES", "1")
    r = client.post(
        "/api/v1/jobs",
        headers=TOKEN,
        json={
            "project_id": "p-mc",
            "name": "web-no-dev",
            "project_dir": "/tmp/p",
            "platform": "web",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["platform"] == "web"
    assert body["device_udids"] == []


def test_complete_log_owned_by_complete_and_runner_sees_cancel(client: TestClient):
    """P1-13 / P0-3：日志由 complete 落盘；Runner 可 GET 到 cancelled。"""
    rid = "r-cancel-poll"
    client.post(
        "/api/v1/runners/register",
        headers=TOKEN,
        json={"runner_id": rid, "hostname": "h"},
    )
    client.post(
        "/api/v1/runners/heartbeat",
        headers=TOKEN,
        json={"runner_id": rid, "inventory": [], "devices": []},
    )
    jid = client.post(
        "/api/v1/jobs",
        headers=TOKEN,
        json={ "project_id": "p-mc","name": "cxl", "project_dir": "/tmp/p"},
    ).json()["id"]
    assert client.post(f"/api/v1/jobs/claim?runner_id={rid}", headers=TOKEN).json()["id"] == jid
    client.post(f"/api/v1/jobs/{jid}/running?runner_id={rid}", headers=TOKEN)
    assert client.post(f"/api/v1/jobs/{jid}/cancel", headers=TOKEN).status_code == 200

    got = client.get(f"/api/v1/jobs/{jid}", headers=TOKEN).json()
    assert got["status"] == "cancelled"

    r = client.post(
        f"/api/v1/jobs/{jid}/complete?runner_id={rid}",
        headers=TOKEN,
        json={"status": "succeeded", "log": "line-from-complete\n"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "cancelled"
    logs = client.get(f"/api/v1/jobs/{jid}/logs", headers=TOKEN)
    assert logs.status_code == 200
    assert "line-from-complete" in logs.text
