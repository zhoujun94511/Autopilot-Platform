"""Org admin 管用户 + 审计 org_id。"""

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


def _login(client: TestClient, user="admin", password="admin") -> dict:
    r = client.post("/api/v1/auth/login", json={"username": user, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_org_admin_creates_and_lists_users(client: TestClient):
    ah = _login(client)
    assert (
        client.post(
            "/api/v1/orgs", headers=ah, json={"id": "bu-u", "name": "U"}
        ).status_code
        == 200
    )
    # 先建组织管理员账号（平台 admin），再提升为 org admin
    assert (
        client.post(
            "/api/v1/auth/users",
            headers=ah,
            json={"username": "orgmgr", "password": "OrgMgr12", "duty": "user"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/v1/orgs/bu-u/members",
            headers=ah,
            json={"username": "orgmgr", "role": "admin"},
        ).status_code
        == 200
    )

    mh = {**_login(client, "orgmgr", "OrgMgr12"), "X-Org-Id": "bu-u"}

    # 无 X-Org-Id 不可管用户
    bare = _login(client, "orgmgr", "OrgMgr12")
    assert client.get("/api/v1/auth/users", headers=bare).status_code == 403

    # 组织管理员创建用户 → 自动入组织
    r = client.post(
        "/api/v1/auth/users",
        headers=mh,
        json={"username": "newbie", "password": "Newbie12", "duty": "org_member"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "operator"
    newbie_id = r.json()["id"]

    r = client.get("/api/v1/auth/users", headers=mh)
    assert r.status_code == 200
    names = {u["username"] for u in page_items(r.json())}
    assert "newbie" in names
    assert "orgmgr" in names

    # 不可改平台角色
    r = client.patch(
        f"/api/v1/auth/users/{newbie_id}",
        headers=mh,
        json={"role": "admin"},
    )
    assert r.status_code == 403

    # 可禁用
    r = client.patch(
        f"/api/v1/auth/users/{newbie_id}",
        headers=mh,
        json={"disabled": True},
    )
    assert r.status_code == 200
    assert r.json()["disabled"] is True

    # 不可删除（仅平台 admin）
    assert client.delete(f"/api/v1/auth/users/{newbie_id}", headers=mh).status_code == 403

    # 审计带 org_id
    r = client.get("/api/v1/audit?action=user.create", headers=mh)
    assert r.status_code == 200
    assert page_items(r.json())
    assert all(a.get("org_id") == "bu-u" for a in page_items(r.json()))


def test_platform_admin_audit_org_filter(client: TestClient):
    ah = _login(client)
    client.post("/api/v1/orgs", headers=ah, json={"id": "bu-a", "name": "A"})
    client.post("/api/v1/orgs", headers=ah, json={"id": "bu-b", "name": "B"})
    client.post(
        "/api/v1/auth/users",
        headers={**ah, "X-Org-Id": "bu-a"},
        json={"username": "ua", "password": "UserAaa1", "duty": "org_member"},
    )
    client.post(
        "/api/v1/auth/users",
        headers={**ah, "X-Org-Id": "bu-b"},
        json={"username": "ub", "password": "UserBbb1", "duty": "org_member"},
    )

    r = client.get("/api/v1/audit?action=user.create&org_id=bu-a", headers=ah)
    assert r.status_code == 200
    assert page_items(r.json())
    assert all(a["org_id"] == "bu-a" for a in page_items(r.json()))


def test_create_user_org_and_project_in_one_request(client: TestClient):
    """建账号 + 组织角色 + 项目角色同一事务，失败则账号也不落库。"""
    ah = _login(client)
    assert client.post("/api/v1/orgs", headers=ah, json={"id": "bu-one", "name": "One"}).status_code == 200
    h = {**ah, "X-Org-Id": "bu-one"}
    assert (
        client.post(
            "/api/v1/projects",
            headers=h,
            json={"id": "p-one", "name": "P", "org_id": "bu-one"},
        ).status_code
        == 200
    )

    r = client.post(
        "/api/v1/auth/users",
        headers=h,
        json={
            "username": "lead1",
            "password": "Leaduser1",
            "duty": "project_owner",
            "project_id": "p-one",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "operator"

    members = page_items(client.get("/api/v1/orgs/bu-one/members", headers=h).json())
    lead = next(m for m in members if m["username"] == "lead1")
    assert lead["role"] == "member"

    pm = page_items(client.get("/api/v1/projects/p-one/members", headers=h).json())
    prow = next(m for m in pm if m["username"] == "lead1")
    assert prow["role"] == "owner"

    bad = client.post(
        "/api/v1/auth/users",
        headers=h,
        json={
            "username": "ghost1",
            "password": "Ghostuser1",
            "duty": "project_member",
            "project_id": "no-such-project",
        },
    )
    assert bad.status_code in (400, 404, 409)
    names = {u["username"] for u in page_items(client.get("/api/v1/auth/users", headers=h).json())}
    assert "ghost1" not in names
