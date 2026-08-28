"""设备注册全流程白盒：名单语义、混合平台入池、库存自愈、组织可见性。"""
from __future__ import annotations

import os
import sys
from datetime import timedelta
from types import SimpleNamespace
from typing import cast

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient

from list_page_helpers import page_items
from autopilot_platform.core.schemas import DeviceInfo
from autopilot_platform.platform.app import create_app
from autopilot_platform.platform.core.db import reset_engine, session_factory
from autopilot_platform.platform.core.models import DeviceRow, RunnerRow, db_get, new_id, utcnow
from autopilot_platform.platform.core.settings import managed_runner_id
from autopilot_platform.platform.services.execution.runners import registry as runner_registry

_inventory_registered = getattr(runner_registry, "_inventory_registered")


RUNNER_HEADERS = {"X-API-Token": "runner-global-token"}

ANDROID = "abcd1234"
IOS_15 = "00008130-0010000000000002"
IOS_16 = "00008140-0010000000000001"


def _mixed_devices() -> list[DeviceInfo]:
    return [
        DeviceInfo(
            udid=ANDROID,
            platform="android",
            name="POCO F8 Pro",
            model="2510DPC44G",
            os_version="16",
            backends=["android-appium"],
        ),
        DeviceInfo(
            udid=IOS_15,
            platform="ios",
            name="iPhone",
            model="iPhone 15 Pro Max",
            os_version="18.6.2",
            backends=["ios-wda"],
        ),
        DeviceInfo(
            udid=IOS_16,
            platform="ios",
            name="iPhone",
            model="iPhone 16e",
            os_version="26.6",
            backends=["ios-wda"],
        ),
    ]


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MC_API_TOKEN", "runner-global-token")
    monkeypatch.setenv("MC_ADMIN_USER", "admin")
    monkeypatch.setenv("MC_ADMIN_PASSWORD", "admin")
    monkeypatch.setenv("MC_SCHEDULE_ENABLED", "0")
    monkeypatch.setenv("MC_ALLOW_MANAGED_RUNNER", "1")
    monkeypatch.setenv("MC_HOST", "127.0.0.1")
    monkeypatch.setenv("MC_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MC_RUNTIME_CONFIG", str(tmp_path / "runtime.json"))
    monkeypatch.setattr(
        "autopilot_platform.runner.devices.list_local_devices",
        _mixed_devices,
    )
    reset_engine()
    app = create_app(database_url=f"sqlite:///{(tmp_path / 'register-flow.db').as_posix()}")
    with TestClient(app) as c:
        yield c
    reset_engine()


def _admin(client: TestClient) -> dict:
    out = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "admin"}
    )
    assert out.status_code == 200, out.text
    return {"Authorization": f"Bearer {out.json()['access_token']}"}


def _login(client: TestClient, username: str, password: str) -> dict:
    out = client.post(
        "/api/v1/auth/login", json={"username": username, "password": password}
    )
    assert out.status_code == 200, out.text
    return {"Authorization": f"Bearer {out.json()['access_token']}"}


def _device_udids(client: TestClient, headers: dict) -> set[str]:
    return {
        str(d.get("udid") or "")
        for d in page_items(client.get("/api/v1/devices", headers=headers).json())
    }


def _probe(client: TestClient, headers: dict) -> str:
    probe = client.post("/api/v1/runners/managed/device-probe", headers=headers)
    assert probe.status_code == 200, probe.text
    body = probe.json()
    assert {d["udid"] for d in body["devices"]} == {ANDROID, IOS_15, IOS_16}
    return body["runner_id"]


def _heartbeat(client: TestClient, rid: str) -> None:
    hb = client.post(
        "/api/v1/runners/heartbeat",
        headers=RUNNER_HEADERS,
        json={
            "runner_id": rid,
            "inventory": [
                {
                    "udid": d.udid,
                    "platform": d.platform,
                    "name": d.name,
                    "model": d.model,
                    "state": "ready",
                    "backends": list(d.backends),
                }
                for d in _mixed_devices()
            ],
            "devices": [
                {
                    "udid": d.udid,
                    "platform": d.platform,
                    "name": d.name,
                    "state": "ready",
                    "backends": list(d.backends),
                }
                for d in _mixed_devices()
            ],
        },
    )
    assert hb.status_code == 200, hb.text


def _register(client: TestClient, headers: dict, rid: str, udids: list[str]):
    out = client.patch(
        f"/api/v1/runners/{rid}/device-selection",
        headers=headers,
        json={"action": "register", "udids": udids},
    )
    assert out.status_code == 200, out.text
    return out.json()


