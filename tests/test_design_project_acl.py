"""设计域项目成员门禁：非成员不可跨项目读写。"""

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


def test_design_cross_project_denied(client: TestClient):
    ah = _login(client)
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
    assert client.post(
        "/api/v1/orgs", headers=ah, json={"id": "org-design", "name": "Design"}
    ).status_code == 200
    assert client.post(
        "/api/v1/projects",
        headers={**ah, "X-Org-Id": "org-design"},
        json={"id": "design-a", "name": "A", "org_id": "org-design"},
    ).status_code == 200
    assert client.post(
        "/api/v1/projects/design-a/members",
        headers=ah,
        json={"username": "alice", "role": "member"},
    ).status_code == 200

    alice_h = _login(client, "alice", "Alice123")
    bob_h = _login(client, "bob", "Bob12345")

    r = client.post(
        "/api/v1/design/requirements",
        headers=alice_h,
        json={"project_id": "design-a", "title": "仅 Alice", "content": "x"},
    )
    assert r.status_code == 200, r.text
    req_id = r.json()["id"]

    r = client.post(
        "/api/v1/design/requirements",
        headers=bob_h,
        json={"project_id": "design-a", "title": "Bob 闯入", "content": "y"},
    )
    assert r.status_code == 403, r.text

    r = client.get("/api/v1/design/requirements?project_id=design-a", headers=bob_h)
    assert r.status_code == 403, r.text

    r = client.get(f"/api/v1/design/requirements/{req_id}", headers=bob_h)
    assert r.status_code == 403, r.text

    r = client.get("/api/v1/design/requirements", headers=bob_h)
    assert r.status_code == 200
    assert all(x["project_id"] != "design-a" for x in r.json())

    r = client.get("/api/v1/design/requirements?project_id=design-a", headers=alice_h)
    assert r.status_code == 200
    assert any(x["id"] == req_id for x in r.json())

    r = client.get("/api/v1/design/projects/design-a/logical-cases/export", headers=bob_h)
    assert r.status_code == 403, r.text
