"""组织策略：默认 member 不能建项目/邀请；开关打开后仅放行约定能力。"""

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
    db_path = tmp_path / "org_policies.db"
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


def _bootstrap_org(client: TestClient) -> tuple[dict, dict, dict]:
    ah = _login(client)
    assert (
        client.post(
            "/api/v1/orgs",
            headers=ah,
            json={"id": "bu-pol", "name": "策略部"},
        ).status_code
        == 200
    )
    for name, pw, role in (
        ("lead", "Leaduser1", "owner"),
        ("alice", "Alice123", "member"),
        ("bob", "Bob12345", "member"),
    ):
        assert (
            client.post(
                "/api/v1/auth/users",
                headers=ah,
                json={"username": name, "password": pw, "duty": "user"},
            ).status_code
            == 200
        )
        if name != "lead":
            assert (
                client.post(
                    "/api/v1/orgs/bu-pol/members",
                    headers=ah,
                    json={"username": name, "role": role},
                ).status_code
                == 200
            )
        else:
            assert (
                client.post(
                    "/api/v1/orgs/bu-pol/members",
                    headers=ah,
                    json={"username": name, "role": "owner"},
                ).status_code
                == 200
            )
    lead_h = _login(client, "lead", "Leaduser1")
    alice_h = _login(client, "alice", "Alice123")
    return ah, lead_h, alice_h


def test_org_out_includes_default_policies(client: TestClient):
    ah = _login(client)
    r = client.post("/api/v1/orgs", headers=ah, json={"id": "bu-def", "name": "默认"})
    assert r.status_code == 200, r.text
    policies = r.json()["policies"]
    assert policies["members_can_create_projects"] is False
    assert policies["members_can_invite"] is False
    got = client.get("/api/v1/orgs/bu-def", headers=ah)
    assert got.status_code == 200
    assert got.json()["policies"] == policies


def test_member_cannot_create_project_by_default(client: TestClient):
    _, lead_h, alice_h = _bootstrap_org(client)
    r = client.post(
        "/api/v1/projects",
        headers={**alice_h, "X-Org-Id": "bu-pol"},
        json={"id": "p-denied", "name": "Denied", "org_id": "bu-pol"},
    )
    assert r.status_code == 403, r.text
    body = r.json()
    assert "不允许普通成员创建项目" in str(body.get("message") or body.get("detail") or r.text)

    ok = client.post(
        "/api/v1/projects",
        headers={**lead_h, "X-Org-Id": "bu-pol"},
        json={"id": "p-lead", "name": "Lead", "org_id": "bu-pol"},
    )
    assert ok.status_code == 200, ok.text


def test_member_can_create_project_when_policy_on(client: TestClient):
    ah, lead_h, alice_h = _bootstrap_org(client)
    patched = client.patch(
        "/api/v1/orgs/bu-pol/policies",
        headers=lead_h,
        json={"members_can_create_projects": True},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["policies"]["members_can_create_projects"] is True

    denied = client.patch(
        "/api/v1/orgs/bu-pol/policies",
        headers=alice_h,
        json={"members_can_create_projects": False},
    )
    assert denied.status_code == 403, denied.text

    r = client.post(
        "/api/v1/projects",
        headers={**alice_h, "X-Org-Id": "bu-pol"},
        json={"id": "p-alice", "name": "Alice", "org_id": "bu-pol"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["org_id"] == "bu-pol"
    # 平台 admin 旁路不受组织策略影响
    admin_p = client.post(
        "/api/v1/projects",
        headers={**ah, "X-Org-Id": "bu-pol"},
        json={"id": "p-admin", "name": "Admin", "org_id": "bu-pol"},
    )
    assert admin_p.status_code == 200, admin_p.text


def test_member_invite_policy(client: TestClient):
    _, lead_h, alice_h = _bootstrap_org(client)
    ah = _login(client)
    assert (
        client.post(
            "/api/v1/auth/users",
            headers=ah,
            json={"username": "carol", "password": "Carol123", "duty": "user"},
        ).status_code
        == 200
    )

    blocked = client.post(
        "/api/v1/orgs/bu-pol/members",
        headers=alice_h,
        json={"username": "carol", "role": "member"},
    )
    assert blocked.status_code == 403, blocked.text

    assert (
        client.patch(
            "/api/v1/orgs/bu-pol/policies",
            headers=lead_h,
            json={"members_can_invite": True},
        ).status_code
        == 200
    )

    invited = client.post(
        "/api/v1/orgs/bu-pol/members",
        headers=alice_h,
        json={"username": "carol", "role": "member"},
    )
    assert invited.status_code == 200, invited.text
    assert invited.json()["role"] == "member"

    elevate = client.post(
        "/api/v1/orgs/bu-pol/members",
        headers=alice_h,
        json={"username": "bob", "role": "admin"},
    )
    assert elevate.status_code == 403, elevate.text
