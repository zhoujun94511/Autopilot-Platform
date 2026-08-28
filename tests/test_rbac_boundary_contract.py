"""权限边界契约：文档钉死 + 跨组织隔离 HTTP。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient

from list_page_helpers import page_items

from autopilot_platform.platform.app import create_app
from autopilot_platform.platform.core.db import reset_engine

CONTRACT = (
    Path(ROOT) / "docs" / "architecture" / "RBAC_BOUNDARY_CONTRACT.md"
)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "boundary.db"
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


def _login(client: TestClient, user="admin", password="admin") -> dict:
    r = client.post("/api/v1/auth/login", json={"username": user, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_boundary_contract_invariants():
    text = CONTRACT.read_text(encoding="utf-8")
    assert "组织是租户硬隔离" in text
    assert "只有平台管理员能看全部组织" in text
    assert "本组织 owner/admin" in text
    assert "被标成" in text
    assert "禁止把外组织的人直接加进项目" in text
    assert "拒绝创建" in text
    assert "必须落在项目里" in text
    assert "版本**：1.5" in text
    assert "ScopePolicy" in text
    assert "合成桶" in text
    assert "设备看板" in text
    assert "注册 ≠ 使用" in text
    assert "禁止 `Device.project_id`" in text
    assert "顶栏组织是**过滤器**" in text
    assert "PATCH /runners/{id}/device-selection" in text


def test_device_row_is_not_project_tenant():
    from autopilot_platform.platform.core.models import DeviceRow, JobRow

    device_cols = set(DeviceRow.__table__.columns.keys())
    assert "project_id" not in device_cols
    assert "runner_id" in device_cols
    assert "udid" in device_cols
    assert "project_id" in set(JobRow.__table__.columns.keys())


def test_cannot_add_other_org_user_as_project_member(client: TestClient):
    ah = _login(client)
    assert client.post("/api/v1/orgs", headers=ah, json={"id": "bu-a", "name": "A"}).status_code == 200
    assert client.post("/api/v1/orgs", headers=ah, json={"id": "bu-b", "name": "B"}).status_code == 200
    client.post(
        "/api/v1/auth/users",
        headers=ah,
        json={"username": "alice-a", "password": "Alice123", "duty": "user"},
    )
    client.post(
        "/api/v1/auth/users",
        headers=ah,
        json={"username": "bob-b", "password": "Bob12345", "duty": "user"},
    )
    assert (
        client.post(
            "/api/v1/orgs/bu-a/members",
            headers=ah,
            json={"username": "alice-a", "role": "member"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/v1/orgs/bu-b/members",
            headers=ah,
            json={"username": "bob-b", "role": "member"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/v1/projects",
            headers={**ah, "X-Org-Id": "bu-a"},
            json={"id": "p-a", "name": "PA", "org_id": "bu-a"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/v1/projects/p-a/members",
            headers=ah,
            json={"username": "alice-a", "role": "owner"},
        ).status_code
        == 200
    )
    alice = {
        **_login(client, "alice-a", "Alice123"),
        "X-Org-Id": "bu-a",
    }
    r = client.post(
        "/api/v1/projects/p-a/members",
        headers=alice,
        json={"username": "bob-b", "role": "viewer"},
    )
    assert r.status_code in (400, 403), r.text
    members = page_items(client.get("/api/v1/projects/p-a/members", headers=alice).json())
    assert all(m["username"] != "bob-b" for m in members)


def test_org_admin_cannot_be_stored_as_viewer(client: TestClient):
    ah = _login(client)
    assert client.post("/api/v1/orgs", headers=ah, json={"id": "bu-c", "name": "C"}).status_code == 200
    client.post(
        "/api/v1/auth/users",
        headers=ah,
        json={"username": "cadm", "password": "Cadm1234", "duty": "user"},
    )
    assert (
        client.post(
            "/api/v1/orgs/bu-c/members",
            headers=ah,
            json={"username": "cadm", "role": "admin"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/v1/projects",
            headers={**ah, "X-Org-Id": "bu-c"},
            json={"id": "p-c", "name": "PC", "org_id": "bu-c"},
        ).status_code
        == 200
    )
    r = client.post(
        "/api/v1/projects/p-c/members",
        headers=ah,
        json={"username": "cadm", "role": "viewer"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "owner"
    members = page_items(client.get("/api/v1/projects/p-c/members", headers=ah).json())
    mine = [m for m in members if m["username"] == "cadm"]
    assert len(mine) == 1 and mine[0]["role"] == "owner"


def test_visibility_sites_do_not_use_raw_member_project_ids():
    """列表/设备/池可见性必须走 visible_project_filter，禁止直接 member_project_ids。"""
    root = Path(ROOT) / "autopilot_platform" / "platform"
    offenders: list[str] = []
    allow = {
        "tenancy/projects.py",
        "tenancy/__init__.py",
    }
    for path in root.rglob("*.py"):
        rel = path.relative_to(root).as_posix()
        if rel in allow:
            continue
        text = path.read_text(encoding="utf-8")
        if "member_project_ids" in text:
            offenders.append(rel)
    assert not offenders, "可见性漏网：" + ", ".join(offenders)


def test_org_admin_sees_design_without_project_membership(client: TestClient):
    """本组织 admin 不必加入 project_members 也能读写设计域。"""
    ah = _login(client)
    assert client.post("/api/v1/orgs", headers=ah, json={"id": "bu-d", "name": "D"}).status_code == 200
    client.post(
        "/api/v1/auth/users",
        headers=ah,
        json={"username": "dadm", "password": "Dadm1234", "duty": "user"},
    )
    assert (
        client.post(
            "/api/v1/orgs/bu-d/members",
            headers=ah,
            json={"username": "dadm", "role": "admin"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/v1/projects",
            headers={**ah, "X-Org-Id": "bu-d"},
            json={"id": "p-d", "name": "PD", "org_id": "bu-d"},
        ).status_code
        == 200
    )
    dadm = {**_login(client, "dadm", "Dadm1234"), "X-Org-Id": "bu-d"}
    r = client.get("/api/v1/design/requirements?project_id=p-d", headers=dadm)
    assert r.status_code == 200, r.text
    r = client.post(
        "/api/v1/design/logical-cases",
        headers=dadm,
        json={
            "project_id": "p-d",
            "title": "org-admin-case",
            "description": "",
            "logical_steps": ["s1"],
        },
    )
    assert r.status_code == 200, r.text
    projects = page_items(client.get("/api/v1/projects", headers=dadm).json())
    hit = [p for p in projects if p["id"] == "p-d"]
    assert len(hit) == 1 and hit[0]["my_role"] == "owner"


def test_cannot_create_unscoped_project(client: TestClient):
    ah = _login(client)
    client.post(
        "/api/v1/auth/users",
        headers=ah,
        json={"username": "op-loose", "password": "OpLoose12", "duty": "user"},
    )
    op = _login(client, "op-loose", "OpLoose12")
    r = client.post("/api/v1/projects", headers=op, json={"id": "p-no-org", "name": "X"})
    assert r.status_code in (400, 403), r.text
    r = client.post("/api/v1/projects", headers=ah, json={"id": "p-admin-no-org", "name": "X"})
    assert r.status_code == 400, r.text


def test_cannot_create_unscoped_job_or_artifact(client: TestClient):
    ah = _login(client)
    body = {"name": "loose-job", "project_dir": "/tmp/p", "project_id": ""}
    r = client.post("/api/v1/jobs", headers=ah, json=body)
    assert r.status_code == 403, r.text
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("x.txt", "1")
    r = client.post(
        "/api/v1/artifacts",
        headers=ah,
        files={"file": ("p.zip", buf.getvalue(), "application/zip")},
        data={"name": "loose-art", "project_id": ""},
    )
    assert r.status_code == 403, r.text

