"""项目邀请：创建链接 + 登录接受 + 自助注册入项。"""

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


def test_invite_register_and_viewer_write_denied(client: TestClient):
    ah = _login(client)
    assert client.post(
        "/api/v1/orgs", headers=ah, json={"id": "org-inv", "name": "Inv"}
    ).status_code == 200
    assert client.post(
        "/api/v1/projects",
        headers={**ah, "X-Org-Id": "org-inv"},
        json={"id": "inv-proj", "name": "Invite Proj", "org_id": "org-inv"},
    ).status_code == 200

    r = client.post(
        "/api/v1/projects/inv-proj/invites",
        headers=ah,
        json={"role": "viewer", "expires_hours": 24, "max_uses": 2, "label": "guest"},
    )
    assert r.status_code == 200, r.text
    token = r.json()["token"]

    prev = client.get(f"/api/v1/invites/{token}")
    assert prev.status_code == 200
    assert prev.json()["valid"] is True
    assert prev.json()["project_id"] == "inv-proj"

    r = client.post(
        f"/api/v1/invites/{token}/register",
        json={"username": "newbie", "password": "Secret12"},
    )
    assert r.status_code == 200, r.text
    nh = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert r.json()["user"]["username"] == "newbie"

    # viewer 可读项目、不可写设计
    r = client.get("/api/v1/projects", headers=nh)
    assert any(p["id"] == "inv-proj" for p in page_items(r.json()))

    r = client.post(
        "/api/v1/design/requirements",
        headers=nh,
        json={"project_id": "inv-proj", "title": "nope", "content": "x"},
    )
    assert r.status_code == 403, r.text

    r = client.get("/api/v1/design/requirements?project_id=inv-proj", headers=nh)
    assert r.status_code == 200

    # 再邀请 member：已有用户登录接受
    r = client.post(
        "/api/v1/projects/inv-proj/invites",
        headers=ah,
        json={"role": "member", "expires_hours": 24, "max_uses": 1},
    )
    assert r.status_code == 200
    mem_token = r.json()["token"]

    client.post(
        "/api/v1/auth/users",
        headers=ah,
        json={"username": "carol", "password": "Carol123", "duty": "user"},
    )
    ch = _login(client, "carol", "Carol123")
    r = client.post(f"/api/v1/invites/{mem_token}/accept", headers=ch)
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "member"

    r = client.post(
        "/api/v1/design/requirements",
        headers=ch,
        json={"project_id": "inv-proj", "title": "ok", "content": "y"},
    )
    assert r.status_code == 200, r.text