def _inventory(client: TestClient, headers: dict, rid: str) -> dict:
    out = client.get(f"/api/v1/runners/{rid}/device-inventory", headers=headers)
    assert out.status_code == 200, out.text
    return out.json()


def _device_row_udids() -> set[str]:
    sf = session_factory()
    assert sf is not None
    with sf() as db:
        return {str(d.udid) for d in db.query(DeviceRow).all()}


def test_inventory_registered_include_follows_allowlist_not_device_row():
    row = cast(
        RunnerRow,
        SimpleNamespace(
            device_selection_mode="include",
            selected_device_udids=[ANDROID, IOS_15],
        ),
    )
    assert _inventory_registered(row, ANDROID, None) is True
    assert _inventory_registered(row, IOS_16, cast(DeviceRow, object())) is False


def test_inventory_registered_all_mode_follows_device_row():
    row = cast(
        RunnerRow,
        SimpleNamespace(device_selection_mode="all", selected_device_udids=[]),
    )
    assert _inventory_registered(row, ANDROID, None) is False
    assert _inventory_registered(row, ANDROID, cast(DeviceRow, object())) is True


def test_probe_does_not_enter_device_pool(client: TestClient):
    ah = _admin(client)
    rid = _probe(client, ah)
    assert rid == managed_runner_id()
    assert _device_row_udids() == set()
    assert _device_udids(client, ah) == set()
    sf = session_factory()
    assert sf is not None
    with sf() as db:
        row = db_get(db, RunnerRow, rid)
        assert row is not None
        assert row.last_heartbeat_at is None


def test_register_mixed_android_ios_enters_pool_immediately(client: TestClient):
    ah = _admin(client)
    rid = _probe(client, ah)
    body = _register(client, ah, rid, [ANDROID, IOS_15, IOS_16])
    _heartbeat(client, rid)
    assert set(body["registered"]) == {ANDROID, IOS_15, IOS_16}
    assert body["rejected"] == {}
    assert set(body["selected_udids"]) == {ANDROID, IOS_15, IOS_16}

    inventory = _inventory(client, ah, rid)
    by_udid = {d["udid"]: d for d in inventory["devices"]}
    assert all(by_udid[uid]["registered"] is True for uid in (ANDROID, IOS_15, IOS_16))
    assert {d["platform"] for d in inventory["devices"]} == {"android", "ios"}

    online = _device_udids(client, ah)
    assert online == {ANDROID, IOS_15, IOS_16}
    assert _device_row_udids() == {ANDROID, IOS_15, IOS_16}


def test_duplicate_register_is_noop(client: TestClient):
    ah = _admin(client)
    rid = _probe(client, ah)
    first = _register(client, ah, rid, [ANDROID, IOS_15, IOS_16])
    again = _register(client, ah, rid, [ANDROID, IOS_15, IOS_16])
    assert again["registered"] == []
    assert again["rejected"] == {}
    assert again["selected_udids"] == first["selected_udids"]
    assert again["policy_revision"] == first["policy_revision"]
    assert _device_row_udids() == {ANDROID, IOS_15, IOS_16}


def test_heartbeat_does_not_pull_unselected_candidate(client: TestClient):
    ah = _admin(client)
    rid = _probe(client, ah)
    _register(client, ah, rid, [ANDROID])
    hb = client.post(
        "/api/v1/runners/heartbeat",
        headers=RUNNER_HEADERS,
        json={
            "runner_id": rid,
            "inventory": [
                {
                    "udid": d.udid,
                    "platform": d.platform,
                    "name": d.name,
                    "model": d.model,
                    "state": "ready",
                    "backends": list(d.backends),
                }
                for d in _mixed_devices()
            ],
            "devices": [
                {
                    "udid": d.udid,
                    "platform": d.platform,
                    "name": d.name,
                    "state": "ready",
                    "backends": list(d.backends),
                }
                for d in _mixed_devices()
            ],
        },
    )
    assert hb.status_code == 200, hb.text
    assert hb.json()["selected_device_udids"] == [ANDROID]
    assert _device_udids(client, ah) == {ANDROID}
    inventory = _inventory(client, ah, rid)
    by_udid = {d["udid"]: d for d in inventory["devices"]}
    assert by_udid[ANDROID]["registered"] is True
    assert by_udid[IOS_15]["registered"] is False
    assert by_udid[IOS_16]["registered"] is False


