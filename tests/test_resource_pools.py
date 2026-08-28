"""Phase 3 资源池：跨组织隔离、角色、调度兼容、删除安全。"""

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

from autopilot_platform.core.constants import DEFAULT_API_TOKEN
from autopilot_platform.platform.app import create_app
from autopilot_platform.platform.core.db import reset_engine

TOKEN = {"X-API-Token": DEFAULT_API_TOKEN}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "resource_pools.db"
    url = f"sqlite:///{db_path.as_posix()}"
    monkeypatch.setenv("MC_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("MC_ADMIN_USER", "admin")
    monkeypatch.setenv("MC_ADMIN_PASSWORD", "admin")
    monkeypatch.setenv("MC_SCHEDULE_ENABLED", "0")
    monkeypatch.setenv("MC_RUNTIME_CONFIG", str(tmp_path / "mc_runtime_config.json"))
    monkeypatch.setenv("MC_JOB_LOGS_DIR", str(tmp_path / "job_logs"))
    monkeypatch.setenv("MC_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("MC_ADMIN_API_TOKEN", raising=False)
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


def _create_user(client: TestClient, ah: dict, username: str, password: str) -> None:
    r = client.post(
        "/api/v1/auth/users",
        headers=ah,
        json={"username": username, "password": password, "duty": "user"},
    )
    assert r.status_code == 200, r.text


def _seed_org_project(
    client: TestClient,
    ah: dict,
    *,
    org_id: str,
    project_id: str,
    owner: str | None = None,
) -> None:
    assert (
        client.post(
            "/api/v1/orgs",
            headers=ah,
            json={"id": org_id, "name": org_id},
        ).status_code
        == 200
    )
    r = client.post(
        "/api/v1/projects",
        headers={**ah, "X-Org-Id": org_id},
        json={"id": project_id, "name": project_id, "org_id": org_id},
    )
    assert r.status_code == 200, r.text
    if owner and owner != "admin":
        assert (
            client.post(
                f"/api/v1/projects/{project_id}/members",
                headers=ah,
                json={"username": owner, "role": "owner"},
            ).status_code
            == 200
        )


def _register_runner(
    client: TestClient,
    runner_id: str,
    *,
    org_id: str,
    udid: str,
) -> str:
    assert (
        client.post(
            "/api/v1/runners/register",
            headers=TOKEN,
            json={
                "runner_id": runner_id,
                "hostname": runner_id,
                "capabilities": ["android"],
            },
        ).status_code
        == 200
    )
    admin = _login(client)
    assert (
        client.patch(
            f"/api/v1/runners/{runner_id}/scope",
            headers=admin,
            json={"org_id": org_id, "project_ids": []},
        ).status_code
        == 200
    )
    hb = client.post(
        "/api/v1/runners/heartbeat",
        headers=TOKEN,
        json={
            "runner_id": runner_id,
            "inventory": [
                {
                    "udid": udid,
                    "platform": "android",
                    "name": udid,
                    "state": "ready",
                    "backends": ["android-appium"],
                }
            ], "devices": [
                {
                    "udid": udid,
                    "platform": "android",
                    "name": udid,
                    "state": "ready",
                    "backends": ["android-appium"],
                }
            ],
        },
    )
    assert hb.status_code == 200, hb.text
    devices = page_items(client.get("/api/v1/devices", headers=admin).json())
    hit = next(
        (d for d in devices if d.get("udid") == udid and d.get("runner_id") == runner_id),
        None,
    )
    assert hit is not None, devices
    device_id = str(hit.get("id") or "")
    assert device_id, hit
    return device_id


def test_org_isolation_and_roles(client: TestClient):
    ah = _login(client)
    _create_user(client, ah, "alice", "Alice123")
    _create_user(client, ah, "bob", "Bob12345")
    _create_user(client, ah, "viewer1", "Viewer123")
    _seed_org_project(client, ah, org_id="org-a", project_id="proj-a", owner="alice")
    _seed_org_project(client, ah, org_id="org-b", project_id="proj-b", owner="bob")

    assert (
        client.post(
            "/api/v1/orgs/org-a/members",
            headers=ah,
            json={"username": "alice", "role": "admin"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/v1/orgs/org-b/members",
            headers=ah,
            json={"username": "bob", "role": "admin"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/v1/projects/proj-a/members",
            headers=ah,
            json={"username": "viewer1", "role": "viewer"},
        ).status_code
        == 200
    )

    alice = _login(client, "alice", "Alice123")
    bob = _login(client, "bob", "Bob12345")
    viewer = _login(client, "viewer1", "Viewer123")

    r = client.post(
        "/api/v1/orgs/org-a/resource-pools",
        headers={**alice, "X-Org-Id": "org-a"},
        json={"name": "lab-a", "description": "A"},
    )
    assert r.status_code == 201, r.text
    pool_a = r.json()["id"]

    r = client.get(
        "/api/v1/orgs/org-a/resource-pools",
        headers={**bob, "X-Org-Id": "org-a"},
    )
    assert r.status_code == 403

    r = client.patch(
        f"/api/v1/resource-pools/{pool_a}",
        headers={**bob, "X-Org-Id": "org-b"},
        json={"enabled": False},
    )
    assert r.status_code == 403

    r = client.post(
        "/api/v1/orgs/org-a/resource-pools",
        headers={**viewer, "X-Org-Id": "org-a"},
        json={"name": "viewer-pool"},
    )
    assert r.status_code == 403

    assert (
        client.post(
            f"/api/v1/resource-pools/{pool_a}/projects",
            headers={**alice, "X-Org-Id": "org-a"},
            json={"project_id": "proj-a"},
        ).status_code
        == 200
    )
    r = client.get(
        "/api/v1/orgs/org-a/resource-pools?project_id=proj-a",
        headers=viewer,
    )
    assert r.status_code == 200, r.text
    assert any(item["id"] == pool_a for item in page_items(r.json()))
    assert all(not item["can_manage"] for item in page_items(r.json()))


def test_claim_uses_authorized_pool_and_legacy_compat(client: TestClient):
    ah = _login(client)
    _seed_org_project(client, ah, org_id="org-c", project_id="proj-c")
    device_id = _register_runner(client, "runner-c", org_id="org-c", udid="udid-c")

    # 存量：无池时仍可 claim
    job = client.post(
        "/api/v1/jobs",
        headers=ah,
        json={
            "name": "legacy",
            "project_dir": "/tmp/legacy",
            "platform": "android",
            "project_id": "proj-c",
            "device_udids": ["udid-c"],
            "preferred_runner_id": "runner-c",
        },
    ).json()
    claimed = client.post(
        "/api/v1/jobs/claim?runner_id=runner-c", headers=TOKEN
    ).json()
    assert claimed and claimed["id"] == job["id"]
    client.post(
        f"/api/v1/jobs/{job['id']}/complete?runner_id=runner-c",
        headers=TOKEN,
        json={"status": "succeeded"},
    )

    pool = client.post(
        "/api/v1/orgs/org-c/resource-pools",
        headers={**ah, "X-Org-Id": "org-c"},
        json={"name": "pool-c"},
    ).json()
    assert (
        client.post(
            f"/api/v1/resource-pools/{pool['id']}/runners",
            headers=ah,
            json={"resource_id": "runner-c"},
        ).status_code
        == 200
    )

    # 有启用池但未授权项目：fail-closed
    blocked = client.post(
        "/api/v1/jobs",
        headers=ah,
        json={
            "name": "blocked",
            "project_dir": "/tmp/blocked",
            "platform": "android",
            "project_id": "proj-c",
            "device_udids": ["udid-c"],
            "preferred_runner_id": "runner-c",
        },
    ).json()
    assert (
        client.post("/api/v1/jobs/claim?runner_id=runner-c", headers=TOKEN).json()
        is None
    )
    assert client.get(f"/api/v1/jobs/{blocked['id']}", headers=ah).json()["status"] == "pending"

    assert (
        client.post(
            f"/api/v1/resource-pools/{pool['id']}/projects",
            headers=ah,
            json={"project_id": "proj-c"},
        ).status_code
        == 200
    )
    # 先取消此前 fail-closed 留下的 pending，再验证授权后可 claim
    assert (
        client.post(f"/api/v1/jobs/{blocked['id']}/cancel", headers=ah).status_code
        == 200
    )
    allowed = client.post(
        "/api/v1/jobs",
        headers=ah,
        json={
            "name": "allowed",
            "project_dir": "/tmp/allowed",
            "platform": "android",
            "project_id": "proj-c",
            "device_udids": ["udid-c"],
            "preferred_runner_id": "runner-c",
        },
    ).json()
    claimed2 = client.post(
        "/api/v1/jobs/claim?runner_id=runner-c", headers=TOKEN
    ).json()
    assert claimed2 and claimed2["id"] == allowed["id"]
    assert device_id


def test_delete_pool_blocks_active_jobs(client: TestClient):
    ah = _login(client)
    _seed_org_project(client, ah, org_id="org-d", project_id="proj-d")
    _register_runner(client, "runner-d", org_id="org-d", udid="udid-d")
    pool = client.post(
        "/api/v1/orgs/org-d/resource-pools",
        headers={**ah, "X-Org-Id": "org-d"},
        json={"name": "pool-d"},
    ).json()
    assert (
        client.post(
            f"/api/v1/resource-pools/{pool['id']}/runners",
            headers=ah,
            json={"resource_id": "runner-d"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/v1/resource-pools/{pool['id']}/projects",
            headers=ah,
            json={"project_id": "proj-d"},
        ).status_code
        == 200
    )
    job = client.post(
        "/api/v1/jobs",
        headers=ah,
        json={
            "name": "active",
            "project_dir": "/tmp/active",
            "platform": "android",
            "project_id": "proj-d",
            "device_udids": ["udid-d"],
            "preferred_runner_id": "runner-d",
        },
    ).json()
    claimed = client.post(
        "/api/v1/jobs/claim?runner_id=runner-d", headers=TOKEN
    ).json()
    assert claimed and claimed["id"] == job["id"]
    client.post(f"/api/v1/jobs/{job['id']}/running?runner_id=runner-d", headers=TOKEN)

    r = client.delete(f"/api/v1/resource-pools/{pool['id']}", headers=ah)
    assert r.status_code == 409, r.text

    client.post(
        f"/api/v1/jobs/{job['id']}/complete?runner_id=runner-d",
        headers=TOKEN,
        json={"status": "succeeded"},
    )
    r = client.delete(f"/api/v1/resource-pools/{pool['id']}", headers=ah)
    assert r.status_code == 200, r.text
    assert client.get(f"/api/v1/jobs/{job['id']}", headers=ah).status_code == 200


def test_single_device_membership_does_not_leak_runner_siblings(client: TestClient):
    ah = _login(client)
    _create_user(client, ah, "pool-user", "PoolUser123")
    _seed_org_project(
        client, ah, org_id="org-device-only", project_id="proj-device-only", owner="pool-user"
    )
    first_id = _register_runner(
        client, "runner-device-only", org_id="org-device-only", udid="device-allowed"
    )
    heartbeat = client.post(
        "/api/v1/runners/heartbeat",
        headers=TOKEN,
        json={
            "runner_id": "runner-device-only",
            "inventory": [
                {"udid": "device-allowed", "platform": "android", "state": "ready"},
                {"udid": "device-secret", "platform": "android", "state": "ready"},
            ], "devices": [
                {"udid": "device-allowed", "platform": "android", "state": "ready"},
                {"udid": "device-secret", "platform": "android", "state": "ready"},
            ],
        },
    )
    assert heartbeat.status_code == 200
    pool = client.post(
        "/api/v1/orgs/org-device-only/resource-pools",
        headers=ah,
        json={"name": "device-only"},
    ).json()
    assert client.post(
        f"/api/v1/resource-pools/{pool['id']}/projects",
        headers=ah,
        json={"project_id": "proj-device-only"},
    ).status_code == 200
    assert client.post(
        f"/api/v1/resource-pools/{pool['id']}/devices",
        headers=ah,
        json={"resource_id": first_id},
    ).status_code == 200

    user = _login(client, "pool-user", "PoolUser123")
    visible = client.get(
        "/api/v1/devices?project_id=proj-device-only", headers=user
    )
    assert visible.status_code == 200
    assert {d["udid"] for d in page_items(visible.json())} == {"device-allowed"}
    runners = client.get(
        "/api/v1/runners?project_id=proj-device-only", headers=user
    )
    assert [r["runner_id"] for r in page_items(runners.json())] == ["runner-device-only"]


def test_project_query_does_not_mix_other_org_resources_in_legacy_mode(client: TestClient):
    ah = _login(client)
    _create_user(client, ah, "multi-org", "MultiOrg123")
    for suffix in ("a", "b"):
        _seed_org_project(
            client,
            ah,
            org_id=f"org-{suffix}-scope",
            project_id=f"proj-{suffix}-scope",
            owner="multi-org",
        )
        assert client.post(
            f"/api/v1/orgs/org-{suffix}-scope/members",
            headers=ah,
            json={"username": "multi-org", "role": "member"},
        ).status_code == 200
        _register_runner(
            client,
            f"runner-{suffix}-scope",
            org_id=f"org-{suffix}-scope",
            udid=f"device-{suffix}-scope",
        )

    user = _login(client, "multi-org", "MultiOrg123")
    devices = client.get("/api/v1/devices?project_id=proj-a-scope", headers=user)
    assert devices.status_code == 200
    assert {d["udid"] for d in page_items(devices.json())} == {"device-a-scope"}
    runners = client.get("/api/v1/runners?project_id=proj-a-scope", headers=user)
    assert runners.status_code == 200
    assert {r["runner_id"] for r in page_items(runners.json())} == {"runner-a-scope"}
    mismatched = client.get(
        "/api/v1/devices?project_id=proj-a-scope",
        headers={**user, "X-Org-Id": "org-b-scope"},
    )
    assert mismatched.status_code == 403


def test_pool_uniqueness_idempotent_binding_and_disabled_fail_closed(client: TestClient):
    ah = _login(client)
    _seed_org_project(client, ah, org_id="org-constraints", project_id="proj-constraints")
    _register_runner(
        client, "runner-constraints", org_id="org-constraints", udid="device-constraints"
    )
    created = client.post(
        "/api/v1/orgs/org-constraints/resource-pools",
        headers=ah,
        json={"name": "unique"},
    )
    assert created.status_code == 201
    pool = created.json()
    duplicate = client.post(
        "/api/v1/orgs/org-constraints/resource-pools",
        headers=ah,
        json={"name": "unique"},
    )
    assert duplicate.status_code == 409
    for _ in range(2):
        bound = client.post(
            f"/api/v1/resource-pools/{pool['id']}/runners",
            headers=ah,
            json={"resource_id": "runner-constraints"},
        )
        assert bound.status_code == 200
        assert bound.json()["runner_ids"] == ["runner-constraints"]
        granted = client.post(
            f"/api/v1/resource-pools/{pool['id']}/projects",
            headers=ah,
            json={"project_id": "proj-constraints"},
        )
        assert granted.status_code == 200
        assert granted.json()["project_ids"] == ["proj-constraints"]

    assert client.patch(
        f"/api/v1/resource-pools/{pool['id']}",
        headers=ah,
        json={"enabled": False},
    ).status_code == 200
    job = client.post(
        "/api/v1/jobs",
        headers=ah,
        json={
            "name": "disabled pool",
            "project_dir": "/tmp/p",
            "project_id": "proj-constraints",
            "platform": "android",
            "device_udids": ["device-constraints"],
            "preferred_runner_id": "runner-constraints",
        },
    )
    assert job.status_code == 200
    claim = client.post(
        "/api/v1/jobs/claim?runner_id=runner-constraints", headers=TOKEN
    )
    assert claim.status_code == 200 and claim.json() is None
    audits = client.get("/api/v1/audit", headers=ah)
    assert audits.status_code == 200
    pool_events = [
        item
        for item in page_items(audits.json())
        if item["resource_type"] == "resource_pool"
        and item["resource_id"] == pool["id"]
    ]
    assert {"resource_pool.create", "resource_pool.update"} <= {
        item["action"] for item in pool_events
    }
    assert all(item["actor"] == "admin" for item in pool_events)
    assert all(item["org_id"] == "org-constraints" for item in pool_events)
