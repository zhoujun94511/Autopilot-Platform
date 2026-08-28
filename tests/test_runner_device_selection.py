"""Runner inventory / allowlist 白盒链。"""
from __future__ import annotations

import os
import sys
from datetime import timedelta
from typing import cast

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient

from list_page_helpers import page_items
from autopilot_platform.platform.app import create_app
from autopilot_platform.platform.core.db import reset_engine, session_factory
from autopilot_platform.platform.core.models import (
    DeviceReservationRow,
    DeviceRow,
    JobRow,
    utcnow,
)
from autopilot_platform.platform.core.settings import managed_runner_id
from autopilot_platform.runner.agent import RunnerAgent
from autopilot_platform.runner.client import PlatformClient
from autopilot_platform.runner.device_policy import DevicePolicy, update_device_policy
from autopilot_platform.core.schemas import DeviceInfo


RUNNER_HEADERS = {"X-API-Token": "runner-global-token"}


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
    reset_engine()
    app = create_app(database_url=f"sqlite:///{(tmp_path / 'selection.db').as_posix()}")
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


def _device(udid: str) -> dict:
    return {
        "udid": udid,
        "platform": "android",
        "name": udid,
        "state": "ready",
        "backends": ["android-appium"],
    }


def _seed_runner(client: TestClient, runner_id: str = "select-r1") -> None:
    assert (
        client.post(
            "/api/v1/runners/register",
            headers=RUNNER_HEADERS,
            json={"runner_id": runner_id, "hostname": "host"},
        ).status_code
        == 200
    )
    payload = {
        "runner_id": runner_id,
        "inventory": [_device("A"), _device("B")],
        "devices": [_device("A"), _device("B")],
    }
    assert client.post(
        "/api/v1/runners/heartbeat", headers=RUNNER_HEADERS, json=payload
    ).status_code == 200