def test_inventory_repairs_allowlist_without_missing_ios_rows(client: TestClient):
    """复现：名单已有 3 台，心跳停了，池里只剩一台安卓。GET 库存应补齐。"""
    ah = _admin(client)
    rid = _probe(client, ah)
    sf = session_factory()
    assert sf is not None
    stale = utcnow() - timedelta(hours=8)
    with sf() as db:
        row = db_get(db, RunnerRow, rid)
        assert row is not None
        row.device_selection_mode = "include"
        row.selected_device_udids = [ANDROID, IOS_15, IOS_16]
        row.device_policy_revision = 1
        row.last_heartbeat_at = stale
        db.add(
            DeviceRow(
                id=new_id(),
                runner_id=rid,
                udid=ANDROID,
                platform="android",
                name="POCO F8 Pro",
                model="2510DPC44G",
                state="ready",
                updated_at=stale,
            )
        )
        db.commit()
    assert _device_row_udids() == {ANDROID}
    # 节点离线：在线看板为空；inventory GET 只补 DeviceRow，不入看板
    assert _device_udids(client, ah) == set()

    inventory = _inventory(client, ah, rid)
    by_udid = {d["udid"]: d for d in inventory["devices"]}
    assert all(by_udid[uid]["registered"] is True for uid in (ANDROID, IOS_15, IOS_16))
    assert _device_row_udids() == {ANDROID, IOS_15, IOS_16}
    assert _device_udids(client, ah) == set()

    _probe(client, ah)
    _heartbeat(client, rid)
    assert _device_udids(client, ah) == {ANDROID, IOS_15, IOS_16}

    again = _inventory(client, ah, rid)
    assert {d["udid"] for d in again["devices"] if d["registered"]} == {
        ANDROID,
        IOS_15,
        IOS_16,
    }
    assert _device_row_udids() == {ANDROID, IOS_15, IOS_16}


def test_stale_heartbeat_register_still_lists_all_platforms(client: TestClient):
    ah = _admin(client)
    rid = _probe(client, ah)
    sf = session_factory()
    assert sf is not None
    with sf() as db:
        row = db_get(db, RunnerRow, rid)
        assert row is not None
        row.last_heartbeat_at = utcnow() - timedelta(hours=8)
        db.commit()
    assert _device_udids(client, ah) == set()
    _register(client, ah, rid, [ANDROID, IOS_15, IOS_16])
    assert _device_udids(client, ah) == set()
    _probe(client, ah)
    _heartbeat(client, rid)
    assert _device_udids(client, ah) == {ANDROID, IOS_15, IOS_16}


