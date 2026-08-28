"""远控链路白盒：占用 → 会话 → 信令中继 → Runner 拉令/状态 → 关闭/释放。

覆盖上个会话落地的 Platform Web 远控（Android 先行）主路径与关键负向门禁。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import threading
import time
from typing import Any, cast
from unittest.mock import MagicMock, patch
from types import ModuleType
import sys

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient

from autopilot_platform.core.constants import DEFAULT_API_TOKEN
from autopilot_platform.platform.app import create_app
from autopilot_platform.platform.core.db import reset_engine
from autopilot_platform.runner.remote.android import input_dispatch
from autopilot_platform.runner.remote.hub import RemotePlatformClient, RemoteSessionHub

TOKEN = {"X-API-Token": DEFAULT_API_TOKEN}


def _noop_signaling(_path: str, _body: dict[str, Any]) -> None:
    return


def _noop_report_status(_session_id: str, _status: str) -> None:
    return


def _noop_post_media(_payload: dict[str, Any]) -> None:
    return


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


def register_device(
    client: TestClient,
    *,
    runner_id: str = "runner-wb-1",
    udid: str = "ANDROID-WB-1",
    platform: str = "android",
) -> str:
    assert (
        client.post(
            "/api/v1/runners/register",
            headers=TOKEN,
            json={
                "runner_id": runner_id,
                "hostname": "wb-host",
                "version": "0.2.0",
                "capabilities": ["android", "android-remote", "ios"],
            },
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/v1/runners/heartbeat",
            headers=TOKEN,
            json={
                "runner_id": runner_id,
                "capabilities": ["android", "android-remote"],
                "host_backends": ["android-appium", "ios-wda"],
                "inventory": [
                    {
                        "udid": udid,
                        "platform": platform,
                        "name": "WB Device",
                        "model": "WB Model",
                        "os_version": "14",
                        "state": "ready",
                        "backends": (
                            ["android-appium"]
                            if platform == "android"
                            else ["ios-wda"]
                        ),
                    }
                ], "devices": [
                    {
                        "udid": udid,
                        "platform": platform,
                        "name": "WB Device",
                        "model": "WB Model",
                        "os_version": "14",
                        "state": "ready",
                        "backends": (
                            ["android-appium"]
                            if platform == "android"
                            else ["ios-wda"]
                        ),
                    }
                ],
            },
        ).status_code
        == 200
    )
    listed = client.get("/api/v1/devices", headers=login(client))
    assert listed.status_code == 200, listed.text
    items = listed.json().get("items") or []
    hit = next((i for i in items if i.get("udid") == udid), None)
    assert hit, f"device {udid} missing from list"
    return str(hit["id"])


def reserve(client: TestClient, auth: dict, device_id: str, reason: str = "[远控预留]") -> str:
    r = client.post(
        f"/api/v1/devices/{device_id}/reservations",
        headers=auth,
        json={"duration_minutes": 30, "reason": reason},
    )
    assert r.status_code in (200, 201), r.text
    return str(r.json()["id"])


def open_remote(client: TestClient, auth: dict, device_id: str) -> dict:
    r = client.post(
        f"/api/v1/devices/{device_id}/remote-sessions",
        headers=auth,
        json={"duration_minutes": 30},
    )
    assert r.status_code in (200, 201), r.text
    return r.json()


def ws_browser_connect(client: TestClient, session_id: str, access_token: str):
    """首帧鉴权连接；返回已 ready 的 WebSocket 上下文管理器包装。"""
    url = f"/api/v1/device-remote-sessions/{session_id}/ws?role=browser"

    class _Ready:
        def __enter__(self):
            self._cm = client.websocket_connect(url)
            self.ws = self._cm.__enter__()
            self.ws.send_json({"type": "auth", "access_token": access_token})
            ready = self.ws.receive_json()
            assert ready["name"] == "transport.ready", ready
            assert ready.get("payload", {}).get("auth_via") == "first_frame"
            return self.ws

        def __exit__(self, *exc):
            return self._cm.__exit__(*exc)

    return _Ready()


# ---------------------------------------------------------------------------
# 1) 主链路：浏览器 offer ↔ Runner answer/ice + 状态机
# ---------------------------------------------------------------------------


def test_whitebox_signaling_cross_role_and_runner_status(client: TestClient):
    """浏览器推 offer → Runner 带 runner_id 拉令并 poll 到 offer → 回 answer/ice。"""
    admin = login(client)
    device_id = register_device(client, runner_id="runner-sig-1", udid="SIG-1")
    reserve(client, admin, device_id)
    session = open_remote(client, admin, device_id)
    sid = session["id"]
    assert session["status"] == "pending"
    assert session["runner_id"] == "runner-sig-1"

    # Runner 拉令须带 runner_id（全局 Token 无绑定）
    cmds = client.get(
        "/api/v1/runners/me/remote-commands",
        headers=TOKEN,
        params={"runner_id": "runner-sig-1"},
    )
    assert cmds.status_code == 200, cmds.text
    ids = [c["session_id"] for c in cmds.json()]
    assert sid in ids

    # 浏览器 → Runner：offer
    assert (
        client.post(
            f"/api/v1/device-remote-sessions/{sid}/offer",
            headers=admin,
            json={"type": "offer", "sdp": "v=0\r\toffer", "from_role": "browser"},
        ).status_code
        == 200
    )

    runner_poll = client.get(
        f"/api/v1/device-remote-sessions/{sid}/signaling-poll",
        headers=TOKEN,
    )
    assert runner_poll.status_code == 200, runner_poll.text
    msgs = runner_poll.json()["messages"]
    assert any(m.get("type") == "offer" and "offer" in str(m.get("sdp")) for m in msgs)

    # Runner → 浏览器：answer + ice
    assert (
        client.post(
            f"/api/v1/device-remote-sessions/{sid}/answer",
            headers=TOKEN,
            json={"type": "answer", "sdp": "v=0\r\nanswer", "from_role": "runner"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/v1/device-remote-sessions/{sid}/ice",
            headers=TOKEN,
            json={
                "type": "ice",
                "candidate": {"candidate": "candidate:1 1 udp 1 1.2.3.4 9 typ host"},
                "from_role": "runner",
            },
        ).status_code
        == 200
    )

    browser_poll = client.get(
        f"/api/v1/device-remote-sessions/{sid}/signaling-poll",
        headers=admin,
    )
    assert browser_poll.status_code == 200, browser_poll.text
    bmsgs = browser_poll.json()["messages"]
    types = {m.get("type") for m in bmsgs}
    assert "answer" in types
    assert "ice" in types

    # 状态机：ready → connected
    ready = client.post(
        f"/api/v1/device-remote-sessions/{sid}/runner-status",
        headers=TOKEN,
        json={"status": "ready", "error_message": ""},
    )
    assert ready.status_code == 200, ready.text
    assert ready.json()["status"] == "ready"

    connected = client.post(
        f"/api/v1/device-remote-sessions/{sid}/runner-status",
        headers=TOKEN,
        json={"status": "connected", "capabilities": ["mirror", "control", "webrtc"]},
    )
    assert connected.status_code == 200, connected.text
    assert connected.json()["status"] == "connected"

    live_board = client.get("/api/v1/devices", headers=admin)
    assert live_board.status_code == 200
    live_item = next(i for i in live_board.json()["items"] if i["id"] == device_id)
    assert live_item.get("remote_session_active") is True
    assert live_item.get("reservation_user_id")

    # 关远控 ≠ 释放占用
    closed = client.delete(f"/api/v1/device-remote-sessions/{sid}", headers=admin)
    assert closed.status_code == 200
    assert closed.json()["status"] == "closed"

    board = client.get("/api/v1/devices", headers=admin)
    assert board.status_code == 200
    item = next(i for i in board.json()["items"] if i["id"] == device_id)
    assert item.get("busy_kind") == "reservation"
    assert item.get("can_release_reservation") is True
    assert item.get("remote_session_active") is False


def test_whitebox_audit_remote_start_stop(client: TestClient):
    admin = login(client)
    device_id = register_device(client, runner_id="runner-audit-1", udid="AUD-1")
    reserve(client, admin, device_id, reason="[手工调试]")
    session = open_remote(client, admin, device_id)
    sid = session["id"]
    assert client.delete(
        f"/api/v1/device-remote-sessions/{sid}", headers=admin
    ).status_code == 200

    starts = client.get(
        "/api/v1/audit",
        headers=admin,
        params={"action": "device.remote_session_start", "limit": 50},
    )
    assert starts.status_code == 200, starts.text
    start_items = starts.json().get("items") or starts.json()
    if isinstance(start_items, dict):
        start_items = start_items.get("items") or []
    assert any(sid in str(i.get("resource_id") or "") for i in start_items)

    stops = client.get(
        "/api/v1/audit",
        headers=admin,
        params={"action": "device.remote_session_stop", "limit": 50},
    )
    assert stops.status_code == 200, stops.text
    stop_items = stops.json().get("items") or stops.json()
    if isinstance(stop_items, dict):
        stop_items = stop_items.get("items") or []
    assert any(sid in str(i.get("resource_id") or "") for i in stop_items)


# ---------------------------------------------------------------------------
# 2) 门禁：非占用人 / 无占用 / 重复打开幂等 / iOS 可建会话
# ---------------------------------------------------------------------------


def test_whitebox_non_owner_cannot_open_or_signal(client: TestClient):
    """占用人外的用户不能打开/信令同一远控会话。"""
    admin = login(client)
    # 再建一个普通用户 bob（无需进 org：鉴权在 session 层拦）
    assert (
        client.post(
            "/api/v1/auth/users",
            headers=admin,
            json={"username": "bob", "password": "Bob12345", "duty": "user"},
        ).status_code
        == 200
    )
    bob = login(client, "bob", "Bob12345")

    device_id = register_device(client, runner_id="runner-own-1", udid="OWN-1")
    reserve(client, admin, device_id)
    session = open_remote(client, admin, device_id)
    sid = session["id"]

    # bob 不能开远控（未占用）
    r = client.post(
        f"/api/v1/devices/{device_id}/remote-sessions",
        headers=bob,
        json={"duration_minutes": 10},
    )
    assert r.status_code == 403, r.text

    # bob 不能 poll / offer 他人会话
    assert (
        client.get(
            f"/api/v1/device-remote-sessions/{sid}/signaling-poll",
            headers=bob,
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/v1/device-remote-sessions/{sid}/offer",
            headers=bob,
            json={"type": "offer", "sdp": "x", "from_role": "browser"},
        ).status_code
        == 403
    )
    assert (
        client.delete(
            f"/api/v1/device-remote-sessions/{sid}",
            headers=bob,
        ).status_code
        == 403
    )


def test_whitebox_reopen_same_user_returns_active_session(client: TestClient):
    auth = login(client)
    device_id = register_device(client, runner_id="runner-idem-1", udid="IDEM-1")
    reserve(client, auth, device_id)
    first = open_remote(client, auth, device_id)
    second = open_remote(client, auth, device_id)
    assert first["id"] == second["id"]
    assert second["access_token"]


def test_whitebox_ios_session_creates_with_mjpeg_caps(client: TestClient):
    auth = login(client)
    device_id = register_device(
        client, runner_id="runner-ios-1", udid="IOS-WB-1", platform="ios"
    )
    reserve(client, auth, device_id, reason="[演示联调]")
    session = open_remote(client, auth, device_id)
    assert session["platform"] == "ios"
    caps = session.get("capabilities") or []
    assert "ios-wda" in caps or "mjpeg" in caps


def test_whitebox_runner_commands_require_runner_id_for_global_token(client: TestClient):
    auth = login(client)
    device_id = register_device(client, runner_id="runner-qid-1", udid="QID-1")
    reserve(client, auth, device_id)
    open_remote(client, auth, device_id)

    bare = client.get("/api/v1/runners/me/remote-commands", headers=TOKEN)
    # 全局 Token 无 runner_id → 403
    assert bare.status_code == 403, bare.text

    ok = client.get(
        "/api/v1/runners/me/remote-commands",
        headers=TOKEN,
        params={"runner_id": "runner-qid-1"},
    )
    assert ok.status_code == 200, ok.text
    assert any(c.get("udid") == "QID-1" for c in ok.json())


def test_whitebox_user_jwt_cannot_list_remote_commands(client: TestClient):
    auth = login(client)
    r = client.get(
        "/api/v1/runners/me/remote-commands",
        headers=auth,
        params={"runner_id": "x"},
    )
    assert r.status_code == 403, r.text


# ---------------------------------------------------------------------------
# 3) Runner Hub 白盒：拉令 → spawn Android/iOS → 指令消失时 stop
# ---------------------------------------------------------------------------


class _FakeRemoteClient:
    def __init__(self) -> None:
        self.commands: list[dict[str, Any]] = []
        self.statuses: list[tuple[str, str, str]] = []
        self.stopped_via_status: list[str] = []
        self.media_posts: list[tuple[str, dict[str, Any]]] = []

    def list_remote_commands(self, _runner_id: str = "") -> list[dict[str, Any]]:
        return list(self.commands)

    @staticmethod
    def list_prewarm_hints(_runner_id: str = "") -> list[dict[str, Any]]:
        return []

    @staticmethod
    def post_remote_signaling(
        _session_id: str, _path: str, _body: dict[str, Any]
    ) -> None:
        return

    @staticmethod
    def poll_remote_signaling(_session_id: str) -> dict[str, Any]:
        return {"messages": [], "session_status": "pending"}

    def post_remote_media(self, session_id: str, body: dict[str, Any]) -> None:
        self.media_posts.append((session_id, dict(body)))

    @staticmethod
    def poll_remote_media(_session_id: str) -> dict[str, Any]:
        return {"messages": [], "session_status": "pending"}

    @staticmethod
    def post_remote_device_logs(_session_id: str, _body: dict[str, Any]) -> None:
        return

    def report_remote_status(
        self,
        session_id: str,
        *,
        status: str,
        error_message: str = "",
        capabilities: list[str] | None = None,
    ) -> None:
        _ = capabilities
        self.statuses.append((session_id, status, error_message))


def test_whitebox_hub_spawns_ios_session_and_stops_when_gone(monkeypatch):
    hub = RemoteSessionHub()
    fake = _FakeRemoteClient()
    started: list[str] = []

    class _StubIos:
        def __init__(self, **kwargs: Any) -> None:
            self.session_id = kwargs["session_id"]
            self.udid = kwargs["udid"]

        def start(self) -> None:
            started.append(self.session_id)

        def stop(self) -> None:
            return

    monkeypatch.setattr(
        "autopilot_platform.runner.remote.ios.session.IosRemoteSession",
        _StubIos,
    )
    fake.commands = [
        {
            "session_id": "sess-ios",
            "device_id": "d1",
            "udid": "UDID-IOS",
            "platform": "ios",
            "status": "pending",
            "capabilities": ["mjpeg"],
            "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
        }
    ]
    hub.sync(cast(RemotePlatformClient, fake), runner_id="r1")
    assert "sess-ios" in hub._sessions  # noqa: SLF001
    assert started == ["sess-ios"]

    fake.commands = []
    stopped = {"n": 0}
    sess = hub._sessions["sess-ios"]  # noqa: SLF001
    orig_stop = sess.stop

    def _stop() -> None:
        stopped["n"] += 1
        orig_stop()

    sess.stop = _stop  # type: ignore[method-assign]
    hub.sync(cast(RemotePlatformClient, fake), runner_id="r1")
    assert "sess-ios" not in hub._sessions  # noqa: SLF001
    assert stopped["n"] == 1


def test_whitebox_hub_spawns_android_session(monkeypatch):
    hub = RemoteSessionHub()
    fake = _FakeRemoteClient()
    started: list[str] = []

    monkeypatch.setattr(
        "autopilot_platform.runner.remote.hub.prewarm_android_scrcpy",
        lambda _udid: None,
    )

    class _StubAndroid:
        def __init__(self, **kwargs: Any) -> None:
            self.session_id = kwargs["session_id"]
            self.udid = kwargs["udid"]

        def start(self) -> None:
            started.append(self.session_id)

        def stop(self) -> None:
            return

    monkeypatch.setattr(
        "autopilot_platform.runner.remote.android.session.AndroidRemoteSession",
        _StubAndroid,
    )
    fake.commands = [
        {
            "session_id": "sess-and",
            "device_id": "d2",
            "udid": "UDID-AND",
            "platform": "android",
            "status": "pending",
            "capabilities": ["webrtc"],
            "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
        }
    ]
    hub.sync(cast(RemotePlatformClient, fake), runner_id="r2")
    assert "sess-and" in hub._sessions  # noqa: SLF001
    assert started == ["sess-and"]


def test_whitebox_hub_passes_poll_media_to_android(monkeypatch):
    hub = RemoteSessionHub()
    fake = _FakeRemoteClient()
    captured: dict[str, Any] = {}

    monkeypatch.setattr(
        "autopilot_platform.runner.remote.hub.prewarm_android_scrcpy",
        lambda _udid: None,
    )

    class _StubAndroid:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

        def start(self) -> None:
            return

        def stop(self) -> None:
            return

    monkeypatch.setattr(
        "autopilot_platform.runner.remote.android.session.AndroidRemoteSession",
        _StubAndroid,
    )
    fake.commands = [
        {
            "session_id": "sess-poll",
            "device_id": "d2",
            "udid": "UDID-AND",
            "platform": "android",
            "status": "pending",
            "capabilities": ["webrtc"],
            "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
        }
    ]
    hub.sync(cast(RemotePlatformClient, fake), runner_id="r2")
    assert captured["session_id"] == "sess-poll"
    assert callable(captured.get("poll_media"))
    assert callable(captured.get("poll_signaling"))


# ---------------------------------------------------------------------------
# 4) 触控分发白盒（DataChannel JSON → control）
# ---------------------------------------------------------------------------


def test_whitebox_input_dispatch_touch_key_text():
    control = MagicMock()
    client = MagicMock()
    client.control = control

    input_dispatch.dispatch(
        client, '{"t":"touch","x":10,"y":20,"action":0}', device_id="u1"
    )
    control.touch.assert_called_once_with(10, 20, 0)

    input_dispatch.dispatch(client, '{"t":"key","code":4,"action":0}')
    control.keycode.assert_called_once_with(4, 0)

    input_dispatch.dispatch(client, '{"t":"text","text":"hello"}')
    control.text.assert_called_once_with("hello")

    # 非法 JSON / 未知类型不抛
    input_dispatch.dispatch(client, "not-json")
    input_dispatch.dispatch(client, '{"t":"unknown"}')


def test_whitebox_input_batch_key_down_up():
    """Platform media batch：一次 POST 内 key down+up 顺序 dispatch。"""
    control = MagicMock()
    client = MagicMock()
    client.control = control
    batch = [
        {"t": "key", "code": 3, "action": 0},
        {"t": "key", "code": 3, "action": 1},
    ]
    for item in batch:
        input_dispatch.dispatch(
            client,
            f'{{"t":"key","code":{item["code"]},"action":{item["action"]}}}',
        )
    assert control.keycode.call_args_list == [
        ((3, 0),),
        ((3, 1),),
    ]


def test_whitebox_input_dispatch_clipboard_reply():
    control = MagicMock()
    control.get_clipboard.return_value = "clip"
    control.set_clipboard.return_value = True
    client = MagicMock()
    client.control = control
    replies: list[dict] = []

    input_dispatch.dispatch(
        client, '{"t":"clipboard.get"}', reply=replies.append
    )
    assert replies and replies[0]["t"] == "clipboard.value"
    assert replies[0]["text"] == "clip"

    input_dispatch.dispatch(
        client,
        '{"t":"clipboard.set","text":"x","paste":true}',
        reply=replies.append,
    )
    assert any(r.get("t") == "clipboard.ack" for r in replies)


# ---------------------------------------------------------------------------
# 4b) WebRTC 重协商 + WS media 兜底：input 须到达 scrcpy control
# ---------------------------------------------------------------------------


def _inject_android_session_deps(
    monkeypatch,
    *,
    client: MagicMock,
    peer_manager_factory,
) -> None:
    fake_scrcpy = ModuleType("autopilot_platform.runner.remote.android.scrcpyclients")
    fake_scrcpy.get_client = lambda _udid: client
    fake_scrcpy.stop_client = lambda _udid: None
    fake_adb = ModuleType("autopilot_platform.runner.remote.android.adb_dispatch")
    fake_adb.dispatch = lambda *_a, **_k: None
    monkeypatch.setitem(
        sys.modules,
        "autopilot_platform.runner.remote.android.scrcpyclients",
        fake_scrcpy,
    )
    monkeypatch.setitem(
        sys.modules,
        "autopilot_platform.runner.remote.android.adb_dispatch",
        fake_adb,
    )
    monkeypatch.setattr(
        "autopilot_platform.runner.remote.android.webrtc.peer_manager.get_peer_manager",
        peer_manager_factory,
    )


def test_whitebox_android_media_poll_input_dispatches_touch(monkeypatch):
    """Platform WS/HTTP media input → Runner poll_media → input_dispatch。"""
    from autopilot_platform.runner.remote.android.session import AndroidRemoteSession

    control = MagicMock()
    client = MagicMock()
    client.alive = True
    client.control = control

    _inject_android_session_deps(
        monkeypatch,
        client=client,
        peer_manager_factory=lambda: MagicMock(close_device=lambda *_: None),
    )

    media_polls = [
        [{"type": "input", "payload": {"t": "touch", "x": 5, "y": 6, "action": 0}}],
    ]
    session = AndroidRemoteSession(
        session_id="sess-media-in",
        udid="UDID-MEDIA",
        post_signaling=_noop_signaling,
        poll_signaling=lambda: [],
        poll_media=lambda: media_polls.pop(0) if media_polls else [],
        report_status=_noop_report_status,
        post_media=None,
    )
    thread = threading.Thread(target=session._run, daemon=True)
    thread.start()
    thread.join(timeout=3.0)
    session.stop()
    thread.join(timeout=2.0)

    control.touch.assert_called_once_with(5, 6, 0)


def test_whitebox_android_media_poll_clipboard_command(monkeypatch):
    """Platform HTTP/WS command → Runner poll_media → adb_dispatch 剪贴板。"""
    from autopilot_platform.runner.remote.android.session import AndroidRemoteSession

    control = MagicMock()
    control.get_clipboard.return_value = "from-device"
    client = MagicMock()
    client.alive = True
    client.control = control

    replies: list[dict[str, Any]] = []

    def _fake_adb_dispatch(adb_client, raw, reply, *, _device_id):
        import json

        evt = json.loads(raw)
        if evt.get("t") == "clipboard.get":
            payload = {
                "t": "clipboard.value",
                "text": adb_client.control.get_clipboard(),
            }
            if evt.get("request_id"):
                payload["request_id"] = evt["request_id"]
            reply(payload)

    _inject_android_session_deps(
        monkeypatch,
        client=client,
        peer_manager_factory=lambda: MagicMock(close_device=lambda *_: None),
    )
    fake_adb = sys.modules["autopilot_platform.runner.remote.android.adb_dispatch"]
    fake_adb.dispatch = _fake_adb_dispatch

    media_polls: list[list[dict[str, Any]]] = [
        [
            {
                "type": "command",
                "payload": {"t": "clipboard.get", "request_id": "req-media-1"},
            }
        ],
        [{"t": "clipboard.get", "request_id": "req-media-2"}],
    ]
    session = AndroidRemoteSession(
        session_id="sess-media-clip",
        udid="UDID-CLIP",
        post_signaling=_noop_signaling,
        poll_signaling=lambda: [],
        poll_media=lambda: media_polls.pop(0) if media_polls else [],
        report_status=_noop_report_status,
        post_media=lambda body: replies.append(body),
    )
    thread = threading.Thread(target=session._run, daemon=True)
    thread.start()
    thread.join(timeout=3.0)
    from autopilot_platform.runner.remote.android.adb_executor import flush, shutdown_device

    flush("UDID-CLIP")
    session.stop()
    shutdown_device("UDID-CLIP", wait=True)
    thread.join(timeout=2.0)

    assert control.get_clipboard.call_count >= 2
    values = [
        item["payload"]
        for item in replies
        if item.get("type") == "command_reply"
        and item.get("payload", {}).get("t") == "clipboard.value"
    ]
    assert values
    assert values[0]["text"] == "from-device"
    assert values[0]["request_id"] == "req-media-1"


def test_whitebox_android_media_poll_device_info_ws_envelope(monkeypatch):
    """WS/HTTP 信封 type=request、name=device.info 必须进 adb_dispatch，不能被前缀过滤丢掉。"""
    from autopilot_platform.runner.remote.android.session import AndroidRemoteSession

    client = MagicMock()
    client.alive = True
    replies: list[dict[str, Any]] = []

    def _fake_adb_dispatch(_client, raw, reply, *, device_id):
        import json

        evt = json.loads(raw)
        if evt.get("t") == "device.info":
            payload = {
                "t": "device.info.result",
                "device_id": device_id,
                "model": "Pixel",
            }
            if evt.get("request_id"):
                payload["request_id"] = evt["request_id"]
            reply(payload)

    _inject_android_session_deps(
        monkeypatch,
        client=client,
        peer_manager_factory=lambda: MagicMock(close_device=lambda *_: None),
    )
    fake_adb = sys.modules["autopilot_platform.runner.remote.android.adb_dispatch"]
    fake_adb.dispatch = _fake_adb_dispatch

    media_polls: list[list[dict[str, Any]]] = [
        [
            {
                "channel": "command",
                "type": "request",
                "name": "device.info",
                "request_id": "req-info-ws",
                "payload": {"t": "device.info", "request_id": "req-info-ws"},
            }
        ],
    ]
    session = AndroidRemoteSession(
        session_id="sess-media-info",
        udid="UDID-INFO",
        post_signaling=_noop_signaling,
        poll_signaling=lambda: [],
        poll_media=lambda: media_polls.pop(0) if media_polls else [],
        report_status=_noop_report_status,
        post_media=lambda body: replies.append(body),
    )
    thread = threading.Thread(target=session._run, daemon=True)
    thread.start()
    thread.join(timeout=3.0)
    from autopilot_platform.runner.remote.android.adb_executor import flush, shutdown_device

    flush("UDID-INFO")
    session.stop()
    shutdown_device("UDID-INFO", wait=True)
    thread.join(timeout=2.0)

    results = [
        item["payload"]
        for item in replies
        if item.get("type") == "command_reply"
        and item.get("payload", {}).get("t") == "device.info.result"
    ]
    assert results
    assert results[0]["model"] == "Pixel"
    assert results[0]["request_id"] == "req-info-ws"


def test_whitebox_android_renegotiation_input_on_live_peer(monkeypatch):
    """两次 offer（重协商）后 input 回调须挂到 replace 后的 PeerSession 并可 dispatch。"""
    from autopilot_platform.runner.remote.android.session import AndroidRemoteSession

    registrations: list[tuple[str, int]] = []
    counter = {"n": 0}

    class FakePeerSession:
        def __init__(self) -> None:
            counter["n"] += 1
            self.id = counter["n"]
            self.pc = MagicMock()
            self.pc.connectionState = "new"
            self.pc.remoteDescription = None
            self._input = None

        def on_local_ice(self, _cb) -> None:
            return

        def on_input_message(self, cb) -> None:
            registrations.append(("input", self.id))
            self._input = cb

        def on_adb_message(self, _cb) -> None:
            registrations.append(("adb", self.id))

        def on_closed(self, _cb) -> None:
            registrations.append(("closed", self.id))

        def on_input_open(self, _cb) -> None:
            registrations.append(("input_open", self.id))

        @staticmethod
        def input_channel_ready() -> bool:
            return False

        @staticmethod
        def send_input(_payload) -> bool:
            return True

        @staticmethod
        def send_adb(_payload) -> bool:
            return True

    class FakePM:
        def __init__(self) -> None:
            self._sess: FakePeerSession | None = None

        def get_or_create(self, _sid, _device_id, **_kw) -> FakePeerSession:
            if self._sess is None:
                self._sess = FakePeerSession()
            return self._sess

        def get(self, _sid, _device_id) -> FakePeerSession | None:
            return self._sess

        def handle_offer(self, _sid, _device_id, _sdp, *, readonly: bool = False) -> dict[str, str]:
            _ = readonly
            assert self._sess is not None
            if self._sess.pc.remoteDescription is not None:
                self._sess = FakePeerSession()
            else:
                self._sess.pc.remoteDescription = object()
            return {"sdp": "v=0", "type": "answer"}

        def attach_video(self, *_args) -> None:
            return

        def handle_ice(self, *_args) -> None:
            return

        def close(self, *_args) -> None:
            return

        def detach_video(self, *_args) -> None:
            return

        def close_device(self, *_args) -> None:
            return

    fake_pm = FakePM()
    control = MagicMock()
    client = MagicMock()
    client.alive = True
    client.control = control

    _inject_android_session_deps(
        monkeypatch,
        client=client,
        peer_manager_factory=lambda: fake_pm,
    )

    signaling_polls: list[list[dict[str, Any]]] = [
        [{"type": "offer", "sdp": "offer-1", "participant_id": "p1"}],
        [{"type": "offer", "sdp": "offer-2", "participant_id": "p1"}],
    ]
    session = AndroidRemoteSession(
        session_id="sess-reneg",
        udid="UDID-RENEG",
        post_signaling=_noop_signaling,
        poll_signaling=lambda: signaling_polls.pop(0) if signaling_polls else [],
        poll_media=lambda: [],
        report_status=_noop_report_status,
        post_media=None,
    )
    thread = threading.Thread(target=session._run, daemon=True)
    thread.start()
    thread.join(timeout=4.0)
    session.stop()
    thread.join(timeout=2.0)

    input_regs = [item for item in registrations if item[0] == "input"]
    assert len(input_regs) >= 2
    assert input_regs[-1][1] == 2

    live = fake_pm.get("sess-reneg:p1", "UDID-RENEG")
    assert live is not None and live._input is not None
    live._input('{"t":"key","code":4,"action":0}')
    control.keycode.assert_called_once_with(4, 0)


def test_whitebox_peer_manager_restore_callbacks_after_renegotiation() -> None:
    """PeerManager.handle_offer 重协商时通过 snapshot/restore 保留回调。"""
    from autopilot_platform.runner.remote.android.webrtc import peer_manager as pm_mod

    saved = pm_mod.PeerSessionCallbacks(
        on_input_message=lambda _msg: None,
        on_adb_message=lambda _msg: None,
        on_ice_local=lambda _c: None,
        on_closed=lambda _s: None,
        on_input_open=lambda: None,
    )
    old = MagicMock()
    old.pc.connectionState = "connected"
    old.pc.remoteDescription = object()
    old.snapshot_callbacks.return_value = saved

    new = MagicMock()
    new.handle_offer = MagicMock(return_value={"sdp": "v=0", "type": "answer"})

    mgr = pm_mod.PeerManager()
    mgr._sessions[("sid-wb", "dev-wb")] = old

    with patch.object(mgr, "close") as close_mock, patch.object(
        mgr, "get_or_create", return_value=new
    ), patch.object(mgr, "runner") as runner_mock:
        runner_mock.return_value.run_sync.side_effect = lambda coro, timeout=15: coro
        out = mgr.handle_offer("sid-wb", "dev-wb", "offer-sdp")

    close_mock.assert_called_once_with("sid-wb", "dev-wb")
    new.restore_callbacks.assert_called_once_with(saved)
    assert out["type"] == "answer"


def test_whitebox_android_participant_left_closes_peer(monkeypatch):
    from autopilot_platform.runner.remote.android.session import AndroidRemoteSession

    closed: list[tuple[str, str]] = []

    class FakePM:
        @staticmethod
        def get_or_create(*_a, **_k):
            return MagicMock()

        @staticmethod
        def get(*_a, **_k):
            return None

        @staticmethod
        def close(sid, device_id=None) -> None:
            closed.append((str(sid), str(device_id or "")))

        def handle_ice(self, *_a, **_k) -> None:
            return

        def attach_video(self, *_a, **_k) -> None:
            return

        def detach_video(self, *_a, **_k) -> None:
            return

        def close_device(self, *_a, **_k) -> None:
            return

    _inject_android_session_deps(
        monkeypatch,
        client=MagicMock(alive=True, control=MagicMock()),
        peer_manager_factory=lambda: FakePM(),
    )
    polls: list[list[dict[str, Any]]] = [
        [{"type": "participant.left", "participant_id": "p-view"}],
    ]
    session = AndroidRemoteSession(
        session_id="sess-left",
        udid="UDID-LEFT",
        post_signaling=_noop_signaling,
        poll_signaling=lambda: polls.pop(0) if polls else [],
        poll_media=lambda: [],
        report_status=_noop_report_status,
        post_media=None,
    )
    thread = threading.Thread(target=session._run, daemon=True)
    thread.start()
    deadline = time.time() + 3.0
    while time.time() < deadline and not closed:
        time.sleep(0.05)
    session.stop()
    thread.join(timeout=2.0)
    assert ("sess-left:p-view", "UDID-LEFT") in closed


def test_peer_manager_skips_reset_when_other_peer_attached() -> None:
    from autopilot_platform.runner.remote.android.webrtc.peer_manager import PeerManager

    mgr = PeerManager()
    first = MagicMock()
    first.device_id = "dev-1"
    first.has_scrcpy_source.return_value = True
    second = MagicMock()
    second.device_id = "dev-1"
    second.has_scrcpy_source.return_value = False
    mgr._sessions[("sess-a", "dev-1")] = first
    mgr._sessions[("sess-b", "dev-1")] = second
    mgr.attach_video("sess-b", "dev-1", MagicMock())
    second.attach_video_source.assert_called_once()
    kwargs = second.attach_video_source.call_args
    assert kwargs.kwargs.get("request_keyframe") is False


def test_peer_manager_first_attach_requests_keyframe() -> None:
    from autopilot_platform.runner.remote.android.webrtc.peer_manager import PeerManager

    mgr = PeerManager()
    only = MagicMock()
    only.device_id = "dev-1"
    only.has_scrcpy_source.return_value = False
    mgr._sessions[("sess-a", "dev-1")] = only
    mgr.attach_video("sess-a", "dev-1", MagicMock())
    assert only.attach_video_source.call_args.kwargs.get("request_keyframe") is True


# ---------------------------------------------------------------------------
# 5) scrcpy 配置对齐 4.0
# ---------------------------------------------------------------------------


def test_whitebox_scrcpy_server_version_aligned():
    from autopilot_platform.runner.remote import config
    from autopilot_platform.runner.remote.android import scrcpyconst

    assert config.SCRCPY_SERVER_VERSION == "4.0"
    assert scrcpyconst.SCRCPY_SERVER_VERSION == "4.0"
    assert config.SCRCPY_SERVER_PATH.endswith("scrcpy-server.jar")
    assert "resources" in config.SCRCPY_SERVER_PATH.replace("\\", "/")
    assert "re_scrcpy" in config.SCRCPY_SERVER_PATH.replace("\\", "/")


# ---------------------------------------------------------------------------
# Phase 3：WS / viewer / command / TURN / quality
# ---------------------------------------------------------------------------


def test_phase3_websocket_relay(client: TestClient):
    admin = login(client)
    device_id = register_device(client, runner_id="runner-ws-3", udid="WS-3")
    reserve(client, admin, device_id)
    session = open_remote(client, admin, device_id)
    sid = session["id"]
    token = session["access_token"]

    runner_url = f"/api/v1/device-remote-sessions/{sid}/ws?role=runner"
    with ws_browser_connect(client, sid, token) as browser:
        with client.websocket_connect(runner_url, headers=TOKEN) as runner:
            assert runner.receive_json()["name"] == "transport.ready"
            browser.send_json(
                {
                    "channel": "signaling",
                    "type": "event",
                    "name": "offer",
                    "request_id": "req-ws-1",
                    "payload": {"type": "offer", "sdp": "v=0\r\n"},
                }
            )
            relayed = runner.receive_json()
            assert relayed["channel"] == "signaling"
            assert relayed["payload"]["sdp"].startswith("v=0")


def test_whitebox_ws_relays_binary_jpeg_to_browser(client: TestClient):
    from autopilot_platform.runner.remote.shared.frame_bus import (
        pack_binary_frame,
        unpack_binary_frame,
    )

    admin = login(client)
    device_id = register_device(client, runner_id="runner-ws-bin", udid="WS-BIN-1")
    reserve(client, admin, device_id)
    session = open_remote(client, admin, device_id)
    sid = session["id"]
    packed = pack_binary_frame(b"\xff\xd8\xff\xd9", width=12, height=16)
    runner_url = f"/api/v1/device-remote-sessions/{sid}/ws?role=runner"
    with ws_browser_connect(client, sid, session["access_token"]) as browser:
        with client.websocket_connect(runner_url, headers=TOKEN) as runner:
            assert runner.receive_json()["name"] == "transport.ready"
            runner.send_bytes(packed)
            got = browser.receive_bytes()
    parsed = unpack_binary_frame(got)
    assert parsed is not None
    assert parsed["jpeg"] == b"\xff\xd8\xff\xd9"
    assert parsed["width"] == 12
    assert parsed["height"] == 16


def test_whitebox_ws_binary_frame_falls_back_to_http_poll(client: TestClient):
    from autopilot_platform.runner.remote.shared.frame_bus import pack_binary_frame

    admin = login(client)
    device_id = register_device(client, runner_id="runner-ws-bin-http", udid="WS-BIN-2")
    reserve(client, admin, device_id)
    session = open_remote(client, admin, device_id)
    sid = session["id"]
    packed = pack_binary_frame(b"\xff\xd8\xff\xd9", width=8, height=8)
    runner_url = f"/api/v1/device-remote-sessions/{sid}/ws?role=runner"
    with client.websocket_connect(runner_url, headers=TOKEN) as runner:
        assert runner.receive_json()["name"] == "transport.ready"
        runner.send_bytes(packed)
    polled = client.get(
        f"/api/v1/device-remote-sessions/{sid}/media-poll",
        headers=admin,
    )
    assert polled.status_code == 200, polled.text
    frames = [
        m
        for m in (polled.json().get("messages") or [])
        if m.get("type") == "frame"
    ]
    assert frames
    assert frames[0].get("data_b64")
    assert frames[0].get("width") == 8


def test_phase3_viewer_is_readonly_and_can_be_kicked(client: TestClient):
    admin = login(client)
    created = client.post(
        "/api/v1/auth/users",
        headers=admin,
        json={"username": "member3", "password": "Member123", "duty": "user"},
    )
    assert created.status_code == 200, created.text
    member = login(client, "member3", "Member123")
    assert (
        client.post(
            "/api/v1/auth/users",
            headers=admin,
            json={"username": "owner3", "password": "Owner1234", "duty": "user"},
        ).status_code
        == 200
    )
    owner = login(client, "owner3", "Owner1234")
    device_id = register_device(
        client, runner_id="runner-view-3", udid="VIEW-3"
    )
    reserve(client, owner, device_id)
    idle_board = client.get("/api/v1/devices", headers=admin)
    idle_item = next(i for i in idle_board.json()["items"] if i["id"] == device_id)
    assert idle_item.get("remote_session_active") is False
    steal_create = client.post(
        f"/api/v1/devices/{device_id}/remote-sessions",
        headers=admin,
        json={"duration_minutes": 30},
    )
    assert steal_create.status_code == 403, steal_create.text
    session = open_remote(client, owner, device_id)
    sid = session["id"]

    denied_join = client.post(
        f"/api/v1/devices/{device_id}/remote-sessions/join",
        headers=member,
        json={"role": "viewer", "connection_id": "member-denied"},
    )
    assert denied_join.status_code == 403, denied_join.text

    steal = client.post(
        f"/api/v1/devices/{device_id}/remote-sessions",
        headers=admin,
        json={"duration_minutes": 30},
    )
    assert steal.status_code == 403, steal.text

    joined = client.post(
        f"/api/v1/devices/{device_id}/remote-sessions/join",
        headers=admin,
        json={"role": "viewer", "connection_id": "viewer-test-3"},
    )
    assert joined.status_code == 200, joined.text
    assert joined.json()["participant_role"] == "viewer"
    participant_id = joined.json()["participant_id"]

    peeked = client.get(
        f"/api/v1/device-remote-sessions/{sid}",
        headers=admin,
    )
    assert peeked.status_code == 200, peeked.text
    assert peeked.json()["participant_role"] == "viewer"

    denied = client.post(
        f"/api/v1/device-remote-sessions/{sid}/media",
        headers=admin,
        json={
            "type": "input",
            "from_role": "browser",
            "payload": {"t": "home"},
        },
    )
    assert denied.status_code == 403, denied.text
    readonly = client.post(
        f"/api/v1/device-remote-sessions/{sid}/commands",
        headers=admin,
        json={"name": "device.info", "request_id": "view-info", "payload": {}},
    )
    assert readonly.status_code == 200, readonly.text
    listed = client.post(
        f"/api/v1/device-remote-sessions/{sid}/commands",
        headers=admin,
        json={"name": "file.list", "request_id": "view-list", "payload": {"path": "/sdcard"}},
    )
    assert listed.status_code == 200, listed.text
    pulled = client.post(
        f"/api/v1/device-remote-sessions/{sid}/commands",
        headers=admin,
        json={"name": "file.pull", "request_id": "view-pull", "payload": {"path": "/sdcard/a.txt"}},
    )
    assert pulled.status_code == 200, pulled.text
    mutated = client.post(
        f"/api/v1/device-remote-sessions/{sid}/commands",
        headers=admin,
        json={"name": "file.delete", "request_id": "view-del", "payload": {"path": "/sdcard/a.txt"}},
    )
    assert mutated.status_code == 403, mutated.text
    signal = client.post(
        f"/api/v1/device-remote-sessions/{sid}/offer",
        headers=admin,
        json={
            "type": "offer",
            "sdp": "v=0\r\nviewer",
            "participant_id": participant_id,
        },
    )
    assert signal.status_code == 200, signal.text
    kicked = client.delete(
        f"/api/v1/device-remote-sessions/{sid}/participants/{participant_id}",
        headers=owner,
    )
    assert kicked.status_code == 200, kicked.text
    assert kicked.json()["status"] == "left"
    left_poll = client.get(
        f"/api/v1/device-remote-sessions/{sid}/signaling-poll",
        headers=TOKEN,
    )
    assert left_poll.status_code == 200, left_poll.text
    assert any(
        m.get("type") == "participant.left"
        and m.get("participant_id") == participant_id
        for m in left_poll.json().get("messages") or []
    ), left_poll.text


def test_phase3_http_command_status_fallback(client: TestClient):
    admin = login(client)
    device_id = register_device(
        client, runner_id="runner-cmd-3", udid="CMD-3"
    )
    reserve(client, admin, device_id)
    sid = open_remote(client, admin, device_id)["id"]
    accepted = client.post(
        f"/api/v1/device-remote-sessions/{sid}/commands",
        headers=admin,
        json={
            "name": "clipboard.get",
            "request_id": "cmd-status-1",
            "payload": {},
        },
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "accepted"
    runner_poll = client.get(
        f"/api/v1/device-remote-sessions/{sid}/media-poll",
        headers=TOKEN,
    )
    assert runner_poll.status_code == 200, runner_poll.text
    assert any(
        item.get("t") == "clipboard.get"
        for item in runner_poll.json()["messages"]
    )
    replied = client.post(
        f"/api/v1/device-remote-sessions/{sid}/media",
        headers=TOKEN,
        json={
            "type": "command_reply",
            "from_role": "runner",
            "payload": {
                "t": "clipboard.value",
                "request_id": "cmd-status-1",
                "text": "hello",
            },
        },
    )
    assert replied.status_code == 200, replied.text
    status = client.get(
        f"/api/v1/device-remote-sessions/{sid}/commands/cmd-status-1",
        headers=admin,
    )
    assert status.status_code == 200, status.text
    assert status.json()["status"] == "completed"
    assert status.json()["result"]["text"] == "hello"


def test_phase3_turn_hmac_credentials(monkeypatch):
    import base64
    import hashlib
    import hmac

    from autopilot_platform.platform.core.security import create_turn_credentials

    secret = "turn-test-secret-with-at-least-32-bytes"
    monkeypatch.setenv("MC_TURN_SECRET", secret)
    username, credential, expires_at = create_turn_credentials("session-turn-3")
    expected = base64.b64encode(
        hmac.new(
            secret.encode(),
            username.encode(),
            hashlib.sha1,
        ).digest()
    ).decode()
    assert credential == expected
    assert username.endswith(":autopilot:session-turn-3")
    assert expires_at > datetime.now(timezone.utc)


def test_phase3_ios_quality_ladder():
    from autopilot_platform.runner.remote.ios.quality_controller import (
        IosQualityController,
    )

    controller = IosQualityController(initial_fps=12)
    controller.enabled = True
    for _ in range(12):
        controller.observe(2_000_000)
    snapshot = controller.snapshot()
    assert snapshot.average_frame_bytes == 2_000_000
    assert snapshot.fps <= 12


def test_phase3_command_protocol_roundtrip():
    from autopilot_platform.runner.remote.shared.command_protocol import (
        RemoteChannel,
        RemoteEnvelope,
        RemoteMessageType,
        result_for,
    )

    request = RemoteEnvelope(
        channel=RemoteChannel.COMMAND.value,
        type=RemoteMessageType.REQUEST.value,
        name="file.list",
        payload={"path": "/sdcard"},
    )
    restored = RemoteEnvelope.from_dict(request.to_dict())
    assert restored.request_id == request.request_id
    assert result_for(restored, {"ok": True}).type == "result"


def test_phase3_normalize_reliable_command_accepts_device_info():
    from autopilot_platform.runner.remote.shared.command_protocol import (
        is_reliable_command_name,
        normalize_reliable_command,
    )

    assert is_reliable_command_name("device.info")
    assert is_reliable_command_name("home")
    assert not is_reliable_command_name("touch")
    ws = normalize_reliable_command(
        {
            "channel": "command",
            "type": "request",
            "name": "device.info",
            "request_id": "req-info-1",
            "payload": {"t": "device.info", "request_id": "req-info-1"},
        }
    )
    assert ws is not None
    assert ws["t"] == "device.info"
    assert ws["request_id"] == "req-info-1"
    http = normalize_reliable_command(
        {"t": "device.info", "name": "device.info", "request_id": "req-info-2"}
    )
    assert http is not None
    assert http["t"] == "device.info"
    assert normalize_reliable_command({"type": "offer", "sdp": "v=0"}) is None
    log_start = normalize_reliable_command(
        {
            "channel": "command",
            "type": "request",
            "name": "log.start",
            "request_id": "req-log-1",
            "payload": {"t": "log.start", "level": "I"},
        }
    )
    assert log_start is not None
    assert log_start["t"] == "log.start"
    assert is_reliable_command_name("log.stop")


def test_phase3_android_chunk_transfer_cancel():
    import base64

    from autopilot_platform.runner.remote.android import file_transfer

    replies: list[dict[str, Any]] = []
    event = {
        "id": "transfer-whitebox-3",
        "name": "hello.txt",
        "size": 5,
        "remote": "/sdcard/Download/",
    }
    file_transfer.begin(event, replies.append)
    file_transfer.chunk(
        {
            "id": event["id"],
            "seq": 0,
            "data": base64.b64encode(b"hello").decode(),
        },
        replies.append,
    )
    file_transfer.cancel({"id": event["id"]}, replies.append)
    assert [reply["t"] for reply in replies] == [
        "file.ready",
        "file.progress",
        "file.cancelled",
    ]
    assert replies[1]["received"] == 5


def test_android_apk_upload_without_install_flag_pushes_only(monkeypatch):
    import base64

    from autopilot_platform.runner.remote.android import file_transfer

    pushed: list[str] = []

    class _Client:
        class Device:
            class Sync:
                @staticmethod
                def push(local_path: str, remote: str) -> None:
                    pushed.append(f"{local_path}|{remote}")

            sync = Sync

        device = Device

    replies: list[dict[str, Any]] = []
    event = {
        "id": "transfer-apk-push",
        "name": "demo.apk",
        "size": 3,
        "remote": "/sdcard/Download/",
    }
    file_transfer.begin(event, replies.append)
    file_transfer.chunk(
        {
            "id": event["id"],
            "seq": 0,
            "data": base64.b64encode(b"apk").decode(),
        },
        replies.append,
    )
    file_transfer.end(
        {"id": event["id"], "install": False},
        _Client(),
        replies.append,
        install_apk=lambda _path, _force: {"ok": True},
    )
    assert pushed
    assert replies[-1]["t"] == "file.done"
    assert replies[-1]["action"] == "push"


def test_android_file_end_push_failure_replies_file_error():
    import base64

    from autopilot_platform.runner.remote.android import file_transfer

    class _Client:
        class Device:
            class Sync:
                @staticmethod
                def push(_local_path: str, _remote: str) -> None:
                    raise OSError("Permission denied")

            sync = Sync

        device = Device

    replies: list[dict[str, Any]] = []
    event = {
        "id": "transfer-root-denied",
        "name": "fast_script.py",
        "size": 4,
        "remote": "/",
    }
    file_transfer.begin(event, replies.append)
    file_transfer.chunk(
        {
            "id": event["id"],
            "seq": 0,
            "data": base64.b64encode(b"code").decode(),
        },
        replies.append,
    )
    file_transfer.end({"id": event["id"]}, _Client(), replies.append)
    assert replies[-1]["t"] == "file.error"
    assert "Permission denied" in replies[-1]["error"]


def test_phase3_ios_export_limit_is_explicit():
    from autopilot_platform.runner.remote.ios.command_dispatch import dispatch

    replies: list[dict[str, Any]] = []
    dispatch(
        MagicMock(),
        "IOS-WHITEBOX-3",
        {
            "t": "app.export",
            "package": "com.example.app",
            "request_id": "ios-export-3",
        },
        replies.append,
    )
    assert replies[0]["t"] == "app.export.error"
    assert replies[0]["error_code"] == "not_supported"
    assert replies[0]["request_id"] == "ios-export-3"


# ---------------------------------------------------------------------------
# 6) iOS media 旁路 + 触控 / 切帧
# ---------------------------------------------------------------------------


def test_whitebox_media_frame_and_input_isolated_from_signaling(client: TestClient):
    """frame/input 走 media 队列，不污染 SDP signaling-poll。"""
    import base64

    admin = login(client)
    device_id = register_device(
        client, runner_id="runner-media-1", udid="MEDIA-IOS-1", platform="ios"
    )
    reserve(client, admin, device_id)
    session = open_remote(client, admin, device_id)
    sid = session["id"]

    jpeg = base64.b64encode(b"\xff\xd8\xff\xd9").decode("ascii")
    posted = client.post(
        f"/api/v1/device-remote-sessions/{sid}/media",
        headers=TOKEN,
        json={
            "type": "frame",
            "from_role": "runner",
            "data_b64": jpeg,
            "width": 100,
            "height": 200,
            "mime": "image/jpeg",
        },
    )
    assert posted.status_code == 200, posted.text

    # Runner 推 frame 后 browser media-poll 应拿到；signaling-poll 应为空
    media = client.get(
        f"/api/v1/device-remote-sessions/{sid}/media-poll",
        headers=admin,
    )
    assert media.status_code == 200, media.text
    msgs = media.json().get("messages") or []
    assert len(msgs) == 1
    assert msgs[0]["type"] == "frame"
    assert msgs[0]["data_b64"] == jpeg
    assert msgs[0]["width"] == 100

    replay = client.get(
        f"/api/v1/device-remote-sessions/{sid}/media-poll",
        headers=admin,
    )
    assert replay.status_code == 200, replay.text
    assert not any(
        m.get("type") == "frame" for m in replay.json().get("messages") or []
    )

    sig = client.get(
        f"/api/v1/device-remote-sessions/{sid}/signaling-poll",
        headers=admin,
    )
    assert sig.status_code == 200
    assert (sig.json().get("messages") or []) == []

    # 浏览器 input → Runner media-poll
    inp = client.post(
        f"/api/v1/device-remote-sessions/{sid}/media",
        headers=admin,
        json={
            "type": "input",
            "from_role": "browser",
            "payload": {"t": "touch", "x": 1, "y": 2, "action": 0},
        },
    )
    assert inp.status_code == 200, inp.text
    runner_media = client.get(
        f"/api/v1/device-remote-sessions/{sid}/media-poll",
        headers=TOKEN,
    )
    assert runner_media.status_code == 200, runner_media.text
    rmsgs = runner_media.json().get("messages") or []
    assert any(m.get("type") == "input" for m in rmsgs)


def test_http_media_frame_fanout_to_each_browser(client: TestClient):
    """HTTP MJPEG 最新帧按参与者游标分发，互不抢槽。"""
    import base64

    admin = login(client)
    created = client.post(
        "/api/v1/auth/users",
        headers=admin,
        json={"username": "owner-frame", "password": "Owner1234", "duty": "user"},
    )
    assert created.status_code == 200, created.text
    owner = login(client, "owner-frame", "Owner1234")
    device_id = register_device(
        client, runner_id="runner-media-fan", udid="MEDIA-FAN-1", platform="ios"
    )
    reserve(client, owner, device_id)
    session = open_remote(client, owner, device_id)
    sid = session["id"]
    joined = client.post(
        f"/api/v1/devices/{device_id}/remote-sessions/join",
        headers=admin,
        json={"role": "viewer", "connection_id": "viewer-frame"},
    )
    assert joined.status_code == 200, joined.text

    jpeg = base64.b64encode(b"\xff\xd8\xff\xd9").decode("ascii")
    posted = client.post(
        f"/api/v1/device-remote-sessions/{sid}/media",
        headers=TOKEN,
        json={
            "type": "frame",
            "from_role": "runner",
            "data_b64": jpeg,
            "width": 80,
            "height": 60,
            "mime": "image/jpeg",
        },
    )
    assert posted.status_code == 200, posted.text

    owner_media = client.get(
        f"/api/v1/device-remote-sessions/{sid}/media-poll",
        headers=owner,
    )
    viewer_media = client.get(
        f"/api/v1/device-remote-sessions/{sid}/media-poll",
        headers=admin,
    )
    assert owner_media.status_code == 200, owner_media.text
    assert viewer_media.status_code == 200, viewer_media.text
    owner_frames = [
        m for m in owner_media.json().get("messages") or [] if m.get("type") == "frame"
    ]
    viewer_frames = [
        m for m in viewer_media.json().get("messages") or [] if m.get("type") == "frame"
    ]
    assert len(owner_frames) == 1 and owner_frames[0]["data_b64"] == jpeg
    assert len(viewer_frames) == 1 and viewer_frames[0]["data_b64"] == jpeg

    owner_again = client.get(
        f"/api/v1/device-remote-sessions/{sid}/media-poll",
        headers=owner,
    )
    assert not any(
        m.get("type") == "frame" for m in owner_again.json().get("messages") or []
    )

    jpeg2 = base64.b64encode(b"\xff\xd8\xff\xd9\x00").decode("ascii")
    posted2 = client.post(
        f"/api/v1/device-remote-sessions/{sid}/media",
        headers=TOKEN,
        json={
            "type": "frame",
            "from_role": "runner",
            "data_b64": jpeg2,
            "width": 80,
            "height": 60,
            "mime": "image/jpeg",
        },
    )
    assert posted2.status_code == 200, posted2.text
    owner_next = client.get(
        f"/api/v1/device-remote-sessions/{sid}/media-poll",
        headers=owner,
    )
    viewer_next = client.get(
        f"/api/v1/device-remote-sessions/{sid}/media-poll",
        headers=admin,
    )
    assert any(
        m.get("data_b64") == jpeg2
        for m in owner_next.json().get("messages") or []
        if m.get("type") == "frame"
    )
    assert any(
        m.get("data_b64") == jpeg2
        for m in viewer_next.json().get("messages") or []
        if m.get("type") == "frame"
    )


def test_whitebox_ios_input_dispatch_tap_swipe():
    from autopilot_platform.runner.remote.ios.input_dispatch import (
        TouchState,
        dispatch_input,
    )
    from autopilot_platform.runner.remote.ios.mjpeg_reader import split_jpegs
    from autopilot_platform.runner.remote.shared.coords import map_display_to_device

    assert map_display_to_device(
        50, 100, display_w=100, display_h=200, device_w=200, device_h=400
    ) == (100, 200)
    # contain + letterbox：画面 100x100 居中于 200x100 面板
    assert map_display_to_device(
        100,
        50,
        display_w=200,
        display_h=100,
        device_w=100,
        device_h=100,
        content_fit="contain",
    ) == (50, 50)

    wda = MagicMock()
    st = TouchState()
    dispatch_input(
        wda,
        {"t": "touch", "x": 10, "y": 20, "action": 0},
        touch_state=st,
        display_w=100,
        display_h=200,
        device_w=100,
        device_h=200,
    )
    dispatch_input(
        wda,
        {"t": "touch", "x": 10, "y": 20, "action": 1},
        touch_state=st,
        display_w=100,
        display_h=200,
        device_w=100,
        device_h=200,
    )
    wda.tap.assert_called_once_with(10, 20)

    wda.reset_mock()
    dispatch_input(
        wda,
        {"t": "scroll", "x": 50, "y": 100, "h": 0, "v": 120},
        touch_state=TouchState(),
        display_w=100,
        display_h=200,
        device_w=100,
        device_h=200,
    )
    time.sleep(0.05)
    wda.swipe.assert_called_once_with(50, 100, 50, 220, duration_ms=120)

    frames, rest = split_jpegs(b"xx\xff\xd8ABC\xff\xd9yy")
    assert frames == [b"\xff\xd8ABC\xff\xd9"]
    # 非 JPEG 尾部噪声应丢弃，避免缓冲无界增长。
    assert rest == b""


def test_whitebox_ios_input_dispatch_buttons_and_dpad_box():
    """对齐 WebAppFlaskauto-iOS：home=pressButton, lock=/wda/lock, volume camelCase, 方向键 1000 盒。"""
    from autopilot_platform.runner.remote.ios.input_dispatch import (
        TouchState,
        dispatch_input,
    )

    kwargs = dict(
        touch_state=TouchState(),
        display_w=1170,
        display_h=2532,
        device_w=390,
        device_h=844,
    )
    wda = MagicMock()
    dispatch_input(wda, {"t": "home"}, **kwargs)
    wda.press_button.assert_called_once_with("home")
    wda.home.assert_not_called()

    wda.reset_mock()
    dispatch_input(wda, {"t": "lock"}, **kwargs)
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline and not wda.lock.called:
        time.sleep(0.01)
    wda.lock.assert_called_once()
    wda.press_button.assert_not_called()

    wda.reset_mock()
    dispatch_input(wda, {"t": "press_button", "name": "volumeup"}, **kwargs)
    wda.press_button.assert_called_once_with("volumeUp")

    wda.reset_mock()
    dispatch_input(
        wda,
        {
            "t": "swipe",
            "startX": 500,
            "startY": 680,
            "endX": 500,
            "endY": 320,
            "display_width": 1000,
            "display_height": 1000,
            "duration": 180,
        },
        **kwargs,
    )
    wda.swipe.assert_called_once()
    sx, sy, ex, ey = wda.swipe.call_args.args[:4]
    assert (sx, sy) == (195, 574)
    assert (ex, ey) == (195, 270)
    assert wda.swipe.call_args.kwargs["duration_ms"] == 180

    wda.reset_mock()
    dispatch_input(
        wda,
        {"type": "input", "payload": {"t": "press_button", "name": "volumedown"}},
        **kwargs,
    )
    wda.press_button.assert_called_once_with("volumeDown")


def test_whitebox_ios_home_command_envelope_and_media_fallback():
    """Home 对齐 Flask POST /button：command 通道可分发；旧 media 信封也能拆出 t=home。"""
    from autopilot_platform.runner.remote.ios.command_dispatch import dispatch
    from autopilot_platform.runner.remote.ios.input_dispatch import coerce_input_event
    from autopilot_platform.runner.remote.shared.command_protocol import (
        normalize_reliable_command,
    )

    wda = MagicMock()
    replies: list[dict[str, Any]] = []
    event = normalize_reliable_command(
        {
            "channel": "command",
            "type": "request",
            "name": "home",
            "request_id": "home-1",
            "payload": {"t": "home", "request_id": "home-1"},
        }
    )
    assert event is not None
    assert event["t"] == "home"
    dispatch(wda, "IOS-HOME", event, replies.append)
    wda.press_button.assert_called_once_with("home")
    wda.home.assert_not_called()
    wda.swipe.assert_not_called()
    assert replies[-1]["t"] == "button.ack"

    nested = coerce_input_event(
        {
            "type": "event",
            "name": "input",
            "payload": {
                "type": "input",
                "from_role": "browser",
                "payload": {"t": "home"},
            },
        }
    )
    assert nested is not None
    assert nested["t"] == "home"
    top = coerce_input_event({"t": "home", "type": "home"})
    assert top is not None and top["t"] == "home"


def test_whitebox_ios_home_swipe_fallback_when_press_fails():
    from autopilot_platform.ap.keywords.registry import KeywordError
    from autopilot_platform.runner.remote.ios.input_dispatch import press_wda_button

    wda = MagicMock()
    wda.press_button.side_effect = KeywordError("press home failed")
    wda.window_size.return_value = {"width": 390, "height": 844}
    press_wda_button(wda, "home")
    wda.press_button.assert_called_once_with("home")
    wda.drag_from_to_for_duration.assert_called_once()


def test_whitebox_ios_input_wda_error_does_not_propagate():
    """锁屏/点按 WDA 失败不得穿出 dispatch_input，否则 Hub 会 respawn 整段会话。"""
    from autopilot_platform.ap.keywords.registry import KeywordError
    from autopilot_platform.runner.remote.ios.input_dispatch import (
        TouchState,
        dispatch_input,
    )

    kwargs = dict(
        touch_state=TouchState(),
        display_w=1170,
        display_h=2532,
        device_w=390,
        device_h=844,
    )
    wda = MagicMock()
    wda.lock.side_effect = KeywordError(
        "WDA 错误: Timed out while waiting until the screen gets locked"
    )
    dispatch_input(wda, {"t": "lock"}, **kwargs)
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline and not wda.lock.called:
        time.sleep(0.01)
    wda.lock.assert_called_once()

    wda.reset_mock()
    wda.tap.side_effect = KeywordError("WDA 错误: unknown error")
    dispatch_input(wda, {"t": "touch", "x": 100, "y": 200, "action": 0}, **kwargs)
    dispatch_input(wda, {"t": "touch", "x": 100, "y": 200, "action": 1}, **kwargs)
    wda.tap.assert_called_once()


def test_whitebox_ios_wda_worker_does_not_block_submit():
    """对齐 Flask：锁屏 HTTP 不堵画面 poll；submit 必须立刻返回。"""
    import queue
    import threading

    from autopilot_platform.runner.remote.ios.session import IosRemoteSession

    sess = IosRemoteSession(
        session_id="sess-wda-offloop",
        udid="00008140-TEST",
        post_media=_noop_post_media,
        poll_media=lambda: [],
        report_status=_noop_report_status,
    )
    started = threading.Event()
    release = threading.Event()

    def _block() -> None:
        started.set()
        release.wait(timeout=2.0)

    sess._start_wda_worker()
    sess._submit_wda(_block)
    assert started.wait(timeout=1.0)
    t0 = time.monotonic()
    sess._submit_wda(lambda: None)
    assert time.monotonic() - t0 < 0.2
    release.set()
    sess.stop()
    assert isinstance(sess._wda_jobs, queue.Queue)


def test_whitebox_ios_aux_queue_does_not_block_home_submit():
    """file.pull 走 aux；Home 走 WDA 队列，aux 堵塞不得拖住 Home 入队。"""
    import queue
    import threading

    from autopilot_platform.runner.remote.ios.session import (
        IosRemoteSession,
        command_job_lane,
    )

    assert command_job_lane("file.pull") == "aux"
    assert command_job_lane("home") == "wda"

    sess = IosRemoteSession(
        session_id="sess-aux-home",
        udid="00008140-TEST",
        post_media=_noop_post_media,
        poll_media=lambda: [],
        report_status=_noop_report_status,
    )
    started = threading.Event()
    release = threading.Event()
    home_ran = threading.Event()

    def _block_file() -> None:
        started.set()
        release.wait(timeout=2.0)

    def _home() -> None:
        home_ran.set()

    sess._start_wda_worker()
    sess._submit_aux(_block_file)
    assert started.wait(timeout=1.0)
    t0 = time.monotonic()
    sess._submit_wda(_home)
    assert time.monotonic() - t0 < 0.2
    assert home_ran.wait(timeout=1.0)
    release.set()
    sess.stop()
    assert isinstance(sess._aux_jobs, queue.Queue)


def test_whitebox_shared_frame_bus_payload():
    from autopilot_platform.runner.remote.shared.frame_bus import (
        binary_frame_to_http_payload,
        build_frame_message,
        pack_binary_frame,
        unpack_binary_frame,
    )

    msg = build_frame_message(b"\xff\xd8\xff\xd9", width=9, height=8)
    assert msg["type"] == "frame"
    assert msg["width"] == 9
    assert msg["height"] == 8
    assert msg["data_b64"]

    packed = pack_binary_frame(b"\xff\xd8\xff\xd9", width=9, height=8)
    parsed = unpack_binary_frame(packed)
    assert parsed is not None
    assert parsed["jpeg"] == b"\xff\xd8\xff\xd9"
    assert parsed["width"] == 9
    assert parsed["height"] == 8
    http = binary_frame_to_http_payload(packed)
    assert http is not None
    assert http["data_b64"] == msg["data_b64"]
    assert unpack_binary_frame(b"not-a-frame") is None


def test_whitebox_ios_session_prepares_wda_and_posts_frame(monkeypatch):
    """真实 IosRemoteSession 编排壳：自动发现 WDA、首帧、状态与回收。"""
    from autopilot_platform.runner.remote.ios.session import IosRemoteSession

    captured: dict[str, Any] = {}
    connected = threading.Event()

    class _Prep:
        def __init__(
            self,
            udid: str,
            wda_bundle: str,
            *,
            info_port: int,
            wda_port: int,
            mjpeg_port: int,
            cancel_event: threading.Event,
            log=None,
        ) -> None:
            captured.update(
                udid=udid,
                wda_bundle=wda_bundle,
                info_port=info_port,
                wda_port=wda_port,
                mjpeg_port=mjpeg_port,
                cancel_event=cancel_event,
                log=log,
            )

        @staticmethod
        def prepare() -> str:
            return "http://127.0.0.1:8100"

        @staticmethod
        def mjpeg_url() -> str:
            return f"http://127.0.0.1:{captured['mjpeg_port']}"

        @staticmethod
        def stop() -> None:
            captured["prep_stopped"] = True

    class _Wda:
        def __init__(self, url: str) -> None:
            captured["wda_url"] = url
            self._http = MagicMock()

        @staticmethod
        def create_session() -> None:
            captured["wda_session"] = True

        @staticmethod
        def update_settings(settings: dict) -> None:
            captured["wda_settings"] = dict(settings)

        @staticmethod
        def set_recover(_fn) -> None:
            captured["wda_recover"] = True

        @staticmethod
        def window_size() -> dict[str, int]:
            return {"width": 390, "height": 844}

        @staticmethod
        def delete_session() -> None:
            captured["wda_deleted"] = True

    class _Reader:
        def __init__(self, url, on_frame, **_kwargs) -> None:
            captured["mjpeg_url"] = url
            self._on_frame = on_frame

        def start(self) -> None:
            self._on_frame(b"\xff\xd8\xff\xd9", 390, 844)

        @staticmethod
        def stop() -> None:
            captured["reader_stopped"] = True

    monkeypatch.setattr(
        "autopilot_platform.ap.mobile.ios_bootstrap.IosDevicePrep", _Prep
    )
    monkeypatch.setattr(
        "autopilot_platform.ap.mobile.ios_bootstrap.ensure_mjpeg_ready",
        lambda *args, **kwargs: True,
    )
    monkeypatch.setattr(
        "autopilot_platform.ap.keywords.mobile.wda_client.WdaClient", _Wda
    )
    monkeypatch.setattr(
        "autopilot_platform.runner.remote.ios.session.MjpegReader", _Reader
    )

    frames: list[dict[str, Any]] = []
    statuses: list[str] = []

    def report(status: str, _error: str) -> None:
        statuses.append(status)
        if status == "connected":
            connected.set()

    session = IosRemoteSession(
        session_id="ios-unit",
        udid="IOS-UDID",
        post_media=frames.append,
        poll_media=lambda: [],
        report_status=report,
    )
    session.start()
    assert connected.wait(2)
    session.stop()
    if session._thread is not None:  # noqa: SLF001
        session._thread.join(timeout=2)  # noqa: SLF001

    assert captured["wda_bundle"] == ""
    assert captured["wda_session"] is True
    assert captured.get("wda_settings")
    assert captured["wda_settings"].get("mjpegScalingFactor") == 60
    assert captured["wda_settings"].get("mjpegServerScreenshotQuality") == 45
    assert captured.get("wda_recover") is True
    assert callable(captured.get("log"))
    assert captured["mjpeg_url"].endswith(f":{captured['mjpeg_port']}")
    assert statuses[:2] == ["ready", "connected"]
    assert frames and frames[0]["type"] == "frame"
    assert frames[0]["jpeg"] == b"\xff\xd8\xff\xd9"
    assert "data_b64" not in frames[0]
    assert captured["prep_stopped"] is True


# ---------------------------------------------------------------------------
# 7) Phase3 审计补强：WS 鉴权、promote 实时 ACL、双端命令矩阵
# ---------------------------------------------------------------------------


def test_whitebox_ws_rejects_wrong_session_token(client: TestClient):
    admin = login(client)
    device_a = register_device(client, runner_id="runner-ws-tok", udid="WS-TOK-A")
    device_b = register_device(
        client, runner_id="runner-ws-tok-b", udid="WS-TOK-B"
    )
    reserve(client, admin, device_a)
    reserve(client, admin, device_b)
    sess_a = open_remote(client, admin, device_a)
    sess_b = open_remote(client, admin, device_b)
    url = f"/api/v1/device-remote-sessions/{sess_a['id']}/ws?role=browser"
    with client.websocket_connect(url) as ws:
        ws.send_json(
            {"type": "auth", "access_token": sess_b["access_token"]}
        )
        with pytest.raises(Exception):
            # 鉴权失败后服务端关闭连接；再读会失败
            while True:
                ws.receive_json()


def test_whitebox_ws_viewer_command_forbidden(client: TestClient):
    admin = login(client)
    assert (
        client.post(
            "/api/v1/auth/users",
            headers=admin,
            json={"username": "owner-ws", "password": "Owner1234", "duty": "user"},
        ).status_code
        == 200
    )
    owner = login(client, "owner-ws", "Owner1234")
    device_id = register_device(
        client, runner_id="runner-ws-view", udid="WS-VIEW-1"
    )
    reserve(client, owner, device_id)
    session = open_remote(client, owner, device_id)
    joined = client.post(
        f"/api/v1/devices/{device_id}/remote-sessions/join",
        headers=admin,
        json={"role": "viewer", "connection_id": "viewer-ws-1"},
    )
    assert joined.status_code == 200, joined.text
    token = joined.json()["access_token"]
    sid = session["id"]
    with ws_browser_connect(client, sid, token) as browser:
        browser.send_json(
            {
                "channel": "command",
                "type": "request",
                "name": "clipboard.set",
                "request_id": "viewer-cmd-1",
                "payload": {"text": "nope"},
            }
        )
        err = browser.receive_json()
        assert err["error_code"] == "forbidden"
        browser.send_json(
            {
                "channel": "command",
                "type": "request",
                "name": "device.info",
                "request_id": "viewer-spoof-1",
                "payload": {"t": "clipboard.set", "text": "nope"},
            }
        )
        spoofed = browser.receive_json()
        assert spoofed["error_code"] == "forbidden"
        browser.send_json(
            {
                "channel": "command",
                "type": "request",
                "name": "device.info",
                "request_id": "viewer-info-1",
                "payload": {},
            }
        )
        browser.send_json(
            {
                "channel": "signaling",
                "type": "event",
                "name": "ping-check",
                "request_id": "sig-ok",
                "payload": {},
            }
        )


def test_whitebox_ws_legacy_query_token_still_works(client: TestClient):
    """兼容回退：query access_token 仍可握手（auth_via=query）。"""
    admin = login(client)
    device_id = register_device(
        client, runner_id="runner-ws-legacy", udid="WS-LEGACY"
    )
    reserve(client, admin, device_id)
    session = open_remote(client, admin, device_id)
    url = (
        f"/api/v1/device-remote-sessions/{session['id']}/ws"
        f"?role=browser&access_token={session['access_token']}"
    )
    with client.websocket_connect(url) as browser:
        ready = browser.receive_json()
        assert ready["name"] == "transport.ready"
        assert ready["payload"]["auth_via"] == "query"


def test_whitebox_promote_transfers_control_and_ws_acl(client: TestClient):
    """promote 后：原控制者立即失权，旁观管理员获得 HTTP/WS 命令权。"""
    admin = login(client)
    assert (
        client.post(
            "/api/v1/auth/users",
            headers=admin,
            json={
                "username": "owner-a",
                "password": "Ctrl12345",
                "duty": "user",
            },
        ).status_code
        == 200
    )
    owner = login(client, "owner-a", "Ctrl12345")
    device_id = register_device(
        client, runner_id="runner-promote", udid="PROMOTE-1"
    )
    reserve(client, owner, device_id)
    session = open_remote(client, owner, device_id)
    sid = session["id"]
    owner_token = session["access_token"]
    joined = client.post(
        f"/api/v1/devices/{device_id}/remote-sessions/join",
        headers=admin,
        json={"role": "viewer", "connection_id": "promote-admin"},
    )
    assert joined.status_code == 200, joined.text
    pid_admin = joined.json()["participant_id"]
    peer_token = joined.json()["access_token"]

    owner_uid = str(session["user_id"])
    promoted = client.post(
        f"/api/v1/device-remote-sessions/{sid}/participants/{pid_admin}/promote",
        headers=owner,
    )
    assert promoted.status_code == 200, promoted.text
    assert promoted.json()["role"] == "controller"
    host = client.get(f"/api/v1/device-remote-sessions/{sid}", headers=owner)
    assert host.status_code == 200, host.text
    assert host.json()["user_id"] == owner_uid
    assert host.json()["participant_role"] == "viewer"
    transferred = client.get(
        f"/api/v1/device-remote-sessions/{sid}/signaling-poll",
        headers=TOKEN,
    )
    assert transferred.status_code == 200, transferred.text
    assert any(
        m.get("type") == "control.transferred"
        and m.get("controller_participant_id") == pid_admin
        for m in transferred.json().get("messages") or []
    ), transferred.text

    denied = client.post(
        f"/api/v1/device-remote-sessions/{sid}/commands",
        headers=owner,
        json={
            "name": "clipboard.set",
            "request_id": "old-ctrl",
            "payload": {"text": "nope"},
        },
    )
    assert denied.status_code == 403, denied.text

    allowed = client.post(
        f"/api/v1/device-remote-sessions/{sid}/commands",
        headers=admin,
        json={"name": "clipboard.get", "request_id": "new-ctrl", "payload": {}},
    )
    assert allowed.status_code == 200, allowed.text

    # 旧票仍可握手，但 command 通道实时 ACL 拒绝写操作
    with ws_browser_connect(client, sid, owner_token) as browser:
        browser.send_json(
            {
                "channel": "command",
                "type": "request",
                "name": "clipboard.set",
                "request_id": "ws-old",
                "payload": {"text": "nope"},
            }
        )
        err = browser.receive_json()
        assert err["error_code"] == "forbidden"

    with ws_browser_connect(client, sid, peer_token) as browser:
        browser.send_json(
            {
                "channel": "command",
                "type": "request",
                "name": "clipboard.get",
                "request_id": "ws-new",
                "payload": {},
            }
        )
        browser.send_json(
            {
                "channel": "signaling",
                "type": "event",
                "name": "ping-check",
                "request_id": "sig-ok",
                "payload": {},
            }
        )

    closed_ok = client.delete(
        f"/api/v1/device-remote-sessions/{sid}", headers=owner
    )
    assert closed_ok.status_code == 200, closed_ok.text


def test_whitebox_admin_viewer_cannot_control_but_can_close(client: TestClient):
    """admin 旁观不夺取控制权；仍可 break-glass 关闭会话。"""
    admin = login(client)
    assert (
        client.post(
            "/api/v1/auth/users",
            headers=admin,
            json={
                "username": "owner-ctrl",
                "password": "Owner1234",
                "duty": "user",
            },
        ).status_code
        == 200
    )
    owner = login(client, "owner-ctrl", "Owner1234")
    device_id = register_device(
        client, runner_id="runner-admin-acl", udid="ADMIN-ACL-1"
    )
    reserve(client, owner, device_id)
    session = open_remote(client, owner, device_id)
    sid = session["id"]

    joined = client.post(
        f"/api/v1/devices/{device_id}/remote-sessions/join",
        headers=admin,
        json={"role": "viewer", "connection_id": "admin-as-viewer"},
    )
    assert joined.status_code == 200, joined.text
    assert joined.json()["participant_role"] == "viewer"

    denied = client.post(
        f"/api/v1/device-remote-sessions/{sid}/commands",
        headers=admin,
        json={
            "name": "clipboard.set",
            "request_id": "admin-cmd",
            "payload": {"text": "nope"},
        },
    )
    assert denied.status_code == 403, denied.text

    closed = client.delete(
        f"/api/v1/device-remote-sessions/{sid}",
        headers=admin,
    )
    assert closed.status_code == 200, closed.text
    assert closed.json()["status"] == "closed"


def test_whitebox_android_adb_command_matrix(monkeypatch):
    """Android adb_dispatch 关键命令矩阵（剪贴板/未知）。"""
    import importlib
    import sys

    monkeypatch.setitem(sys.modules, "adbutils", MagicMock())
    for key in list(sys.modules):
        if key.startswith("autopilot_platform.runner.remote.android"):
            del sys.modules[key]
    dispatch = importlib.import_module(
        "autopilot_platform.runner.remote.android.adb_dispatch"
    ).dispatch

    replies: list[dict[str, Any]] = []
    control = MagicMock()
    control.get_clipboard.return_value = "clip-android"
    control.set_clipboard.return_value = True
    client = MagicMock()
    client.control = control

    dispatch(
        client,
        '{"t":"clipboard.get","request_id":"a1"}',
        replies.append,
        device_id="serial-1",
    )
    assert replies[-1]["t"] == "clipboard.value"
    assert replies[-1]["text"] == "clip-android"
    assert replies[-1]["request_id"] == "a1"

    dispatch(
        client,
        '{"t":"clipboard.set","text":"x","paste":true,"request_id":"a2"}',
        replies.append,
        device_id="serial-1",
    )
    assert replies[-1]["t"] == "clipboard.ack"
    control.set_clipboard.assert_called()

    dispatch(
        client,
        '{"t":"unknown.cmd","request_id":"a3"}',
        replies.append,
        device_id="serial-1",
    )
    assert replies[-1]["error_code"] == "not_supported"

    monkeypatch.setattr(
        "autopilot_platform.runner.remote.android.device_info.collect",
        lambda device_id: {"device_id": device_id, "model": "Pixel", "platform": "android"},
    )
    dispatch(
        client,
        '{"t":"device.info","request_id":"a4"}',
        replies.append,
        device_id="serial-1",
    )
    assert replies[-1]["t"] == "device.info.result"
    assert replies[-1]["model"] == "Pixel"
    assert replies[-1]["request_id"] == "a4"


def test_whitebox_android_stream_configure_reattaches_client(monkeypatch):
    """stream.configure 必须把新的 scrcpy Client 交给 WebRTC，不能把 (client, old) 元组塞进去。"""
    import importlib
    from pathlib import Path

    monkeypatch.setitem(sys.modules, "adbutils", MagicMock())
    monkeypatch.setitem(sys.modules, "av", MagicMock())
    monkeypatch.setitem(sys.modules, "av.codec", MagicMock())
    monkeypatch.setitem(sys.modules, "av.error", MagicMock())
    for key in list(sys.modules):
        if key.startswith("autopilot_platform.runner.remote.android"):
            del sys.modules[key]
    adb_dispatch = importlib.import_module(
        "autopilot_platform.runner.remote.android.adb_dispatch"
    )
    scrcpyclients = importlib.import_module(
        "autopilot_platform.runner.remote.android.scrcpyclients"
    )
    peer_manager = importlib.import_module(
        "autopilot_platform.runner.remote.android.webrtc.peer_manager"
    )

    new_client = MagicMock(name="new-scrcpy")
    peers = MagicMock()
    monkeypatch.setattr(scrcpyclients, "reconfigure", lambda _device_id, **_kwargs: new_client)
    monkeypatch.setattr(
        scrcpyclients,
        "get_device_config",
        lambda _device_id: {
            "bitrate": 2_000_000,
            "max_fps": 30,
            "max_width": 0,
            "i_frame_interval": 2,
        },
    )
    monkeypatch.setattr(peer_manager, "get_peer_manager", lambda: peers)

    replies: list[dict[str, Any]] = []
    adb_dispatch.dispatch(
        MagicMock(),
        '{"t":"stream.configure","bitrate":2000000,"max_fps":30,'
        '"max_width":0,"i_frame_interval":2,"adaptive":false,"request_id":"s1"}',
        replies.append,
        device_id="serial-1",
    )
    assert replies[-1]["t"] == "stream.configure.result"
    assert replies[-1]["ok"] is True
    peers.reattach_for_device.assert_called_once_with("serial-1", new_client)
    src = (
        Path(__file__).resolve().parents[1]
        / "autopilot_platform"
        / "runner"
        / "remote"
        / "android"
        / "scrcpyclients.py"
    ).read_text(encoding="utf-8")
    assert "return new_client, old" not in src


def test_whitebox_ios_command_matrix_clipboard_and_unknown():
    from autopilot_platform.runner.remote.ios.command_dispatch import dispatch

    replies: list[dict[str, Any]] = []
    wda = MagicMock()
    wda.get_pasteboard.return_value = "clip-ios"
    dispatch(
        wda,
        "IOS-1",
        {"t": "clipboard.get", "request_id": "i1"},
        replies.append,
    )
    assert replies[-1]["text"] == "clip-ios"
    dispatch(
        wda,
        "IOS-1",
        {"t": "clipboard.set", "text": "y", "request_id": "i2"},
        replies.append,
    )
    assert replies[-1]["t"] == "clipboard.ack"
    wda.set_pasteboard.assert_called_with("y")
    from autopilot_platform.runner.remote.ios import device_info as ios_device_info

    ios_device_info.collect = MagicMock(  # type: ignore[method-assign]
        return_value={"device_id": "IOS-1", "ios_version": "17.5", "platform": "ios"}
    )
    dispatch(
        wda,
        "IOS-1",
        {"t": "device.info", "request_id": "i3"},
        replies.append,
    )
    assert replies[-1]["t"] == "device.info.result"
    assert replies[-1]["ios_version"] == "17.5"
    dispatch(
        wda,
        "IOS-1",
        {"t": "totally.unknown", "request_id": "i4"},
        replies.append,
    )
    assert replies[-1]["error_code"] == "not_supported"
    from autopilot_platform.ap.keywords.registry import KeywordError

    replies.clear()
    wda.reset_mock()
    dispatch(
        wda,
        "IOS-1",
        {"t": "home", "request_id": "i-home"},
        replies.append,
    )
    wda.press_button.assert_called_once_with("home")
    assert replies[-1]["t"] == "button.ack"
    assert replies[-1]["button"] == "home"

    replies.clear()
    wda.get_pasteboard.side_effect = KeywordError("WDA 错误: boom")
    dispatch(
        wda,
        "IOS-1",
        {"t": "clipboard.get", "request_id": "i5"},
        replies.append,
    )
    assert replies[-1]["t"] == "error"
    assert replies[-1]["request_id"] == "i5"


def test_whitebox_android_file_browser_sort_and_normalize(monkeypatch):
    import importlib
    import sys

    monkeypatch.setitem(sys.modules, "adbutils", MagicMock())
    for key in list(sys.modules):
        if key.startswith("autopilot_platform.runner.remote.android"):
            del sys.modules[key]
    file_browser = importlib.import_module(
        "autopilot_platform.runner.remote.android.file_browser"
    )

    class _Item:
        def __init__(self, path: str, mode: int = 0o100644, size: int = 1):
            self.path = path
            self.mode = mode
            self.size = size
            self.mtime = 0

    class _Sync:
        @staticmethod
        def list(_path: str):
            return [_Item("b.txt"), _Item("a", mode=0o040755), _Item("c.txt")]

        @staticmethod
        def stat(path: str):
            return _Item(path, mode=0o040755 if path.endswith("a") else 0o100644)

    class _Dev:
        sync = _Sync()

    monkeypatch.setattr(file_browser, "_device", lambda _id: _Dev())
    out = file_browser.list_directory("serial", "/sdcard")
    assert out["ok"] is True
    names = [e["name"] for e in out["entries"]]
    assert names[0] == "a"
    assert "b.txt" in names and "c.txt" in names


def test_whitebox_shared_coords_letterbox():
    from autopilot_platform.runner.remote.shared.coords import map_display_to_device

    x, y = map_display_to_device(
        320,
        240,
        display_w=640,
        display_h=480,
        device_w=1280,
        device_h=720,
    )
    assert 0 <= x <= 1280
    assert 0 <= y <= 720


def test_whitebox_max_viewers_zero_blocks_join(client: TestClient):
    admin = login(client)
    assert (
        client.post(
            "/api/v1/auth/users",
            headers=admin,
            json={"username": "owner-max", "password": "Owner1234", "duty": "user"},
        ).status_code
        == 200
    )
    owner = login(client, "owner-max", "Owner1234")
    device_id = register_device(
        client, runner_id="runner-maxv", udid="MAXV-1"
    )
    reserve(client, owner, device_id)
    opened = client.post(
        f"/api/v1/devices/{device_id}/remote-sessions",
        headers=owner,
        json={"duration_minutes": 30, "max_viewers": 0},
    )
    assert opened.status_code == 200, opened.text
    assert opened.json()["max_viewers"] == 0
    joined = client.post(
        f"/api/v1/devices/{device_id}/remote-sessions/join",
        headers=admin,
        json={"role": "viewer", "connection_id": "maxv-1"},
    )
    assert joined.status_code == 403, joined.text


def test_whitebox_remote_jar_matches_local(monkeypatch):
    import importlib
    import sys

    monkeypatch.setitem(sys.modules, "adbutils", MagicMock())
    monkeypatch.setitem(sys.modules, "av", MagicMock())
    monkeypatch.setitem(sys.modules, "av.codec", MagicMock())
    monkeypatch.setitem(sys.modules, "av.error", MagicMock())
    for key in list(sys.modules):
        if key.startswith("autopilot_platform.runner.remote.android"):
            del sys.modules[key]
    scrcpyclients = importlib.import_module(
        "autopilot_platform.runner.remote.android.scrcpyclients"
    )
    monkeypatch.setattr(
        scrcpyclients,
        "_sha256_file",
        lambda _path: "local-sha",
    )
    monkeypatch.setattr(
        scrcpyclients,
        "get_remote_server_info",
        lambda _device_id: {"exists": True, "sha256": "local-sha"},
    )
    assert scrcpyclients.remote_jar_matches_local("dev-1") is True

    monkeypatch.setattr(
        scrcpyclients,
        "get_remote_server_info",
        lambda _device_id: {"exists": True, "sha256": "other"},
    )
    assert scrcpyclients.remote_jar_matches_local("dev-1") is False


def test_whitebox_prewarm_android_skips_alive_client(monkeypatch):
    import importlib
    import sys

    monkeypatch.setitem(sys.modules, "adbutils", MagicMock())
    monkeypatch.setitem(sys.modules, "av", MagicMock())
    monkeypatch.setitem(sys.modules, "av.codec", MagicMock())
    monkeypatch.setitem(sys.modules, "av.error", MagicMock())
    for key in list(sys.modules):
        if key.startswith("autopilot_platform.runner.remote.android"):
            del sys.modules[key]
    scrcpyclients = importlib.import_module(
        "autopilot_platform.runner.remote.android.scrcpyclients"
    )
    calls: list[str] = []
    monkeypatch.setattr(scrcpyclients, "peek_client", lambda udid: object())
    monkeypatch.setattr(
        scrcpyclients,
        "get_client",
        lambda udid: calls.append(udid) or None,
    )
    from autopilot_platform.runner.remote.prewarm import prewarm_android_scrcpy

    prewarm_android_scrcpy("SERIAL-1")
    assert calls == []


def test_whitebox_prewarm_ios_skips_when_mjpeg_ready(monkeypatch):
    from autopilot_platform.runner.remote.prewarm import prewarm_ios_remote

    class _Ports:
        mjpeg_port = 9100

    class _Rt:
        ports = _Ports()

    monkeypatch.setattr(
        "autopilot_platform.ap.runtime.device_runtime.peek_device_runtime",
        lambda _udid: _Rt(),
    )
    monkeypatch.setattr(
        "autopilot_platform.ap.mobile.ios_bootstrap.mjpeg_alive",
        lambda _port, timeout=0.8: True,
    )
    prewarm_ios_remote("UDID-IOS")


def test_whitebox_prewarm_android_scrcpy_skips_webrtc_stack(monkeypatch):
    """hub.spawn 并行 scrcpy 预热不得抢占 AsyncRunner（不调用 webrtc prewarm）。"""
    webrtc_calls: list[str] = []
    monkeypatch.setattr(
        "autopilot_platform.runner.remote.prewarm.prewarm_webrtc_stack",
        lambda: webrtc_calls.append("webrtc"),
    )
    import importlib
    import sys

    monkeypatch.setitem(sys.modules, "adbutils", MagicMock())
    monkeypatch.setitem(sys.modules, "av", MagicMock())
    monkeypatch.setitem(sys.modules, "av.codec", MagicMock())
    monkeypatch.setitem(sys.modules, "av.error", MagicMock())
    for key in list(sys.modules):
        if key.startswith("autopilot_platform.runner.remote.android"):
            del sys.modules[key]
    scrcpyclients = importlib.import_module(
        "autopilot_platform.runner.remote.android.scrcpyclients"
    )
    monkeypatch.setattr(scrcpyclients, "peek_client", lambda udid: None)
    monkeypatch.setattr(
        scrcpyclients,
        "get_client",
        lambda udid: type("C", (), {"alive": True})(),
    )
    from autopilot_platform.runner.remote.prewarm import prewarm_android_scrcpy

    prewarm_android_scrcpy("SERIAL-WB")
    assert webrtc_calls == []


def test_whitebox_prewarm_webrtc_lightweight_no_handle_offer(monkeypatch):
    """注册后台 webrtc 预热仅 import/codec，不触发 PeerManager.handle_offer。"""
    import autopilot_platform.runner.remote.prewarm as prewarm_mod

    prewarm_mod._webrtc_warmed = False
    handle_calls: list[str] = []

    class _FakeRunner:
        @staticmethod
        def run_sync(coro, _timeout=10.0):
            import asyncio

            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(coro)
            finally:
                loop.close()

    fake_aiortc = MagicMock()
    fake_aiortc.RTCRtpSender.getCapabilities.return_value = {"codecs": []}
    monkeypatch.setitem(sys.modules, "aiortc", fake_aiortc)
    monkeypatch.setattr(
        "autopilot_platform.runner.remote.android.webrtc.async_runner.get_runner",
        lambda: _FakeRunner(),
    )

    import importlib

    pm_mod = importlib.import_module(
        "autopilot_platform.runner.remote.android.webrtc.peer_manager"
    )
    original_handle = pm_mod.PeerManager.handle_offer

    def _track_handle(self, *args, **kwargs):
        handle_calls.append("handle_offer")
        return original_handle(self, *args, **kwargs)

    monkeypatch.setattr(pm_mod.PeerManager, "handle_offer", _track_handle)

    prewarm_mod.prewarm_webrtc_stack()
    assert handle_calls == []
    assert prewarm_mod.webrtc_stack_ready() is True
    prewarm_mod._webrtc_warmed = False


# ---------------------------------------------------------------------------
# 旁观收口：信令隔离 / 帧游标 / Hub 单播 / viewer 无控制 DC / 交权事件
# ---------------------------------------------------------------------------


class _SignalingRow:
    signaling_json = "{}"


def test_whitebox_signaling_dequeue_isolates_browser_participant():
    from autopilot_platform.platform.core.models import DeviceRemoteSessionRow
    from autopilot_platform.platform.services.remote import sessions as remote_svc

    row = cast(DeviceRemoteSessionRow, _SignalingRow())
    remote_svc._enqueue(
        row,
        for_role="browser",
        message={"type": "answer", "sdp": "owner", "participant_id": "p-owner"},
    )
    remote_svc._enqueue(
        row,
        for_role="browser",
        message={"type": "answer", "sdp": "viewer", "participant_id": "p-view"},
    )
    owner_msgs = remote_svc._dequeue(row, for_role="browser", participant_id="p-owner")
    viewer_msgs = remote_svc._dequeue(row, for_role="browser", participant_id="p-view")
    assert [m.get("sdp") for m in owner_msgs] == ["owner"]
    assert [m.get("sdp") for m in viewer_msgs] == ["viewer"]


def test_whitebox_media_frame_cursor_fans_out_without_steal():
    from autopilot_platform.platform.core.models import DeviceRemoteSessionRow
    from autopilot_platform.platform.services.remote import sessions as remote_svc

    row = cast(DeviceRemoteSessionRow, _SignalingRow())
    remote_svc._media_enqueue(
        row,
        for_role="browser",
        message={"type": "frame", "data_b64": "jpeg-1"},
    )
    first = remote_svc._media_dequeue(row, for_role="browser", consumer_id="p-a")
    second = remote_svc._media_dequeue(row, for_role="browser", consumer_id="p-b")
    replay = remote_svc._media_dequeue(row, for_role="browser", consumer_id="p-a")
    assert [m.get("data_b64") for m in first if m.get("type") == "frame"] == ["jpeg-1"]
    assert [m.get("data_b64") for m in second if m.get("type") == "frame"] == ["jpeg-1"]
    assert not any(m.get("type") == "frame" for m in replay)

    remote_svc._media_enqueue(
        row,
        for_role="browser",
        message={"type": "frame", "data_b64": "jpeg-2"},
    )
    nxt = remote_svc._media_dequeue(row, for_role="browser", consumer_id="p-a")
    assert any(m.get("data_b64") == "jpeg-2" for m in nxt)


def test_whitebox_hub_unicasts_answer_and_lists_browser_pids():
    import asyncio

    from autopilot_platform.platform.services.remote.hub import (
        DeviceRemoteSocketHub,
        RemoteSocket,
    )

    class _WS:
        def __init__(self) -> None:
            self.messages: list[Any] = []

        async def send_json(self, message: dict[str, Any]) -> None:
            self.messages.append(message)

        async def send_bytes(self, payload: bytes) -> None:
            self.messages.append(payload)

    hub = DeviceRemoteSocketHub()
    loop = asyncio.new_event_loop()
    owner_ws = _WS()
    viewer_ws = _WS()
    runner_ws = _WS()
    hub._sessions["sid-hub"] = {
        "o": RemoteSocket(
            websocket=cast(Any, owner_ws),
            role="browser",
            participant_id="p-owner",
            connection_id="o",
            loop=loop,
        ),
        "v": RemoteSocket(
            websocket=cast(Any, viewer_ws),
            role="browser",
            participant_id="p-view",
            connection_id="v",
            loop=loop,
        ),
        "r": RemoteSocket(
            websocket=cast(Any, runner_ws),
            role="runner",
            participant_id="",
            connection_id="r",
            loop=loop,
        ),
    }
    try:
        sent = loop.run_until_complete(
            hub.broadcast(
                "sid-hub",
                {"type": "answer", "sdp": "only-owner"},
                target_role="browser",
                participant_id="p-owner",
            )
        )
        runner_sent = loop.run_until_complete(
            hub.broadcast(
                "sid-hub",
                {"type": "offer", "sdp": "to-runner"},
                target_role="runner",
                participant_id="p-owner",
            )
        )
        bin_sent = loop.run_until_complete(
            hub.broadcast_bytes(
                "sid-hub",
                b"APJFframe",
                target_role="browser",
            )
        )
    finally:
        loop.close()
    assert sent == 1
    assert {"type": "answer", "sdp": "only-owner"} in owner_ws.messages
    assert {"type": "answer", "sdp": "only-owner"} not in viewer_ws.messages
    assert runner_sent == 1
    assert runner_ws.messages == [{"type": "offer", "sdp": "to-runner"}]
    assert bin_sent == 2
    assert b"APJFframe" in owner_ws.messages
    assert b"APJFframe" in viewer_ws.messages
    assert hub.connected_browser_participant_ids("sid-hub") == frozenset(
        {"p-owner", "p-view"}
    )


def test_whitebox_android_viewer_offer_skips_control_channels(monkeypatch):
    from autopilot_platform.runner.remote.android.session import AndroidRemoteSession

    registrations: list[str] = []
    readonly_flags: list[bool] = []

    class FakePeerSession:
        def on_local_ice(self, _cb) -> None:
            return

        @staticmethod
        def on_input_message(_cb) -> None:
            registrations.append("input")

        @staticmethod
        def on_adb_message(_cb) -> None:
            registrations.append("adb")

        def on_closed(self, _cb) -> None:
            return

        @staticmethod
        def on_input_open(_cb) -> None:
            registrations.append("input_open")

        @staticmethod
        def input_channel_ready() -> bool:
            return False

    class FakePM:
        def __init__(self) -> None:
            self._sess = FakePeerSession()

        def get_or_create(self, *_a, **_k) -> FakePeerSession:
            return self._sess

        def get(self, *_a, **_k) -> FakePeerSession:
            return self._sess

        @staticmethod
        def handle_offer(*_a, **kwargs) -> dict[str, str]:
            readonly_flags.append(bool(kwargs.get("readonly")))
            return {"sdp": "v=0", "type": "answer"}

        def attach_video(self, *_a, **_k) -> None:
            return

        def handle_ice(self, *_a, **_k) -> None:
            return

        def close(self, *_a, **_k) -> None:
            return

        def detach_video(self, *_a, **_k) -> None:
            return

        def close_device(self, *_a, **_k) -> None:
            return

    _inject_android_session_deps(
        monkeypatch,
        client=MagicMock(alive=True, control=MagicMock()),
        peer_manager_factory=lambda: FakePM(),
    )
    polls: list[list[dict[str, Any]]] = [
        [
            {
                "type": "offer",
                "sdp": "v=0\r\nviewer-offer",
                "participant_id": "p-view",
                "participant_role": "viewer",
            }
        ],
    ]
    session = AndroidRemoteSession(
        session_id="sess-view-dc",
        udid="UDID-VIEW-DC",
        post_signaling=_noop_signaling,
        poll_signaling=lambda: polls.pop(0) if polls else [],
        poll_media=lambda: [],
        report_status=_noop_report_status,
        post_media=None,
    )
    thread = threading.Thread(target=session._run, daemon=True)
    thread.start()
    deadline = time.time() + 3.0
    while time.time() < deadline and not readonly_flags:
        time.sleep(0.05)
    session.stop()
    thread.join(timeout=2.0)
    assert readonly_flags == [True]
    assert registrations == []


def test_whitebox_kick_viewer_keeps_session_and_notifies_runner(client: TestClient):
    admin = login(client)
    assert (
        client.post(
            "/api/v1/auth/users",
            headers=admin,
            json={"username": "owner-kick", "password": "Owner1234", "duty": "user"},
        ).status_code
        == 200
    )
    owner = login(client, "owner-kick", "Owner1234")
    device_id = register_device(
        client, runner_id="runner-kick-keep", udid="KICK-KEEP-1"
    )
    reserve(client, owner, device_id)
    session = open_remote(client, owner, device_id)
    sid = session["id"]
    joined = client.post(
        f"/api/v1/devices/{device_id}/remote-sessions/join",
        headers=admin,
        json={"role": "viewer", "connection_id": "kick-keep"},
    )
    assert joined.status_code == 200, joined.text
    pid = joined.json()["participant_id"]
    kicked = client.delete(
        f"/api/v1/device-remote-sessions/{sid}/participants/{pid}",
        headers=owner,
    )
    assert kicked.status_code == 200, kicked.text
    live = client.get(f"/api/v1/device-remote-sessions/{sid}", headers=owner)
    assert live.status_code == 200, live.text
    assert live.json()["status"] in ("pending", "ready", "connected")
    assert live.json()["participant_role"] == "controller"
    polled = client.get(
        f"/api/v1/device-remote-sessions/{sid}/signaling-poll",
        headers=TOKEN,
    )
    assert any(
        m.get("type") == "participant.left" and m.get("participant_id") == pid
        for m in polled.json().get("messages") or []
    ), polled.text


def test_whitebox_promote_event_reaches_both_browsers(client: TestClient):
    admin = login(client)
    assert (
        client.post(
            "/api/v1/auth/users",
            headers=admin,
            json={"username": "owner-ev", "password": "Owner1234", "duty": "user"},
        ).status_code
        == 200
    )
    owner = login(client, "owner-ev", "Owner1234")
    device_id = register_device(
        client, runner_id="runner-promote-ev", udid="PROMOTE-EV-1"
    )
    reserve(client, owner, device_id)
    session = open_remote(client, owner, device_id)
    sid = session["id"]
    joined = client.post(
        f"/api/v1/devices/{device_id}/remote-sessions/join",
        headers=admin,
        json={"role": "viewer", "connection_id": "promote-ev"},
    )
    assert joined.status_code == 200, joined.text
    pid_admin = joined.json()["participant_id"]
    with ws_browser_connect(client, sid, session["access_token"]) as owner_ws:
        with ws_browser_connect(client, sid, joined.json()["access_token"]) as admin_ws:
            promoted = client.post(
                f"/api/v1/device-remote-sessions/{sid}/participants/{pid_admin}/promote",
                headers=owner,
            )
            assert promoted.status_code == 200, promoted.text
            owner_ev = owner_ws.receive_json()
            admin_ev = admin_ws.receive_json()
    assert owner_ev.get("name") == "control.transferred"
    assert admin_ev.get("name") == "control.transferred"
    assert owner_ev.get("payload", {}).get("controller_participant_id") == pid_admin
    assert admin_ev.get("payload", {}).get("controller_participant_id") == pid_admin

