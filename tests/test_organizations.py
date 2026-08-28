"""Organization：创建/成员/X-Org-Id 过滤项目；非成员 403。"""

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


def test_org_create_member_project_scope(client: TestClient):
    ah = _login(client)
    r = client.post(
        "/api/v1/orgs",
        headers=ah,
        json={"id": "bu-core", "name": "核心事业部"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["id"] == "bu-core"

    client.post(
        "/api/v1/auth/users",
        headers=ah,
        json={"username": "alice", "password": "Alice123", "duty": "user"},
    )
    client.post(
        "/api/v1/auth/users",
        headers=ah,
        json={"username": "bob", "password": "Bob12345", "duty": "user"},
    )

    r = client.post(
        "/api/v1/orgs/bu-core/members",
        headers=ah,
        json={"username": "alice", "role": "member"},
    )
    assert r.status_code == 200, r.text

    # 带 org 创建项目
    r = client.post(
        "/api/v1/projects",
        headers={**ah, "X-Org-Id": "bu-core"},
        json={"id": "p-core", "name": "Core", "org_id": "bu-core"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["org_id"] == "bu-core"

    # 项目必须属于组织，平台管理员也不能建无组织项目
    assert (
        client.post(
            "/api/v1/projects",
            headers=ah,
            json={"id": "p-loose", "name": "Loose"},
        ).status_code
        == 400
    )

    # admin 按 X-Org-Id 过滤
    r = client.get("/api/v1/projects", headers={**ah, "X-Org-Id": "bu-core"})
    assert r.status_code == 200
    ids = {p["id"] for p in page_items(r.json())}
    assert "p-core" in ids
    assert "p-loose" not in ids

    # alice 是组织成员，可用 X-Org-Id
    alice_h = _login(client, "alice", "Alice123")
    r = client.get("/api/v1/orgs", headers=alice_h)
    assert r.status_code == 200
    assert any(o["id"] == "bu-core" for o in page_items(r.json()))

    r = client.get("/api/v1/auth/me", headers={**alice_h, "X-Org-Id": "bu-core"})
    assert r.status_code == 200

    # bob 非组织成员：带 X-Org-Id 应 403
    bob_h = _login(client, "bob", "Bob12345")
    r = client.get("/api/v1/auth/me", headers={**bob_h, "X-Org-Id": "bu-core"})
    assert r.status_code == 403, r.text

    # alice 非项目成员时看不到项目；加入后可见且受 org 过滤
    client.post(
        "/api/v1/projects/p-core/members",
        headers=ah,
        json={"username": "alice", "role": "member"},
    )
    r = client.get("/api/v1/projects", headers={**alice_h, "X-Org-Id": "bu-core"})
    assert r.status_code == 200
    assert any(p["id"] == "p-core" for p in page_items(r.json()))


def test_non_member_cannot_create_project_in_org(client: TestClient):
    ah = _login(client)
    assert (
        client.post(
            "/api/v1/orgs",
            headers=ah,
            json={"id": "bu-x", "name": "X"},
        ).status_code
        == 200
    )
    client.post(
        "/api/v1/auth/users",
        headers=ah,
        json={"username": "carol", "password": "Carol123", "duty": "user"},
    )
    carol_h = _login(client, "carol", "Carol123")
    r = client.post(
        "/api/v1/projects",
        headers=carol_h,
        json={"id": "p-x", "name": "X", "org_id": "bu-x"},
    )
    assert r.status_code == 403, r.text