def test_empty_org_devices_visible_to_admin_hidden_from_org_member(client: TestClient):
    ah = _admin(client)
    assert (
        client.post(
            "/api/v1/orgs", headers=ah, json={"id": "org-lab", "name": "Lab"}
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/v1/auth/users",
            headers=ah,
            json={"username": "lab-member", "password": "Owner1234", "duty": "user"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/v1/orgs/org-lab/members",
            headers=ah,
            json={"username": "lab-member", "role": "member"},
        ).status_code
        == 200
    )
    rid = _probe(client, ah)
    _register(client, ah, rid, [ANDROID, IOS_15, IOS_16])
    _heartbeat(client, rid)
    assert _device_udids(client, ah) == {ANDROID, IOS_15, IOS_16}
    member = {**_login(client, "lab-member", "Owner1234"), "X-Org-Id": "org-lab"}
    assert _device_udids(client, member) == set()


def test_scope_then_register_makes_devices_visible_to_org_member(client: TestClient):
    ah = _admin(client)
    assert (
        client.post(
            "/api/v1/orgs", headers=ah, json={"id": "org-lab", "name": "Lab"}
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/v1/auth/users",
            headers=ah,
            json={"username": "lab-member", "password": "Owner1234", "duty": "user"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/v1/orgs/org-lab/members",
            headers=ah,
            json={"username": "lab-member", "role": "member"},
        ).status_code
        == 200
    )
    rid = _probe(client, ah)
    scoped = client.patch(
        f"/api/v1/runners/{rid}/scope",
        headers=ah,
        json={"org_id": "org-lab"},
    )
    assert scoped.status_code == 200, scoped.text
    _register(client, ah, rid, [ANDROID, IOS_15, IOS_16])
    _heartbeat(client, rid)
    inventory = _inventory(client, ah, rid)
    assert inventory["org_id"] == "org-lab"
    member = {**_login(client, "lab-member", "Owner1234"), "X-Org-Id": "org-lab"}
    assert _device_udids(client, member) == {ANDROID, IOS_15, IOS_16}


def test_heartbeat_keeps_allowlisted_devices_when_runner_reports_empty(client: TestClient):
    """Web 注册后 Runner 本地策略未同步、上报空 devices 时，不得 prune 掉已登记设备。"""
    ah = _admin(client)
    rid = _probe(client, ah)
    _register(client, ah, rid, [ANDROID, IOS_15, IOS_16])
    _heartbeat(client, rid)
    assert _device_udids(client, ah) == {ANDROID, IOS_15, IOS_16}

    hb = client.post(
        "/api/v1/runners/heartbeat",
        headers=RUNNER_HEADERS,
        json={
            "runner_id": rid,
            "inventory": [
                {
                    "udid": ANDROID,
                    "platform": "android",
                    "name": "POCO F8 Pro",
                    "state": "ready",
                    "backends": ["android-appium"],
                },
                {
                    "udid": IOS_15,
                    "platform": "ios",
                    "name": "iPhone",
                    "state": "ready",
                    "backends": ["ios-wda"],
                },
                {
                    "udid": IOS_16,
                    "platform": "ios",
                    "name": "iPhone",
                    "state": "ready",
                    "backends": ["ios-wda"],
                },
            ],
            "devices": [],
        },
    )
    assert hb.status_code == 200, hb.text
    assert set(hb.json().get("selected_device_udids") or []) == {ANDROID, IOS_15, IOS_16}
    assert _device_udids(client, ah) == {ANDROID, IOS_15, IOS_16}


def test_fleet_startup_reset_clears_heartbeat_and_device_board(client: TestClient):
    """控制面 reset 后节点离线，在线看板为空直至再次 heartbeat。"""
    from autopilot_platform.platform.services.execution.fleet_startup import (
        reset_fleet_liveness_on_startup,
    )

    ah = _admin(client)
    rid = _probe(client, ah)
    _register(client, ah, rid, [ANDROID])
    _heartbeat(client, rid)
    assert _device_udids(client, ah) == {ANDROID}
    sf = session_factory()
    assert sf is not None
    with sf() as db:
        row = db_get(db, RunnerRow, rid)
        assert row is not None
        assert row.last_heartbeat_at is not None
        reset_fleet_liveness_on_startup(db)
        row = db_get(db, RunnerRow, rid)
        assert row is not None
        assert row.last_heartbeat_at is None
    assert _device_udids(client, ah) == set()
    inventory = _inventory(client, ah, rid)
    assert any(d["udid"] == ANDROID and d.get("registered") for d in inventory["devices"])


def test_registered_devices_hidden_from_pool_when_runner_offline(client: TestClient):
    """节点离线时在线设备看板为空；注册名单仍在 inventory API。"""
    ah = _admin(client)
    rid = _probe(client, ah)
    _register(client, ah, rid, [ANDROID, IOS_15, IOS_16])
    sf = session_factory()
    assert sf is not None
    stale = utcnow() - timedelta(hours=8)
    with sf() as db:
        row = db_get(db, RunnerRow, rid)
        assert row is not None
        row.last_heartbeat_at = stale
        db.commit()
    listed = client.get("/api/v1/devices", headers=ah)
    assert listed.status_code == 200, listed.text
    assert page_items(listed.json()) == []
    inventory = _inventory(client, ah, rid)
    registered = [d["udid"] for d in inventory["devices"] if d.get("registered")]
    assert set(registered) == {ANDROID, IOS_15, IOS_16}


def test_unregister_only_drops_allowlisted_and_keeps_candidates(client: TestClient):
    ah = _admin(client)
    rid = _probe(client, ah)
    _register(client, ah, rid, [ANDROID, IOS_15, IOS_16])
    _heartbeat(client, rid)
    out = client.patch(
        f"/api/v1/runners/{rid}/device-selection",
        headers=ah,
        json={"action": "unregister", "udids": [IOS_15, IOS_16]},
    )
    assert out.status_code == 200, out.text
    assert set(out.json()["unregistered"]) == {IOS_15, IOS_16}
    assert out.json()["selected_udids"] == [ANDROID]
    inventory = _inventory(client, ah, rid)
    by_udid = {d["udid"]: d for d in inventory["devices"]}
    assert by_udid[ANDROID]["registered"] is True
    assert by_udid[IOS_15]["registered"] is False
    assert by_udid[IOS_16]["registered"] is False
    _heartbeat(client, rid)
    assert _device_udids(client, ah) == {ANDROID}
