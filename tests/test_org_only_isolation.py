"""仅 org 成员、无 project 成员：设计/制品/任务不可见或 403。"""

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

from autopilot_platform.platform.app import create_app
from autopilot_platform.platform.core.db import reset_engine


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "org_only.db"
    url = f"sqlite:///{db_path.as_posix()}"
    monkeypatch.setenv("MC_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("MC_ADMIN_USER", "admin")
    monkeypatch.setenv("MC_ADMIN_PASSWORD", "admin")
    monkeypatch.setenv("MC_SCHEDULE_ENABLED", "0")
    monkeypatch.setenv("MC_RUNTIME_CONFIG", str(tmp_path / "mc_runtime_config.json"))
    monkeypatch.setenv("MC_JOB_LOGS_DIR", str(tmp_path / "job_logs"))
    monkeypatch.setenv("MC_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MC_API_TOKEN", "test-runner-token")
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


def _zip_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("a.txt", "1")
    return buf.getvalue()


def test_org_member_without_project_cannot_see_content(client: TestClient):
    ah = _login(client)
    assert (
        client.post(
            "/api/v1/orgs",
            headers=ah,
            json={"id": "bu-iso", "name": "隔离事业部"},
        ).status_code
        == 200
    )
    client.post(
        "/api/v1/auth/users",
        headers=ah,
        json={"username": "orgonly", "password": "OrgOnly1", "duty": "user"},
    )
    client.post(
        "/api/v1/auth/users",
        headers=ah,
        json={"username": "projmem", "password": "ProjMem1", "duty": "user"},
    )
    assert (
        client.post(
            "/api/v1/orgs/bu-iso/members",
            headers=ah,
            json={"username": "orgonly", "role": "member"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/v1/orgs/bu-iso/members",
            headers=ah,
            json={"username": "projmem", "role": "member"},
        ).status_code
        == 200
    )

    # 平台 admin 建项目并加入 projmem
    r = client.post(
        "/api/v1/projects",
        headers={**ah, "X-Org-Id": "bu-iso"},
        json={"id": "p-iso", "name": "Iso", "org_id": "bu-iso"},
    )
    assert r.status_code == 200, r.text
    assert (
        client.post(
            "/api/v1/projects/p-iso/members",
            headers=ah,
            json={"username": "projmem", "role": "member"},
        ).status_code
        == 200
    )

    # 项目成员写入设计 + 制品 + Job
    pm = _login(client, "projmem", "ProjMem1")
    r = client.post(
        "/api/v1/design/requirements",
        headers=pm,
        json={"project_id": "p-iso", "title": "秘", "content": "x"},
    )
    assert r.status_code == 200, r.text
    req_id = r.json()["id"]

    r = client.post(
        "/api/v1/artifacts",
        headers=pm,
        files={"file": ("a.zip", _zip_bytes(), "application/zip")},
        data={"name": "art", "project_id": "p-iso"},
    )
    assert r.status_code == 200, r.text
    aid = r.json()["id"]

    r = client.post(
        "/api/v1/jobs",
        headers=pm,
        json={
            "name": "j1",
            "artifact_id": aid,
            "project_id": "p-iso",
            "platform": "android",
        },
    )
    assert r.status_code == 200, r.text
    jid = r.json()["id"]

    oo = _login(client, "orgonly", "OrgOnly1")
    oo_org = {**oo, "X-Org-Id": "bu-iso"}

    # 组织可见，项目元数据不可见
    assert any(o["id"] == "bu-iso" for o in page_items(client.get("/api/v1/orgs", headers=oo).json()))
    r = client.get("/api/v1/projects", headers=oo_org)
    assert r.status_code == 200
    assert all(p["id"] != "p-iso" for p in page_items(r.json()))

    # 设计：直链 403；列表不含
    assert (
        client.get("/api/v1/design/requirements?project_id=p-iso", headers=oo).status_code
        == 403
    )
    assert (
        client.get(f"/api/v1/design/requirements/{req_id}", headers=oo).status_code == 403
    )
    r = client.get("/api/v1/design/requirements", headers=oo)
    assert r.status_code == 200
    assert all(x.get("project_id") != "p-iso" for x in page_items(r.json()))

    # 制品 / Job：直链 403；列表不含
    assert client.get(f"/api/v1/artifacts?project_id=p-iso", headers=oo).status_code == 403
    assert client.get("/api/v1/jobs?project_id=p-iso", headers=oo).status_code == 403
    arts = page_items(client.get("/api/v1/artifacts", headers=oo).json())
    assert all(a.get("id") != aid for a in arts)
    jobs = page_items(client.get("/api/v1/jobs", headers=oo).json())
    assert all(j.get("id") != jid for j in jobs)

    # 报告按项目过滤亦 403
    assert client.get("/api/v1/reports?project_id=p-iso", headers=oo).status_code == 403


def test_org_admin_cannot_elevate_to_owner(client: TestClient):
    ah = _login(client)
    assert (
        client.post(
            "/api/v1/orgs", headers=ah, json={"id": "bu-rank", "name": "R"}
        ).status_code
        == 200
    )
    client.post(
        "/api/v1/auth/users",
        headers=ah,
        json={"username": "oadm", "password": "Oadm1234", "duty": "user"},
    )
    client.post(
        "/api/v1/auth/users",
        headers=ah,
        json={"username": "peer", "password": "Peer1234", "duty": "user"},
    )
    assert (
        client.post(
            "/api/v1/orgs/bu-rank/members",
            headers=ah,
            json={"username": "oadm", "role": "admin"},
        ).status_code
        == 200
    )
    oadm = _login(client, "oadm", "Oadm1234")
    r = client.post(
        "/api/v1/orgs/bu-rank/members",
        headers={**oadm, "X-Org-Id": "bu-rank"},
        json={"username": "peer", "role": "owner"},
    )
    assert r.status_code == 403, r.text
    # 同级 admin 允许
    r = client.post(
        "/api/v1/orgs/bu-rank/members",
        headers={**oadm, "X-Org-Id": "bu-rank"},
        json={"username": "peer", "role": "admin"},
    )
    assert r.status_code == 200, r.text


def test_org_admin_creates_project_as_first_owner(client: TestClient):
    ah = _login(client)
    assert (
        client.post(
            "/api/v1/orgs", headers=ah, json={"id": "bu-own", "name": "O"}
        ).status_code
        == 200
    )
    client.post(
        "/api/v1/auth/users",
        headers=ah,
        json={"username": "creator", "password": "Create12", "duty": "user"},
    )
    assert (
        client.post(
            "/api/v1/orgs/bu-own/members",
            headers=ah,
            json={"username": "creator", "role": "admin"},
        ).status_code
        == 200
    )
    ch = _login(client, "creator", "Create12")
    r = client.post(
        "/api/v1/projects",
        headers={**ch, "X-Org-Id": "bu-own"},
        json={"id": "p-own", "name": "Mine", "org_id": "bu-own"},
    )
    assert r.status_code == 200, r.text
    members = page_items(client.get("/api/v1/projects/p-own/members", headers=ch).json())
    mine = [m for m in members if m["username"] == "creator"]
    assert len(mine) == 1 and mine[0]["role"] == "owner"
