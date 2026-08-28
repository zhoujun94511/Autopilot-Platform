"""IDE 私有/平台共享设备与限时占用产品规则。"""

from __future__ import annotations

from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient

from list_page_helpers import page_items

from autopilot_platform.core.constants import DEFAULT_API_TOKEN
from autopilot_platform.platform.app import create_app
from autopilot_platform.platform.core.db import reset_engine
from autopilot_platform.platform.core.models import DeviceReservationRow, DeviceRow, utcnow

TOKEN = {"X-API-Token": DEFAULT_API_TOKEN}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MC_ADMIN_USER", "admin")
    monkeypatch.setenv("MC_ADMIN_PASSWORD", "admin")
    monkeypatch.setenv("MC_SCHEDULE_ENABLED", "0")
    monkeypatch.setenv("MC_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MC_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("MC_RUNTIME_CONFIG", str(tmp_path / "runtime.json"))
    monkeypatch.delenv("MC_ADMIN_API_TOKEN", raising=False)
    reset_engine()
    app = create_app(database_url=f"sqlite:///{(tmp_path / 'db.sqlite').as_posix()}")
    with TestClient(app) as c:
        yield c
    reset_engine()


def login(client: TestClient, username: str, password: str) -> dict:
    out = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    assert out.status_code == 200, out.text
    return {"Authorization": f"Bearer {out.json()['access_token']}"}


def setup_users_and_project(client: TestClient) -> tuple[dict, dict, dict]:
    admin = login(client, "admin", "admin")
    for username, password in (("alice", "Alice123"), ("bob", "Bob12345")):
        out = client.post(
            "/api/v1/auth/users",
            headers=admin,
            json={"username": username, "password": password, "duty": "user"},
        )
        assert out.status_code == 200, out.text
    assert client.post(
        "/api/v1/orgs",
        headers=admin,
        json={"id": "org-1", "name": "Org 1"},
    ).status_code == 200
    assert client.post(
        "/api/v1/projects",
        headers={**admin, "X-Org-Id": "org-1"},
        json={"id": "project-1", "name": "P1", "org_id": "org-1"},
    ).status_code == 200
    for username in ("alice", "bob"):
        assert client.post(
            "/api/v1/orgs/org-1/members",
            headers=admin,
            json={"username": username, "role": "member"},
        ).status_code == 200
        assert client.post(
            "/api/v1/projects/project-1/members",
            headers=admin,
            json={"username": username, "role": "member"},
        ).status_code == 200
    return admin, login(client, "alice", "Alice123"), login(client, "bob", "Bob12345")


def register_ide(
    client: TestClient,
    user_headers: dict,
    runner_id: str,
    udid: str,
    *,
    token_issuer: dict | None = None,
) -> tuple[str, str]:
    out = client.post(
        "/api/v1/runners/register",
        headers=user_headers,
        json={
            "runner_id": runner_id,
            "hostname": "ide-host",
            "registration_source": "ide",
            "capabilities": ["android"],
        },
    )
    assert out.status_code == 200, out.text
    issued = client.post(
        f"/api/v1/runners/{runner_id}/scoped-token",
        headers=token_issuer or user_headers,
        json={"org_id": "org-1", "project_ids": ["project-1"]},
    )
    assert issued.status_code == 200, issued.text
    token = issued.json()["api_token"]
    hb = client.post(
        "/api/v1/runners/heartbeat",
        headers={"X-API-Token": token},
        json={
            "runner_id": runner_id,
            "inventory": [{"udid": udid, "platform": "android", "state": "ready"}], "devices": [{"udid": udid, "platform": "android", "state": "ready"}],
        },
    )
    assert hb.status_code == 200, hb.text
    return runner_id, token


def register_shared(
    client: TestClient, admin: dict, runner_id: str, udid: str
) -> tuple[str, str]:
    assert client.post(
        "/api/v1/runners/register",
        headers=TOKEN,
        json={
            "runner_id": runner_id,
            "hostname": "platform-host",
            "registration_source": "platform",
            "capabilities": ["android"],
        },
    ).status_code == 200
    assert client.patch(
        f"/api/v1/runners/{runner_id}/scope",
        headers=admin,
        json={"org_id": "org-1", "project_ids": ["project-1"]},
    ).status_code == 200
    issued = client.post(
        f"/api/v1/runners/{runner_id}/token",
        headers=admin,
        json={"org_id": "org-1", "project_ids": ["project-1"]},
    )
    assert issued.status_code == 200, issued.text
    token = issued.json()["api_token"]
    assert client.post(
        "/api/v1/runners/heartbeat",
        headers={"X-API-Token": token},
        json={
            "runner_id": runner_id,
            "inventory": [{"udid": udid, "platform": "android", "state": "ready"}], "devices": [{"udid": udid, "platform": "android", "state": "ready"}],
        },
    ).status_code == 200
    return runner_id, token


def test_private_and_shared_visibility_use_and_management(client: TestClient):
    admin, alice, bob = setup_users_and_project(client)
    register_ide(client, alice, "ide-alice", "private-1", token_issuer=admin)
    register_shared(client, admin, "platform-1", "shared-1")
    assert client.post(
        "/api/v1/auth/users",
        headers=admin,
        json={"username": "outsider", "password": "Outside123", "duty": "user"},
    ).status_code == 200
    outsider = login(client, "outsider", "Outside123")

    alice_devices = page_items(client.get("/api/v1/devices", headers=alice).json())
    bob_devices = page_items(client.get("/api/v1/devices", headers=bob).json())
    admin_devices = page_items(client.get("/api/v1/devices", headers=admin).json())
    assert {d["udid"] for d in alice_devices} == {"private-1", "shared-1"}
    assert {d["udid"] for d in bob_devices} == {"shared-1"}
    assert {d["udid"] for d in admin_devices} == {"private-1", "shared-1"}
    private = next(d for d in alice_devices if d["udid"] == "private-1")
    shared = next(d for d in alice_devices if d["udid"] == "shared-1")
    assert private["registration_source"] == "ide"
    assert private["owner_username"] == "alice"
    assert private["can_manage"] is False
    assert next(d for d in admin_devices if d["udid"] == "private-1")["can_manage"] is True

    denied = client.post(
        "/api/v1/jobs",
        headers=bob,
        json={
            "name": "steal private",
            "project_dir": "/tmp/p",
            "project_id": "project-1",
            "platform": "android",
            "device_udids": ["private-1"],
        },
    )
    assert denied.status_code == 403
    assert client.post(
        "/api/v1/devices/shared-1/maintenance",
        headers=bob,
        json={"disabled": True},
    ).status_code == 403
    assert client.post(
        "/api/v1/devices/private-1/maintenance",
        headers=alice,
        json={"disabled": True},
    ).status_code == 403
    assert client.post(
        "/api/v1/devices/private-1/maintenance",
        headers=admin,
        json={"disabled": True},
    ).status_code == 200
    assert client.post(
        f"/api/v1/devices/{shared['id']}/reservations",
        headers=outsider,
        json={"duration_minutes": 30},
    ).status_code == 403


def test_reserve_stop_expire_and_claim_conflict(client: TestClient):
    admin, alice, bob = setup_users_and_project(client)
    runner_id, runner_token = register_shared(
        client, admin, "platform-r", "shared-r"
    )
    device = next(
        d for d in page_items(client.get("/api/v1/devices", headers=bob).json())
        if d["udid"] == "shared-r"
    )
    reserved = client.post(
        f"/api/v1/devices/{device['id']}/reservations",
        headers=bob,
        json={"duration_minutes": 60, "reason": "manual test"},
    )
    assert reserved.status_code == 201, reserved.text
    reservation_id = reserved.json()["id"]

    job = client.post(
        "/api/v1/jobs",
        headers=alice,
        json={
            "name": "blocked",
            "project_dir": "/tmp/p",
            "project_id": "project-1",
            "platform": "android",
            "device_udids": ["shared-r"],
            "preferred_runner_id": runner_id,
        },
    )
    assert job.status_code == 200, job.text
    claim = client.post(
        f"/api/v1/jobs/claim?runner_id={runner_id}",
        headers={"X-API-Token": runner_token},
    )
    assert claim.status_code == 200
    assert claim.json() is None

    assert client.delete(
        f"/api/v1/device-reservations/{reservation_id}",
        headers=alice,
    ).status_code == 403
    assert client.delete(
        f"/api/v1/device-reservations/{reservation_id}",
        headers=bob,
    ).status_code == 200

    reserved2 = client.post(
        f"/api/v1/devices/{device['id']}/reservations",
        headers=bob,
        json={"duration_minutes": 1},
    )
    assert reserved2.status_code == 201
    import autopilot_platform.platform.core.db as db_module

    _sf = db_module.session_factory()
    assert _sf is not None
    session = _sf()
    try:
        row = session.get(DeviceReservationRow, reserved2.json()["id"])
        assert row is not None
        row.expires_at = utcnow() - timedelta(seconds=1)
        session.commit()
    finally:
        session.close()
    board = client.get("/api/v1/devices/board", headers=bob)
    assert board.status_code == 200
    shared = next(d for d in board.json()["devices"] if d["udid"] == "shared-r")
    assert shared["reservation_id"] is None


def test_pool_mode_intersects_private_ownership(client: TestClient):
    admin, alice, bob = setup_users_and_project(client)
    register_ide(client, alice, "ide-pool", "private-pool", token_issuer=admin)
    private = next(
        d for d in page_items(client.get("/api/v1/devices", headers=alice).json())
        if d["udid"] == "private-pool"
    )
    pool = client.post(
        "/api/v1/orgs/org-1/resource-pools",
        headers=admin,
        json={"name": "pool"},
    ).json()
    assert client.post(
        f"/api/v1/resource-pools/{pool['id']}/projects",
        headers=admin,
        json={"project_id": "project-1"},
    ).status_code == 200
    # 池模式已激活但成员为空，owner 也不能绕过池授权。
    assert page_items(
        client.get("/api/v1/devices?project_id=project-1", headers=alice).json()
    ) == []
    assert client.post(
        f"/api/v1/resource-pools/{pool['id']}/devices",
        headers=admin,
        json={"resource_id": private["id"]},
    ).status_code == 200
    visible = page_items(
        client.get("/api/v1/devices?project_id=project-1", headers=alice).json()
    )
    assert [d["udid"] for d in visible] == ["private-pool"]
    assert page_items(
        client.get("/api/v1/devices?project_id=project-1", headers=bob).json()
    ) == []


@pytest.mark.parametrize("duration", [0, -1, 1441])
def test_reservation_duration_boundaries_are_rejected(client: TestClient, duration: int):
    admin, _alice, bob = setup_users_and_project(client)
    register_shared(client, admin, f"duration-{duration}", f"duration-{duration}")
    device = next(
        d
        for d in page_items(client.get("/api/v1/devices", headers=bob).json())
        if d["udid"] == f"duration-{duration}"
    )
    out = client.post(
        f"/api/v1/devices/{device['id']}/reservations",
        headers=bob,
        json={"duration_minutes": duration},
    )
    assert out.status_code == 422


def test_concurrent_reserve_has_single_winner_and_audits_org(client: TestClient):
    admin, alice, bob = setup_users_and_project(client)
    register_shared(client, admin, "reserve-race", "reserve-race")
    device = next(
        d
        for d in page_items(client.get("/api/v1/devices", headers=bob).json())
        if d["udid"] == "reserve-race"
    )
    gate = Barrier(2)

    def reserve(headers: dict):
        gate.wait()
        return client.post(
            f"/api/v1/devices/{device['id']}/reservations",
            headers=headers,
            json={"duration_minutes": 30},
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(reserve, (alice, bob)))
    assert sorted(r.status_code for r in results) == [201, 409]

    import autopilot_platform.platform.core.db as db_module

    _sf = db_module.session_factory()
    assert _sf is not None
    session = _sf()
    try:
        active = list(
            session.query(DeviceReservationRow).filter_by(
                device_id=device["id"], status="active"
            )
        )
        row = session.get(DeviceRow, device["id"])
        assert len(active) == 1
        assert row is not None and row.reservation_id == active[0].id
    finally:
        session.close()

    audits = client.get("/api/v1/audit?action=device.reserve", headers=admin)
    assert audits.status_code == 200
    hit = next(a for a in page_items(audits.json()) if a["resource_id"] == device["id"])
    assert hit["actor"] in {"alice", "bob"}
    assert hit["org_id"] == "org-1"


def test_reserve_and_claim_race_never_double_allocates(client: TestClient):
    admin, alice, bob = setup_users_and_project(client)
    runner_id, token = register_shared(client, admin, "claim-race", "claim-race")
    device = next(
        d
        for d in page_items(client.get("/api/v1/devices", headers=bob).json())
        if d["udid"] == "claim-race"
    )
    job = client.post(
        "/api/v1/jobs",
        headers=alice,
        json={
            "name": "claim race",
            "project_dir": "/tmp/p",
            "project_id": "project-1",
            "platform": "android",
            "device_udids": ["claim-race"],
            "preferred_runner_id": runner_id,
        },
    )
    assert job.status_code == 200
    gate = Barrier(2)

    def reserve():
        gate.wait()
        return client.post(
            f"/api/v1/devices/{device['id']}/reservations",
            headers=bob,
            json={"duration_minutes": 30},
        )

    def claim():
        gate.wait()
        return client.post(
            f"/api/v1/jobs/claim?runner_id={runner_id}",
            headers={"X-API-Token": token},
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        reserve_future = pool.submit(reserve)
        claim_future = pool.submit(claim)
        reserve_response = reserve_future.result()
        claim_response = claim_future.result()

    claimed = claim_response.status_code == 200 and claim_response.json() is not None
    reserved = reserve_response.status_code == 201
    assert claimed != reserved
    assert reserve_response.status_code in {201, 409}


def test_owner_reservation_survives_job_complete(client: TestClient):
    admin, _alice, bob = setup_users_and_project(client)
    runner_id, token = register_shared(client, admin, "owner-job", "owner-job")
    device = next(
        d
        for d in page_items(client.get("/api/v1/devices", headers=bob).json())
        if d["udid"] == "owner-job"
    )
    reserved = client.post(
        f"/api/v1/devices/{device['id']}/reservations",
        headers=bob,
        json={"duration_minutes": 30},
    )
    assert reserved.status_code == 201
    job = client.post(
        "/api/v1/jobs",
        headers=bob,
        json={
            "name": "reservation owner",
            "project_dir": "/tmp/p",
            "project_id": "project-1",
            "platform": "android",
            "device_udids": ["owner-job"],
            "preferred_runner_id": runner_id,
        },
    ).json()
    claimed = client.post(
        f"/api/v1/jobs/claim?runner_id={runner_id}",
        headers={"X-API-Token": token},
    ).json()
    assert claimed["id"] == job["id"]
    assert client.post(
        f"/api/v1/jobs/{job['id']}/complete?runner_id={runner_id}",
        headers={"X-API-Token": token},
        json={"status": "succeeded"},
    ).status_code == 200
    board = client.get("/api/v1/devices/board", headers=bob).json()
    item = next(d for d in board["devices"] if d["id"] == device["id"])
    assert item["busy_kind"] == "reservation"
    assert item["reservation_id"] == reserved.json()["id"]
    assert str(item.get("occupy_summary") or "").startswith("人工预占")


def test_user_cannot_scope_shared_runner_or_spoof_owner(client: TestClient):
    admin, alice, _bob = setup_users_and_project(client)
    register_shared(client, admin, "shared-scope", "shared-scope")
    denied = client.post(
        "/api/v1/runners/shared-scope/scoped-token",
        headers=alice,
        json={"org_id": "org-1", "project_ids": ["project-1"]},
    )
    assert denied.status_code == 403

    created = client.post(
        "/api/v1/runners/register",
        headers=alice,
        json={
            "runner_id": "owner-trusted",
            "registration_source": "ide",
            "owner_user_id": "forged-user-id",
        },
    )
    assert created.status_code == 200
    assert created.json()["registration_source"] == "ide"
    assert created.json()["owner_user_id"]
    assert created.json()["owner_user_id"] != "forged-user-id"


def test_expiry_is_cleaned_by_heartbeat_and_claim(client: TestClient):
    admin, alice, bob = setup_users_and_project(client)
    runner_id, token = register_shared(client, admin, "expiry-paths", "expiry-paths")
    device = next(
        d
        for d in page_items(client.get("/api/v1/devices", headers=bob).json())
        if d["udid"] == "expiry-paths"
    )
    reserved = client.post(
        f"/api/v1/devices/{device['id']}/reservations",
        headers=bob,
        json={"duration_minutes": 1},
    ).json()
    import autopilot_platform.platform.core.db as db_module

    _sf = db_module.session_factory()
    assert _sf is not None
    session = _sf()
    try:
        row = session.get(DeviceReservationRow, reserved["id"])
        assert row is not None
        row.expires_at = utcnow()
        session.commit()
    finally:
        session.close()
    heartbeat = client.post(
        "/api/v1/runners/heartbeat",
        headers={"X-API-Token": token},
        json={
            "runner_id": runner_id,
            "inventory": [{"udid": "expiry-paths", "platform": "android", "state": "ready"}], "devices": [{"udid": "expiry-paths", "platform": "android", "state": "ready"}],
        },
    )
    assert heartbeat.status_code == 200

    job = client.post(
        "/api/v1/jobs",
        headers=alice,
        json={
            "name": "after expiry",
            "project_dir": "/tmp/p",
            "project_id": "project-1",
            "platform": "android",
            "device_udids": ["expiry-paths"],
            "preferred_runner_id": runner_id,
        },
    ).json()
    claimed = client.post(
        f"/api/v1/jobs/claim?runner_id={runner_id}",
        headers={"X-API-Token": token},
    )
    assert claimed.status_code == 200
    assert claimed.json()["id"] == job["id"]

    _sf = db_module.session_factory()
    assert _sf is not None
    session = _sf()
    try:
        expired = session.get(DeviceReservationRow, reserved["id"])
        locked = session.get(DeviceRow, device["id"])
        assert expired is not None and expired.status == "expired"
        assert locked is not None and locked.reservation_id is None
        assert locked.busy_job_id == job["id"]
    finally:
        session.close()


def test_migration_reconciles_duplicate_active_reservations(tmp_path):
    from sqlalchemy import create_engine, text

    from autopilot_platform.platform.core.db import migrate_schema

    engine = create_engine(f"sqlite:///{(tmp_path / 'legacy.sqlite').as_posix()}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE devices (id VARCHAR(64) PRIMARY KEY)"))
        conn.execute(
            text(
                "CREATE TABLE device_reservations ("
                "id VARCHAR(64) PRIMARY KEY, device_id VARCHAR(64), status VARCHAR(32), "
                "start_at DATETIME, expires_at DATETIME, released_at DATETIME)"
            )
        )
        conn.execute(text("INSERT INTO devices (id) VALUES ('d1')"))
        conn.execute(
            text(
                "INSERT INTO device_reservations "
                "(id, device_id, status, start_at, expires_at) VALUES "
                "('old', 'd1', 'active', '2026-01-01', '2027-01-01'), "
                "('new', 'd1', 'active', '2026-02-01', '2027-02-01')"
            )
        )
    migrate_schema(engine)
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT id, status FROM device_reservations "
                "WHERE device_id = 'd1' ORDER BY id"
            )
        ).all()
        lock = conn.execute(
            text("SELECT reservation_id FROM devices WHERE id = 'd1'")
        ).scalar_one()
    assert rows == [("new", "active"), ("old", "expired")]
    assert lock == "new"