def test_default_all_and_explicit_unregistration_survives_heartbeat(client: TestClient):
    _seed_runner(client)
    ah = _admin(client)
    inventory = client.get(
        "/api/v1/runners/select-r1/device-inventory", headers=ah
    )
    assert inventory.status_code == 200, inventory.text
    assert inventory.json().get("org_id", "") == ""
    assert {x["udid"] for x in inventory.json()["devices"]} == {"A", "B"}
    assert all(x["registered"] for x in inventory.json()["devices"])

    changed = client.patch(
        "/api/v1/runners/select-r1/device-selection",
        headers=ah,
        json={"action": "unregister", "udids": ["B"]},
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["selected_udids"] == ["A"]
    assert changed.json()["unregistered"] == ["B"]

    # 模拟客户端异常全量上报；服务端策略必须阻止 B 被重建。
    hb = client.post(
        "/api/v1/runners/heartbeat",
        headers=RUNNER_HEADERS,
        json={
            "runner_id": "select-r1",
            "inventory": [_device("A"), _device("B")],
            "devices": [_device("A"), _device("B")],
        },
    )
    assert hb.status_code == 200, hb.text
    assert hb.json()["device_selection_mode"] == "include"
    assert hb.json()["selected_device_udids"] == ["A"]
    sf = session_factory()
    assert sf is not None
    with sf() as db:
        assert {d.udid for d in db.query(DeviceRow).all()} == {"A"}


def test_busy_device_rejects_unregistration_without_partial_delete(client: TestClient):
    _seed_runner(client)
    sf = session_factory()
    assert sf is not None
    with sf() as db:
        row = db.query(DeviceRow).filter(DeviceRow.udid == "B").one()
        row.busy_job_id = "job-running"
        db.commit()
    out = client.patch(
        "/api/v1/runners/select-r1/device-selection",
        headers=_admin(client),
        json={"action": "unregister", "udids": ["A", "B"]},
    )
    assert out.status_code == 200, out.text
    body = out.json()
    assert body["unregistered"] == ["A"]
    assert "正在执行任务" in body["rejected"]["B"]
    assert body["selected_udids"] == ["B"]


def test_runner_inventory_is_not_exposed_to_other_runner_token(client: TestClient):
    _seed_runner(client)
    assert (
        client.post(
            "/api/v1/runners/register",
            headers=RUNNER_HEADERS,
            json={"runner_id": "other-r1"},
        ).status_code
        == 200
    )
    token = client.post(
        "/api/v1/runners/other-r1/token", headers=_admin(client), json={}
    )
    assert token.status_code == 200, token.text
    response = client.get(
        "/api/v1/runners/select-r1/device-inventory",
        headers={"X-API-Token": token.json()["api_token"]},
    )
    assert response.status_code == 403


def test_org_owner_can_manage_selection_but_member_cannot(client: TestClient):
    _seed_runner(client)
    ah = _admin(client)
    assert (
        client.post(
            "/api/v1/orgs",
            headers=ah,
            json={"id": "org-device-owner", "name": "Device Owner"},
        ).status_code
        == 200
    )
    assert (
        client.patch(
            "/api/v1/runners/select-r1/scope",
            headers=ah,
            json={"org_id": "org-device-owner"},
        ).status_code
        == 200
    )
    inventory = client.get(
        "/api/v1/runners/select-r1/device-inventory", headers=ah
    )
    assert inventory.status_code == 200, inventory.text
    assert inventory.json()["org_id"] == "org-device-owner"
    for username, role in (("device-owner", "owner"), ("device-member", "member")):
        assert (
            client.post(
                "/api/v1/auth/users",
                headers=ah,
                json={
                    "username": username,
                    "password": "Owner1234",
                    "duty": "user",
                },
            ).status_code
            == 200
        )
        assert (
            client.post(
                "/api/v1/orgs/org-device-owner/members",
                headers=ah,
                json={"username": username, "role": role},
            ).status_code
            == 200
        )
    owner = _login(client, "device-owner", "Owner1234")
    member = _login(client, "device-member", "Owner1234")
    assert (
        client.patch(
            "/api/v1/runners/select-r1/device-selection",
            headers=owner,
            json={"action": "unregister", "udids": ["B"]},
        ).status_code
        == 200
    )
    assert (
        client.patch(
            "/api/v1/runners/select-r1/device-selection",
            headers=member,
            json={"action": "register", "udids": ["B"]},
        ).status_code
        == 403
    )


def test_managed_probe_keeps_candidates_out_of_device_rows(
    client: TestClient, monkeypatch
):
    from autopilot_platform.core.schemas import DeviceInfo

    monkeypatch.setattr(
        "autopilot_platform.runner.devices.list_local_devices",
        lambda: [DeviceInfo(udid="LOCAL-1", platform="android", name="Pixel")],
    )
    out = client.post(
        "/api/v1/runners/managed/device-probe", headers=_admin(client)
    )
    assert out.status_code == 200, out.text
    assert out.json()["devices"][0]["registered"] is False
    sf = session_factory()
    assert sf is not None
    with sf() as db:
        assert db.query(DeviceRow).count() == 0


def test_remote_provision_returns_scoped_one_time_display_command(client: TestClient):
    ah = _admin(client)
    org = client.post(
        "/api/v1/orgs", headers=ah, json={"id": "org-lab", "name": "Lab"}
    )
    assert org.status_code == 200, org.text
    out = client.post(
        "/api/v1/runners/provision",
        headers=ah,
        json={"runner_id": "remote-lab-1", "org_id": "org-lab"},
    )
    assert out.status_code == 200, out.text
    body = out.json()
    assert body["org_id"] == "org-lab"
    assert body["api_token"] not in body["command"]
    assert "--token-env MC_RUNNER_TOKEN" in body["command"]
    assert "--runner-id remote-lab-1" in body["command"]


def test_platform_runner_filters_same_policy_and_reloads_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("MC_RUNNER_STATE_DIR", str(tmp_path))
    devices = [
        DeviceInfo(udid="A", platform="android"),
        DeviceInfo(udid="B", platform="android"),
    ]
    monkeypatch.setattr(
        "autopilot_platform.runner.agent.list_local_devices", lambda: list(devices)
    )
    monkeypatch.setattr(
        "autopilot_platform.runner.agent.probe_host_capabilities", lambda: ([], [])
    )

    class FakeClient:
        def __init__(self):
            self.bodies = []

        def heartbeat(self, body):
            self.bodies.append(body)
            return {
                "device_selection_mode": "include",
                "selected_device_udids": ["A"],
                "device_policy_revision": 3,
            }

    fake = FakeClient()
    agent = RunnerAgent("http://platform", runner_id="platform-policy-r1")
    platform_client = cast(PlatformClient, fake)
    agent._heartbeat_once(platform_client)
    agent._heartbeat_once(platform_client)
    assert [d.udid for d in fake.bodies[0].inventory] == ["A", "B"]
    assert [d.udid for d in fake.bodies[1].devices] == ["A"]
    assert RunnerAgent(
        "http://platform", runner_id="platform-policy-r1"
    )._device_policy.revision == 3


def _device_udids(client: TestClient, headers: dict) -> set[str]:
    return {
        str(d.get("udid") or "")
        for d in page_items(client.get("/api/v1/devices", headers=headers).json())
    }


def test_register_selected_then_heartbeat_creates_only_allowlisted_rows(
    client: TestClient, monkeypatch
):
    """扫描候选不进在线池；register 立刻写入 allowlist 对应 DeviceRow。"""
    monkeypatch.setattr(
        "autopilot_platform.runner.devices.list_local_devices",
        lambda: [
            DeviceInfo(udid="LOCAL-1", platform="android", name="One"),
            DeviceInfo(udid="LOCAL-2", platform="android", name="Two"),
        ],
    )
    ah = _admin(client)
    probe = client.post("/api/v1/runners/managed/device-probe", headers=ah)
    assert probe.status_code == 200, probe.text
    rid = probe.json()["runner_id"]
    assert rid == managed_runner_id()
    assert {d["udid"] for d in probe.json()["devices"]} == {"LOCAL-1", "LOCAL-2"}
    assert all(d["registered"] is False for d in probe.json()["devices"])
    assert "LOCAL-1" not in _device_udids(client, ah)
    assert "LOCAL-2" not in _device_udids(client, ah)

    registered = client.patch(
        f"/api/v1/runners/{rid}/device-selection",
        headers=ah,
        json={"action": "register", "udids": ["LOCAL-1"]},
    )
    assert registered.status_code == 200, registered.text
    body = registered.json()
    assert body["selection_mode"] == "include"
    assert body["selected_udids"] == ["LOCAL-1"]
    assert body["registered"] == ["LOCAL-1"]
    assert "LOCAL-1" in _device_udids(client, ah)
    assert "LOCAL-2" not in _device_udids(client, ah)
    inventory = client.get(f"/api/v1/runners/{rid}/device-inventory", headers=ah)
    by_udid = {d["udid"]: d for d in inventory.json()["devices"]}
    assert by_udid["LOCAL-1"]["registered"] is True
    assert by_udid["LOCAL-2"]["registered"] is False

    again = client.patch(
        f"/api/v1/runners/{rid}/device-selection",
        headers=ah,
        json={"action": "register", "udids": ["LOCAL-1"]},
    )
    assert again.status_code == 200, again.text
    assert again.json()["registered"] == []
    assert again.json()["selected_udids"] == ["LOCAL-1"]
    assert again.json()["policy_revision"] == body["policy_revision"]

    hb = client.post(
        "/api/v1/runners/heartbeat",
        headers=RUNNER_HEADERS,
        json={
            "runner_id": rid,
            "inventory": [_device("LOCAL-1"), _device("LOCAL-2")],
            "devices": [_device("LOCAL-1"), _device("LOCAL-2")],
        },
    )
    assert hb.status_code == 200, hb.text
    assert hb.json()["selected_device_udids"] == ["LOCAL-1"]
    online = _device_udids(client, ah)
    assert "LOCAL-1" in online
    assert "LOCAL-2" not in online
    inventory = client.get(f"/api/v1/runners/{rid}/device-inventory", headers=ah)
    by_udid = {d["udid"]: d for d in inventory.json()["devices"]}
    assert by_udid["LOCAL-1"]["registered"] is True
    assert by_udid["LOCAL-2"]["registered"] is False


def test_register_from_all_keeps_existing_tr_rows(client: TestClient):
    """已在线设备的 Runner 上增量 register，不得把已有 TR 行挤出 allowlist。"""
    _seed_runner(client)
    ah = _admin(client)
    out = client.patch(
        "/api/v1/runners/select-r1/device-selection",
        headers=ah,
        json={"action": "register", "udids": ["A"]},
    )
    assert out.status_code == 200, out.text
    assert set(out.json()["selected_udids"]) == {"A", "B"}
    assert set(_device_udids(client, ah)) == {"A", "B"}


def test_unknown_udid_is_rejected_and_not_registered(client: TestClient):
    _seed_runner(client)
    out = client.patch(
        "/api/v1/runners/select-r1/device-selection",
        headers=_admin(client),
        json={"action": "register", "udids": ["C"]},
    )
    assert out.status_code == 200, out.text
    body = out.json()
    assert "不在该 Runner 最近发现清单" in body["rejected"]["C"]
    assert body["registered"] == []
    assert set(body["selected_udids"]) == {"A", "B"}


def test_reserved_device_rejects_unregistration(client: TestClient):
    _seed_runner(client)
    sf = session_factory()
    assert sf is not None
    with sf() as db:
        row = db.query(DeviceRow).filter(DeviceRow.udid == "B").one()
        row.reservation_id = "rsv-hold"
        now = utcnow()
        db.add(
            DeviceReservationRow(
                id="rsv-hold",
                device_id=row.id,
                user_id="user-alice",
                username="alice",
                reason="联调占用",
                status="active",
                start_at=now,
                expires_at=now + timedelta(hours=2),
            )
        )
        db.commit()
    out = client.patch(
        "/api/v1/runners/select-r1/device-selection",
        headers=_admin(client),
        json={"action": "unregister", "udids": ["A", "B"]},
    )
    assert out.status_code == 200, out.text
    body = out.json()
    assert body["unregistered"] == ["A"]
    assert "有效预占" in body["rejected"]["B"]
    assert body["selected_udids"] == ["B"]
    inventory = client.get(
        "/api/v1/runners/select-r1/device-inventory", headers=_admin(client)
    )
    by_udid = {d["udid"]: d for d in inventory.json()["devices"]}
    assert by_udid["B"]["reserved"] is True
    assert by_udid["B"]["rejection_reason"]
    assert by_udid["B"]["occupancy_kind"] == "reservation"
    assert by_udid["B"]["occupancy_username"] == "alice"
    assert by_udid["B"]["occupancy_start_at"]
    assert by_udid["B"]["occupancy_end_at"]
    assert by_udid["B"]["occupancy_reference"] == "rsv-hold"
    assert by_udid["B"]["occupancy_reason"] == "联调占用"


def test_busy_job_inventory_exposes_owner_and_claim_time(client: TestClient):
    _seed_runner(client)
    sf = session_factory()
    assert sf is not None
    claimed_at = utcnow()
    with sf() as db:
        row = db.query(DeviceRow).filter(DeviceRow.udid == "A").one()
        db.add(
            JobRow(
                id="job-owned",
                name="冒烟回归",
                status="running",
                created_by="bob",
                claimed_at=claimed_at,
            )
        )
        row.busy_job_id = "job-owned"
        db.commit()
    inventory = client.get(
        "/api/v1/runners/select-r1/device-inventory", headers=_admin(client)
    )
    assert inventory.status_code == 200, inventory.text
    item = next(d for d in inventory.json()["devices"] if d["udid"] == "A")
    assert item["busy"] is True
    assert item["occupancy_kind"] == "job"
    assert item["occupancy_username"] == "bob"
    assert item["occupancy_start_at"]
    assert item["occupancy_end_at"] is None
    assert item["occupancy_reference"] == "job-owned"
    assert item["occupancy_reason"] == "冒烟回归"


def test_heartbeat_without_inventory_is_rejected(client: TestClient):
    assert (
        client.post(
            "/api/v1/runners/register",
            headers=RUNNER_HEADERS,
            json={"runner_id": "no-inventory-r1", "hostname": "host"},
        ).status_code
        == 200
    )
    hb = client.post(
        "/api/v1/runners/heartbeat",
        headers=RUNNER_HEADERS,
        json={"runner_id": "no-inventory-r1", "devices": [_device("A")]},
    )
    assert hb.status_code == 422, hb.text


def test_own_runner_token_can_read_inventory_but_cannot_change_selection(
    client: TestClient,
):
    _seed_runner(client)
    token = client.post(
        "/api/v1/runners/select-r1/token", headers=_admin(client), json={}
    )
    assert token.status_code == 200, token.text
    headers = {"X-API-Token": token.json()["api_token"]}
    inventory = client.get(
        "/api/v1/runners/select-r1/device-inventory", headers=headers
    )
    assert inventory.status_code == 200, inventory.text
    assert (
        client.patch(
            "/api/v1/runners/select-r1/device-selection",
            headers=headers,
            json={"action": "unregister", "udids": ["B"]},
        ).status_code
        == 403
    )


def test_org_owner_cannot_manage_other_org_runner(client: TestClient):
    _seed_runner(client)
    ah = _admin(client)
    for org_id, name in (("org-a", "A"), ("org-b", "B")):
        assert (
            client.post(
                "/api/v1/orgs", headers=ah, json={"id": org_id, "name": name}
            ).status_code
            == 200
        )
    assert (
        client.patch(
            "/api/v1/runners/select-r1/scope",
            headers=ah,
            json={"org_id": "org-a"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/v1/auth/users",
            headers=ah,
            json={"username": "owner-b", "password": "Owner1234", "duty": "user"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/v1/orgs/org-b/members",
            headers=ah,
            json={"username": "owner-b", "role": "owner"},
        ).status_code
        == 200
    )
    owner_b = _login(client, "owner-b", "Owner1234")
    assert (
        client.patch(
            "/api/v1/runners/select-r1/device-selection",
            headers=owner_b,
            json={"action": "unregister", "udids": ["B"]},
        ).status_code
        == 403
    )


def test_provision_allows_org_owner_and_rejects_member_and_cross_org_project(
    client: TestClient,
):
    ah = _admin(client)
    assert (
        client.post(
            "/api/v1/orgs", headers=ah, json={"id": "org-prov", "name": "Prov"}
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/v1/orgs", headers=ah, json={"id": "org-other", "name": "Other"}
        ).status_code
        == 200
    )
    project = client.post(
        "/api/v1/projects",
        headers={**ah, "X-Org-Id": "org-other"},
        json={"id": "proj-other", "name": "other", "org_id": "org-other"},
    )
    assert project.status_code == 200, project.text
    for username, role in (("prov-owner", "owner"), ("prov-member", "member")):
        assert (
            client.post(
                "/api/v1/auth/users",
                headers=ah,
                json={
                    "username": username,
                    "password": "Owner1234",
                    "duty": "user",
                },
            ).status_code
            == 200
        )
        assert (
            client.post(
                "/api/v1/orgs/org-prov/members",
                headers=ah,
                json={"username": username, "role": role},
            ).status_code
            == 200
        )
    owner = _login(client, "prov-owner", "Owner1234")
    member = _login(client, "prov-member", "Owner1234")
    assert (
        client.post(
            "/api/v1/runners/provision",
            headers=member,
            json={"runner_id": "prov-member-r1", "org_id": "org-prov"},
        ).status_code
        == 403
    )
    ok = client.post(
        "/api/v1/runners/provision",
        headers=owner,
        json={"runner_id": "prov-owner-r1", "org_id": "org-prov"},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["api_token"]
    cross = client.post(
        "/api/v1/runners/provision",
        headers=ah,
        json={
            "runner_id": "prov-cross-r1",
            "org_id": "org-prov",
            "project_ids": ["proj-other"],
        },
    )
    assert cross.status_code == 400, cross.text


def test_managed_probe_denied_when_flag_off_or_non_loopback(
    client: TestClient, monkeypatch
):
    ah = _admin(client)
    monkeypatch.setenv("MC_ALLOW_MANAGED_RUNNER", "0")
    denied = client.post("/api/v1/runners/managed/device-probe", headers=ah)
    assert denied.status_code == 403

    monkeypatch.setenv("MC_ALLOW_MANAGED_RUNNER", "1")
    monkeypatch.setenv("MC_HOST", "0.0.0.0")
    exposed = client.post("/api/v1/runners/managed/device-probe", headers=ah)
    assert exposed.status_code == 403


def test_invalid_selection_action_is_400(client: TestClient):
    _seed_runner(client)
    out = client.patch(
        "/api/v1/runners/select-r1/device-selection",
        headers=_admin(client),
        json={"action": "toggle", "udids": ["A"]},
    )
    assert out.status_code == 400


def test_platform_policy_revision_does_not_roll_back(tmp_path, monkeypatch):
    monkeypatch.setenv("MC_RUNNER_STATE_DIR", str(tmp_path))
    current = DevicePolicy(mode="include", selected_udids={"A"}, revision=5)
    kept = update_device_policy(
        "rev-r1",
        current,
        {
            "device_selection_mode": "all",
            "selected_device_udids": ["A", "B"],
            "device_policy_revision": 3,
        },
    )
    assert kept.revision == 5
    assert kept.mode == "include"
    assert kept.selected_udids == {"A"}


def test_platform_heartbeat_contract_includes_inventory_and_policy():
    from autopilot_platform.core.schemas import HeartbeatIn as PlatformHeartbeat

    fields = set(PlatformHeartbeat.model_fields)
    assert {"runner_id", "devices", "inventory", "policy_revision"} <= fields
    assert PlatformHeartbeat.model_fields["inventory"].is_required()
    assert PlatformHeartbeat.model_fields["devices"].is_required()
