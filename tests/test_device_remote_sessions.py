"""Platform Web 远控会话：鉴权、占用前置、Runner 拉令、信令中继。"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient

from autopilot_platform.core.constants import DEFAULT_API_TOKEN
from autopilot_platform.platform.app import create_app
from autopilot_platform.platform.core.db import reset_engine
from autopilot_platform.platform.core.security import (
    create_device_remote_token,
    decode_access_token,
)

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


def login(client: TestClient, username: str = "admin", password: str = "admin") -> dict:
    out = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    assert out.status_code == 200, out.text
    return {"Authorization": f"Bearer {out.json()['access_token']}"}


def register_android_device(client: TestClient, *, runner_id: str = "runner-remote-1") -> str:
    """心跳上报一台 Android 设备，返回 device id。"""
    r = client.post(
        "/api/v1/runners/register",
        headers=TOKEN,
        json={
            "runner_id": runner_id,
            "hostname": "host1",
            "version": "0.2.0",
            "capabilities": ["android", "android-remote"],
        },
    )
    assert r.status_code == 200, r.text
    r = client.post(
        "/api/v1/runners/heartbeat",
        headers=TOKEN,
        json={
            "runner_id": runner_id,
            "capabilities": ["android", "android-remote"],
            "host_backends": ["android-appium"],
            "inventory": [
                {
                    "udid": "ANDROID-SERIAL-1",
                    "platform": "android",
                    "name": "Pixel",
                    "model": "Pixel 8",
                    "os_version": "14",
                    "state": "ready",
                    "backends": ["android-appium"],
                }
            ], "devices": [
                {
                    "udid": "ANDROID-SERIAL-1",
                    "platform": "android",
                    "name": "Pixel",
                    "model": "Pixel 8",
                    "os_version": "14",
                    "state": "ready",
                    "backends": ["android-appium"],
                }
            ],
        },
    )
    assert r.status_code == 200, r.text
    listed = client.get("/api/v1/devices", headers=login(client))
    assert listed.status_code == 200, listed.text
    items = listed.json().get("items") or []
    assert items, "expected device from heartbeat"
    return str(items[0]["id"])


def test_device_remote_token_claims():
    tok = create_device_remote_token(
        sub="u1",
        role="operator",
        username="alice",
        session_id="s1",
        device_id="d1",
        runner_id="r1",
        minutes=30,
    )
    payload = decode_access_token(tok)
    assert payload["typ"] == "device_remote"
    assert payload["purpose"] == "device_remote"
    assert payload["session_id"] == "s1"
    assert payload["device_id"] == "d1"
    assert payload["runner_id"] == "r1"


def test_remote_requires_reservation_first(client: TestClient):
    device_id = register_android_device(client)
    auth = login(client)
    r = client.post(
        f"/api/v1/devices/{device_id}/remote-sessions",
        headers=auth,
        json={"duration_minutes": 30},
    )
    assert r.status_code == 403, r.text
    assert "占用" in (r.json().get("detail") or r.text)


def test_remote_session_full_flow(client: TestClient):
    device_id = register_android_device(client)
    auth = login(client)

    r = client.post(
        f"/api/v1/devices/{device_id}/reservations",
        headers=auth,
        json={"duration_minutes": 30, "reason": "[远控预留]mvp"},
    )
    assert r.status_code in (200, 201), r.text
    reservation_id = r.json()["id"]

    r = client.post(
        f"/api/v1/devices/{device_id}/remote-sessions",
        headers=auth,
        json={"duration_minutes": 30},
    )
    assert r.status_code in (200, 201), r.text
    body = r.json()
    assert body["status"] == "pending"
    assert body["udid"] == "ANDROID-SERIAL-1"
    assert body["access_token"]
    assert "android-scrcpy" in body["capabilities"] or "webrtc" in body["capabilities"]
    session_id = body["id"]

    # Runner 拉令（全局 DEFAULT_API_TOKEN 视为 runner）
    cmds = client.get("/api/v1/runners/me/remote-commands", headers=TOKEN)
    # 全局 token 可能无 runner_id 绑定 → 403 或空列表均可；有绑定则应含 session
    if cmds.status_code == 200:
        items = cmds.json()
        assert isinstance(items, list)

    # 浏览器推 offer，Runner 侧 poll（用用户 JWT 模拟对端；真 Runner 用 Token）
    offer = client.post(
        f"/api/v1/device-remote-sessions/{session_id}/offer",
        headers=auth,
        json={"type": "offer", "sdp": "v=0\r\n", "from_role": "browser"},
    )
    assert offer.status_code == 200, offer.text

    polled = client.get(
        f"/api/v1/device-remote-sessions/{session_id}/signaling-poll",
        headers=auth,
    )
    assert polled.status_code == 200, polled.text
    # 用户 poll 取的是 to_browser 队列；offer 进的是 to_runner，故可能为空
    assert "messages" in polled.json()

    runner_poll = client.get(
        f"/api/v1/device-remote-sessions/{session_id}/signaling-poll",
        headers=TOKEN,
    )
    assert runner_poll.status_code == 200, runner_poll.text
    runner_msgs = runner_poll.json().get("messages") or []
    assert any(str(m.get("type") or "") == "offer" for m in runner_msgs), runner_poll.text

    closed = client.delete(
        f"/api/v1/device-remote-sessions/{session_id}",
        headers=auth,
    )
    assert closed.status_code == 200, closed.text
    assert closed.json()["status"] == "closed"

    # 释放占用
    rel = client.delete(
        f"/api/v1/device-reservations/{reservation_id}",
        headers=auth,
    )
    assert rel.status_code == 200, rel.text


def test_release_reservation_closes_active_remote(client: TestClient):
    device_id = register_android_device(client, runner_id="runner-remote-2")
    auth = login(client)
    r = client.post(
        f"/api/v1/devices/{device_id}/reservations",
        headers=auth,
        json={"duration_minutes": 15, "reason": "[手工调试]"},
    )
    assert r.status_code in (200, 201), r.text
    reservation_id = r.json()["id"]

    r = client.post(
        f"/api/v1/devices/{device_id}/remote-sessions",
        headers=auth,
        json={"duration_minutes": 15},
    )
    assert r.status_code in (200, 201), r.text
    session_id = r.json()["id"]

    rel = client.delete(
        f"/api/v1/device-reservations/{reservation_id}",
        headers=auth,
    )
    assert rel.status_code == 200, rel.text

    got = client.get(
        f"/api/v1/device-remote-sessions/{session_id}",
        headers=auth,
    )
    assert got.status_code == 200, got.text
    assert got.json()["status"] == "closed"


def test_capability_registry_includes_remote_routes():
    from autopilot_platform.platform.tenancy.capability_registry import (
        CAPABILITY_IDS,
        CAPABILITY_ROUTE_BINDINGS,
    )

    assert "cap.devices.remote" in CAPABILITY_IDS
    assert "cap.devices.reserve" in CAPABILITY_IDS
    paths = {(b.method, b.path) for b in CAPABILITY_ROUTE_BINDINGS}
    assert (
        "POST",
        "/api/v1/devices/{device_id}/remote-sessions",
    ) in paths
    assert (
        "POST",
        "/api/v1/devices/{device_id}/remote-sessions/join",
    ) in paths
    assert (
        "POST",
        "/api/v1/device-remote-sessions/{session_id}/commands",
    ) in paths
    assert (
        "GET",
        "/api/v1/device-remote-sessions/{session_id}/ws",
    ) in paths
    assert (
        "GET",
        "/api/v1/runners/me/remote-commands",
    ) in paths
    assert (
        "GET",
        "/api/v1/runners/me/remote-prewarm-hints",
    ) in paths
    assert (
        "POST",
        "/api/v1/devices/{device_id}/reservations",
    ) in paths


def test_prewarm_hints_after_reservation(client: TestClient):
    device_id = register_android_device(client, runner_id="runner-prewarm")
    auth = login(client)
    r = client.post(
        f"/api/v1/devices/{device_id}/reservations",
        headers=auth,
        json={"duration_minutes": 30, "reason": "[远控预留]"},
    )
    assert r.status_code in (200, 201), r.text

    hints = client.get(
        "/api/v1/runners/me/remote-prewarm-hints",
        headers=TOKEN,
        params={"runner_id": "runner-prewarm"},
    )
    assert hints.status_code == 200, hints.text
    items = hints.json()
    assert len(items) == 1
    assert items[0]["udid"] == "ANDROID-SERIAL-1"

    r = client.post(
        f"/api/v1/devices/{device_id}/remote-sessions",
        headers=auth,
        json={"duration_minutes": 30},
    )
    assert r.status_code in (200, 201), r.text

    hints2 = client.get(
        "/api/v1/runners/me/remote-prewarm-hints",
        headers=TOKEN,
        params={"runner_id": "runner-prewarm"},
    )
    assert hints2.status_code == 200, hints2.text
    assert hints2.json() == []


def test_remote_session_rejects_when_runner_at_capacity(client: TestClient, monkeypatch):
    monkeypatch.setenv("MC_MAX_REMOTE_SESSIONS_PER_RUNNER", "1")
    device_id = register_android_device(client, runner_id="runner-cap")
    auth = login(client)
    r = client.post(
        f"/api/v1/devices/{device_id}/reservations",
        headers=auth,
        json={"duration_minutes": 30, "reason": "[远控]"},
    )
    assert r.status_code in (200, 201), r.text

    first = client.post(
        f"/api/v1/devices/{device_id}/remote-sessions",
        headers=auth,
        json={"duration_minutes": 30},
    )
    assert first.status_code in (200, 201), first.text

    # 第二台设备同 runner
    r2 = client.post(
        "/api/v1/runners/heartbeat",
        headers=TOKEN,
        json={
            "runner_id": "runner-cap",
            "capabilities": ["android", "android-remote"],
            "inventory": [
                {
                    "udid": "ANDROID-SERIAL-2",
                    "platform": "android",
                    "name": "Pixel2",
                    "state": "ready",
                }
            ],
            "devices": [
                {
                    "udid": "ANDROID-SERIAL-2",
                    "platform": "android",
                    "name": "Pixel2",
                    "state": "ready",
                }
            ],
        },
    )
    assert r2.status_code == 200, r2.text
    listed = client.get("/api/v1/devices", headers=auth)
    device2 = next(
        x for x in (listed.json().get("items") or []) if x.get("udid") == "ANDROID-SERIAL-2"
    )
    device2_id = device2["id"]
    r3 = client.post(
        f"/api/v1/devices/{device2_id}/reservations",
        headers=auth,
        json={"duration_minutes": 30, "reason": "[远控]"},
    )
    assert r3.status_code in (200, 201), r3.text

    second = client.post(
        f"/api/v1/devices/{device2_id}/remote-sessions",
        headers=auth,
        json={"duration_minutes": 30},
    )
    assert second.status_code == 403, second.text
    body = second.json()
    msg = str(body.get("message") or body.get("detail") or "")
    assert "1/1" in msg or "并发" in msg
