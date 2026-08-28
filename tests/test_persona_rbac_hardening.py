"""人设 RBAC 硬化：my_role、跨项目 batch-delete、空 project 写、建组织。"""

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
    db_path = tmp_path / "persona_rbac.db"
    url = f"sqlite:///{db_path.as_posix()}"
    monkeypatch.setenv("MC_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("MC_APP_BUILDS_DIR", str(tmp_path / "app_builds"))
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


def _add_user(client: TestClient, ah: dict, username: str, password: str) -> None:
    r = client.post(
        "/api/v1/auth/users",
        headers=ah,
        json={"username": username, "password": password, "duty": "user"},
    )
    assert r.status_code in (200, 201, 409), r.text


def test_project_list_includes_my_role(client: TestClient):
    ah = _login(client)
    _add_user(client, ah, "alice", "Alice123")
    assert (
        client.post("/api/v1/orgs", headers=ah, json={"id": "org-role", "name": "Role"}).status_code
        == 200
    )
    assert (
        client.post(
            "/api/v1/projects",
            headers={**ah, "X-Org-Id": "org-role"},
            json={"id": "p-role", "name": "Role", "org_id": "org-role"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/v1/projects/p-role/members",
            headers=ah,
            json={"username": "alice", "role": "viewer"},
        ).status_code
        == 200
    )

    admin_projects = page_items(client.get("/api/v1/projects", headers=ah).json())
    hit = next(p for p in admin_projects if p["id"] == "p-role")
    assert hit.get("my_role") == "owner"

    alice_h = _login(client, "alice", "Alice123")
    alice_projects = page_items(
        client.get("/api/v1/projects", headers=alice_h).json()
    )
    hit = next(p for p in alice_projects if p["id"] == "p-role")
    assert hit.get("my_role") == "viewer"


def test_batch_delete_cross_project_denied(client: TestClient):
    ah = _login(client)
    _add_user(client, ah, "alice", "Alice123")
    assert (
        client.post("/api/v1/orgs", headers=ah, json={"id": "org-batch", "name": "Batch"}).status_code
        == 200
    )
    for pid in ("pa", "pb"):
        assert (
            client.post(
                "/api/v1/projects",
                headers={**ah, "X-Org-Id": "org-batch"},
                json={"id": pid, "name": pid, "org_id": "org-batch"},
            ).status_code
            == 200
        )
    assert (
        client.post(
            "/api/v1/projects/pa/members",
            headers=ah,
            json={"username": "alice", "role": "member"},
        ).status_code
        == 200
    )

    alice_h = _login(client, "alice", "Alice123")
    r = client.post(
        "/api/v1/design/requirements",
        headers=alice_h,
        json={"project_id": "pa", "title": "own", "content": "a"},
    )
    assert r.status_code == 200, r.text
    own_id = r.json()["id"]

    r = client.post(
        "/api/v1/design/requirements",
        headers=ah,
        json={"project_id": "pb", "title": "other", "content": "b"},
    )
    assert r.status_code == 200, r.text
    other_id = r.json()["id"]

    r = client.post(
        "/api/v1/design/requirements/batch-delete",
        headers=alice_h,
        json={"item_ids": [own_id, other_id]},
    )
    assert r.status_code == 403, r.text

    # 夹带失败后两侧资源仍在
    assert (
        client.get(f"/api/v1/design/requirements/{own_id}", headers=alice_h).status_code
        == 200
    )
    assert (
        client.get(f"/api/v1/design/requirements/{other_id}", headers=ah).status_code
        == 200
    )


def test_empty_project_job_create_denied_for_everyone(client: TestClient):
    ah = _login(client)
    _add_user(client, ah, "alice", "Alice123")
    alice_h = _login(client, "alice", "Alice123")
    body = {
        "name": "no-project",
        "platform": "web",
        "project_dir": "/tmp/fake",
        "project_id": "",
    }
    r = client.post("/api/v1/jobs", headers=alice_h, json=body)
    assert r.status_code == 403, r.text
    r = client.post("/api/v1/jobs", headers=ah, json=body)
    assert r.status_code == 403, r.text


def test_operator_cannot_create_organization(client: TestClient):
    ah = _login(client)
    _add_user(client, ah, "alice", "Alice123")
    alice_h = _login(client, "alice", "Alice123")
    r = client.post(
        "/api/v1/orgs",
        headers=alice_h,
        json={"id": "bu-x", "name": "X"},
    )
    assert r.status_code == 403, r.text

    r = client.post(
        "/api/v1/orgs",
        headers=ah,
        json={"id": "bu-admin", "name": "Admin Org"},
    )
    assert r.status_code == 200, r.text
