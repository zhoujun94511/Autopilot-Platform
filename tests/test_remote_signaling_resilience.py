"""远控信令容错白盒：HTTP/WS 双通道、Runner WS 误路由、offer 队列兜底。"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient

from autopilot_platform.core.constants import DEFAULT_API_TOKEN
from autopilot_platform.platform.app import create_app
from autopilot_platform.platform.core.db import reset_engine
from autopilot_platform.runner.remote.shared.channels import RemoteChannels
from autopilot_platform.runner.remote.shared.ws_client import RunnerRemoteWebSocket

TOKEN = {"X-API-Token": DEFAULT_API_TOKEN}


def _ws_enqueue(ws: RunnerRemoteWebSocket, channel: str, message: dict[str, Any]) -> None:
    getattr(ws, "_enqueue")(channel, message)


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


def _login(
    client: TestClient, username: str = "admin", password: str = "admin"
) -> dict:
    out = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    assert out.status_code == 200, out.text
    return {"Authorization": f"Bearer {out.json()['access_token']}"}


def _register_and_open_session(client: TestClient, *, runner_id: str = "runner-res-1") -> tuple[dict, str]:
    assert (
        client.post(
            "/api/v1/runners/register",
            headers=TOKEN,
            json={
                "runner_id": runner_id,
                "hostname": "res-host",
                "version": "0.2.0",
                "capabilities": ["android", "android-remote"],
            },
        ).status_code
        == 200
    )
    udid = "ANDROID-RES-1"
    assert (
        client.post(
            "/api/v1/runners/heartbeat",
            headers=TOKEN,
            json={
                "runner_id": runner_id,
                "capabilities": ["android", "android-remote"],
                "host_backends": ["android-appium"],
                "inventory": [
                    {
                        "udid": udid,
                        "platform": "android",
                        "name": "Res Device",
                        "model": "Res",
                        "os_version": "14",
                        "state": "ready",
                        "backends": ["android-appium"],
                    }
                ],
                "devices": [
                    {
                        "udid": udid,
                        "platform": "android",
                        "name": "Res Device",
                        "model": "Res",
                        "os_version": "14",
                        "state": "ready",
                        "backends": ["android-appium"],
                    }
                ],
            },
        ).status_code
        == 200
    )
    auth = _login(client)
    listed = client.get("/api/v1/devices", headers=auth)
    device_id = str(next(i["id"] for i in listed.json()["items"] if i["udid"] == udid))
    assert (
        client.post(
            f"/api/v1/devices/{device_id}/reservations",
            headers=auth,
            json={"duration_minutes": 30, "reason": "[远控预留]res"},
        ).status_code
        in (200, 201)
    )
    opened = client.post(
        f"/api/v1/devices/{device_id}/remote-sessions",
        headers=auth,
        json={"duration_minutes": 30},
    )
    assert opened.status_code in (200, 201), opened.text
    return auth, str(opened.json()["id"])


# ---------------------------------------------------------------------------
# Runner WS 客户端：裸 SDP 帧路由
# ---------------------------------------------------------------------------


def test_ws_client_routes_bare_offer_to_signaling_queue():
    ws = RunnerRemoteWebSocket("http://127.0.0.1:8000", "tok", "sess-ws-1")
    _ws_enqueue(ws, "", {"type": "offer", "sdp": "v=0\r\nbare-offer", "from_role": "browser"})
    msgs = ws.drain_signaling()
    assert len(msgs) == 1
    assert msgs[0]["type"] == "offer"
    assert "bare-offer" in msgs[0]["sdp"]


def test_ws_client_routes_signaling_envelope_payload():
    ws = RunnerRemoteWebSocket("http://127.0.0.1:8000", "tok", "sess-ws-2")
    _ws_enqueue(
        ws,
        "",
        {
            "channel": "signaling",
            "type": "event",
            "name": "answer",
            "payload": {"type": "answer", "sdp": "v=0\r\nanswer", "from_role": "runner"},
        },
    )
    msgs = ws.drain_signaling()
    assert len(msgs) == 1
    assert msgs[0]["type"] == "answer"


def test_ws_client_drains_participant_left_from_event_envelope():
    ws = RunnerRemoteWebSocket("http://127.0.0.1:8000", "tok", "sess-ws-left")
    _ws_enqueue(
        ws,
        "",
        {
            "channel": "event",
            "type": "event",
            "name": "participant.left",
            "participant_id": "p-view",
            "payload": {"type": "participant.left", "participant_id": "p-view"},
        },
    )
    msgs = ws.drain_signaling()
    assert any(m.get("type") == "participant.left" and m.get("participant_id") == "p-view" for m in msgs)


def test_ws_client_send_drop_if_busy_skips_without_blocking():
    ws = RunnerRemoteWebSocket("http://127.0.0.1:8000", "tok", "sess-ws-busy")
    sock = MagicMock()
    setattr(ws, "_socket", sock)
    getattr(ws, "_connected").set()
    send_guard = getattr(ws, "_send_guard")
    send_guard.acquire()
    try:
        assert ws.send("media", "frame", {"type": "frame", "data_b64": "xx"}, drop_if_busy=True) is False
        assert ws.send_binary(b"APJFold", drop_if_busy=True) is True
        assert ws.send_binary(b"APJFnew", drop_if_busy=True) is True
        assert getattr(ws, "_pending_binary") == b"APJFnew"
        sock.send.assert_not_called()
    finally:
        send_guard.release()
    assert ws.send("media", "input", {"t": "home"}) is True
    assert sock.send.call_args_list[-1].args[0] == b"APJFnew"


def test_ws_client_reconnects_after_recv_exception(monkeypatch):
    """Platform 关连接时 ConnectionClosedOK 不得杀死 Runner WS 线程。"""
    ws = RunnerRemoteWebSocket("http://127.0.0.1:8000", "tok", "sess-ws-reclose")
    calls = {"n": 0}

    class _Closed(Exception):
        pass

    class _Sock:
        def recv(self, timeout=0.5):
            raise _Closed("closed")

        @staticmethod
        def close():
            return None

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

    def _connect(*_args, **_kwargs):
        calls["n"] += 1
        if calls["n"] >= 3:
            getattr(ws, "_stop").set()
        return _Sock()

    monkeypatch.setattr("websockets.sync.client.connect", _connect)
    stop_event = getattr(ws, "_stop")
    monkeypatch.setattr(stop_event, "wait", lambda _timeout=None: True)
    getattr(ws, "_run")()
    assert calls["n"] >= 2


def test_remote_channels_drops_busy_frame_without_http_fallback():
    client = MagicMock()
    channels = _channels_with_mock_ws(client, "sess-ch-frame", connected=True)
    ws = getattr(channels, "_ws")
    assert ws is not None
    ws.send.return_value = False
    channels.post_media(
        {"type": "frame", "jpeg": b"\xff\xd8\xff\xd9", "width": 1, "height": 1}
    )
    client.post_remote_media.assert_not_called()
    ws.send_binary.assert_called_once()
    ws.send.assert_not_called()

    ws.send_binary.reset_mock()
    channels.post_media({"type": "input", "payload": {"t": "home"}})
    client.post_remote_media.assert_called_once()


def test_remote_channels_skips_http_media_poll_when_ws_connected():
    client = MagicMock()
    channels = _channels_with_mock_ws(client, "sess-ch-poll", connected=True)
    ws = getattr(channels, "_ws")
    assert ws is not None
    ws.drain.return_value = []
    assert channels.poll_media() == []
    client.poll_remote_media.assert_not_called()


def test_remote_channels_http_media_poll_when_ws_down():
    client = MagicMock()
    client.poll_remote_media.return_value = {"messages": [{"type": "input"}]}
    channels = _channels_with_mock_ws(client, "sess-ch-poll-http", connected=False)
    ws = getattr(channels, "_ws")
    assert ws is not None
    ws.drain.return_value = []
    msgs = channels.poll_media()
    assert msgs == [{"type": "input"}]
    client.poll_remote_media.assert_called_once_with("sess-ch-poll-http")


def test_ws_client_drain_signaling_recovers_event_queue_misroute():
    ws = RunnerRemoteWebSocket("http://127.0.0.1:8000", "tok", "sess-ws-3")
    # 旧 bug：HTTP hub.publish 裸 payload 会进 event 队列
    getattr(ws, "_queues")["event"].put_nowait({"type": "ice", "candidate": {"candidate": "c1"}})
    msgs = ws.drain_signaling()
    assert any(m.get("type") == "ice" for m in msgs)


# ---------------------------------------------------------------------------
# RemoteChannels：WS + HTTP 双读 / WS 发送失败回退 HTTP
# ---------------------------------------------------------------------------


def _channels_with_mock_ws(
    client: MagicMock,
    session_id: str,
    *,
    connected: bool,
    ws_messages: list[dict[str, Any]] | None = None,
) -> RemoteChannels:
    mock_ws = MagicMock()
    mock_ws.connected = connected
    mock_ws.drain_signaling.return_value = list(ws_messages or [])
    mock_ws.send.return_value = False
    mock_ws.send_binary.return_value = False
    channels = RemoteChannels.__new__(RemoteChannels)
    setattr(channels, "_client", client)
    channels.session_id = session_id
    setattr(channels, "_ws", mock_ws)
    return channels


def test_remote_channels_poll_merges_http_when_ws_disconnected():
    client = MagicMock()
    client.poll_remote_signaling.return_value = {
        "messages": [{"type": "offer", "sdp": "v=0\r\nhttp"}],
    }
    channels = _channels_with_mock_ws(client, "sess-ch-1", connected=False)

    msgs = channels.poll_signaling()
    assert any("http" in str(m.get("sdp")) for m in msgs)
    client.poll_remote_signaling.assert_called_once_with("sess-ch-1")


def test_remote_channels_poll_drains_ws_queue_during_reconnect():
    client = MagicMock()
    client.poll_remote_signaling.return_value = {"messages": []}
    channels = _channels_with_mock_ws(
        client,
        "sess-ch-2",
        connected=False,
        ws_messages=[{"type": "offer", "sdp": "v=0\r\nws-local"}],
    )

    msgs = channels.poll_signaling()
    assert any("ws-local" in str(m.get("sdp")) for m in msgs)


def test_remote_channels_post_signaling_falls_back_to_http_on_ws_send_fail():
    client = MagicMock()
    channels = _channels_with_mock_ws(client, "sess-ch-3", connected=True)
    ws = getattr(channels, "_ws")
    assert ws is not None
    ws.send.return_value = False

    channels.post_signaling("answer", {"type": "answer", "sdp": "v=0\r\n"})
    client.post_remote_signaling.assert_called_once_with(
        "sess-ch-3",
        "answer",
        {"type": "answer", "sdp": "v=0\r\n"},
    )


# ---------------------------------------------------------------------------
# Platform：Runner WS 在线时 HTTP offer 仍须入队（用户报告场景）
# ---------------------------------------------------------------------------


def test_http_offer_delivered_via_ws_when_runner_ws_connected(client: TestClient):
    """Runner WS 在线：offer 走 WS envelope，不应依赖 DB poll。"""
    auth, sid = _register_and_open_session(client, runner_id="runner-res-ws")
    runner_url = f"/api/v1/device-remote-sessions/{sid}/ws?role=runner"

    with client.websocket_connect(runner_url, headers=TOKEN) as runner_ws:
        assert runner_ws.receive_json()["name"] == "transport.ready"

        posted = client.post(
            f"/api/v1/device-remote-sessions/{sid}/offer",
            headers=auth,
            json={"type": "offer", "sdp": "v=0\r\nhttp-with-runner-ws", "from_role": "browser"},
        )
        assert posted.status_code == 200, posted.text

        relayed = runner_ws.receive_json()
        assert relayed.get("channel") == "signaling"
        payload = relayed.get("payload") or {}
        assert payload.get("type") == "offer"
        assert "http-with-runner-ws" in str(payload.get("sdp"))

        polled = client.get(
            f"/api/v1/device-remote-sessions/{sid}/signaling-poll",
            headers=TOKEN,
        )
        assert polled.status_code == 200, polled.text
        assert polled.json().get("messages") == []


def test_http_offer_enqueued_when_runner_ws_offline(client: TestClient):
    """Runner 无 WS：offer 入 DB 队列，poll 可消费。"""
    auth, sid = _register_and_open_session(client, runner_id="runner-res-offline")

    posted = client.post(
        f"/api/v1/device-remote-sessions/{sid}/offer",
        headers=auth,
        json={"type": "offer", "sdp": "v=0\r\nrunner-offline", "from_role": "browser"},
    )
    assert posted.status_code == 200, posted.text

    polled = client.get(
        f"/api/v1/device-remote-sessions/{sid}/signaling-poll",
        headers=TOKEN,
    )
    assert polled.status_code == 200, polled.text
    msgs = polled.json().get("messages") or []
    assert any(
        m.get("type") == "offer" and "runner-offline" in str(m.get("sdp")) for m in msgs
    ), polled.text


def test_browser_poll_gets_answer_after_runner_http_post(client: TestClient):
    auth, sid = _register_and_open_session(client, runner_id="runner-res-ans")
    client.post(
        f"/api/v1/device-remote-sessions/{sid}/offer",
        headers=auth,
        json={"type": "offer", "sdp": "v=0\r\n", "from_role": "browser"},
    )
    posted = client.post(
        f"/api/v1/device-remote-sessions/{sid}/answer",
        headers=TOKEN,
        json={"type": "answer", "sdp": "v=0\r\nanswer-sdp", "from_role": "runner"},
    )
    assert posted.status_code == 200, posted.text

    polled = client.get(
        f"/api/v1/device-remote-sessions/{sid}/signaling-poll",
        headers=auth,
    )
    assert polled.status_code == 200, polled.text
    msgs = polled.json().get("messages") or []
    assert any(m.get("type") == "answer" and "answer-sdp" in str(m.get("sdp")) for m in msgs)


def test_double_offer_poll_dequeues_both_for_runner(client: TestClient):
    """offer 重试时 Runner 应能依次消费多条 offer。"""
    auth, sid = _register_and_open_session(client, runner_id="runner-res-retry")
    for i in range(2):
        r = client.post(
            f"/api/v1/device-remote-sessions/{sid}/offer",
            headers=auth,
            json={"type": "offer", "sdp": f"v=0\r\nretry-{i}", "from_role": "browser"},
        )
        assert r.status_code == 200, r.text

    polled = client.get(
        f"/api/v1/device-remote-sessions/{sid}/signaling-poll",
        headers=TOKEN,
    )
    msgs = polled.json().get("messages") or []
    sdps = [str(m.get("sdp") or "") for m in msgs if m.get("type") == "offer"]
    assert len(sdps) == 2
    assert any("retry-0" in s for s in sdps)
    assert any("retry-1" in s for s in sdps)


def test_ws_client_copies_envelope_participant_id_into_payload():
    ws = RunnerRemoteWebSocket("http://127.0.0.1:8000", "tok", "sess-ws-pid")
    _ws_enqueue(
        ws,
        "",
        {
            "channel": "signaling",
            "type": "event",
            "name": "answer",
            "participant_id": "peer-viewer",
            "payload": {"type": "answer", "sdp": "v=0\r\nans", "from_role": "runner"},
        },
    )
    msgs = ws.drain_signaling()
    assert len(msgs) == 1
    assert msgs[0]["participant_id"] == "peer-viewer"


def test_remote_channels_post_signaling_forwards_participant_id():
    client = MagicMock()
    channels = _channels_with_mock_ws(client, "sess-ch-pid", connected=True)
    ws = getattr(channels, "_ws")
    assert ws is not None
    ws.send.return_value = True
    body = {"type": "answer", "sdp": "v=0\r\n", "participant_id": "peer-1"}
    channels.post_signaling("answer", body)
    ws.send.assert_called_once_with(
        "signaling",
        "answer",
        body,
        participant_id="peer-1",
    )
    client.post_remote_signaling.assert_not_called()


def _register_android_device(
    client: TestClient, *, runner_id: str, udid: str
) -> str:
    assert (
        client.post(
            "/api/v1/runners/register",
            headers=TOKEN,
            json={
                "runner_id": runner_id,
                "hostname": "res-host",
                "version": "0.2.0",
                "capabilities": ["android", "android-remote"],
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
                "host_backends": ["android-appium"],
                "inventory": [
                    {
                        "udid": udid,
                        "platform": "android",
                        "name": "Res Device",
                        "model": "Res",
                        "os_version": "14",
                        "state": "ready",
                        "backends": ["android-appium"],
                    }
                ],
                "devices": [
                    {
                        "udid": udid,
                        "platform": "android",
                        "name": "Res Device",
                        "model": "Res",
                        "os_version": "14",
                        "state": "ready",
                        "backends": ["android-appium"],
                    }
                ],
            },
        ).status_code
        == 200
    )
    listed = client.get("/api/v1/devices", headers=_login(client))
    return str(next(i["id"] for i in listed.json()["items"] if i["udid"] == udid))


def _open_session_with_occupier(
    client: TestClient, *, runner_id: str, udid: str, owner_username: str
) -> tuple[dict, dict, str, str, str]:
    admin = _login(client)
    created = client.post(
        "/api/v1/auth/users",
        headers=admin,
        json={"username": owner_username, "password": "Owner1234", "duty": "user"},
    )
    assert created.status_code == 200, created.text
    owner = _login(client, owner_username, "Owner1234")
    device_id = _register_android_device(client, runner_id=runner_id, udid=udid)
    reserved = client.post(
        f"/api/v1/devices/{device_id}/reservations",
        headers=owner,
        json={"duration_minutes": 30, "reason": "[远控预留]owner"},
    )
    assert reserved.status_code in (200, 201), reserved.text
    opened = client.post(
        f"/api/v1/devices/{device_id}/remote-sessions",
        headers=owner,
        json={"duration_minutes": 30},
    )
    assert opened.status_code in (200, 201), opened.text
    body = opened.json()
    return owner, admin, device_id, str(body["id"]), str(body["participant_id"])


def test_http_offer_stamps_viewer_role_and_ignores_spoofed_pid(client: TestClient):
    owner, admin, device_id, sid, owner_pid = _open_session_with_occupier(
        client,
        runner_id="runner-res-stamp",
        udid="ANDROID-RES-STAMP",
        owner_username="owner-sig-stamp",
    )
    joined = client.post(
        f"/api/v1/devices/{device_id}/remote-sessions/join",
        headers=admin,
        json={"role": "viewer", "connection_id": "viewer-stamp"},
    )
    assert joined.status_code == 200, joined.text
    viewer_pid = str(joined.json()["participant_id"])
    assert viewer_pid != owner_pid

    posted = client.post(
        f"/api/v1/device-remote-sessions/{sid}/offer",
        headers=admin,
        json={
            "type": "offer",
            "sdp": "v=0\r\nview-offer",
            "from_role": "browser",
            "participant_id": owner_pid,
            "participant_role": "controller",
        },
    )
    assert posted.status_code == 200, posted.text

    polled = client.get(
        f"/api/v1/device-remote-sessions/{sid}/signaling-poll",
        headers=TOKEN,
    )
    assert polled.status_code == 200, polled.text
    msgs = polled.json().get("messages") or []
    offer = next(m for m in msgs if "view-offer" in str(m.get("sdp")))
    assert offer["participant_id"] == viewer_pid
    assert offer["participant_role"] == "viewer"


def test_browser_poll_isolates_answer_by_participant(client: TestClient):
    owner, admin, device_id, sid, owner_pid = _open_session_with_occupier(
        client,
        runner_id="runner-res-iso",
        udid="ANDROID-RES-ISO",
        owner_username="owner-sig-iso",
    )
    joined = client.post(
        f"/api/v1/devices/{device_id}/remote-sessions/join",
        headers=admin,
        json={"role": "viewer", "connection_id": "viewer-iso"},
    )
    assert joined.status_code == 200, joined.text
    viewer_pid = str(joined.json()["participant_id"])

    for pid, sdp in (
        (owner_pid, "v=0\r\nowner-answer"),
        (viewer_pid, "v=0\r\nviewer-answer"),
    ):
        posted = client.post(
            f"/api/v1/device-remote-sessions/{sid}/answer",
            headers=TOKEN,
            json={
                "type": "answer",
                "sdp": sdp,
                "from_role": "runner",
                "participant_id": pid,
            },
        )
        assert posted.status_code == 200, posted.text

    owner_msgs = client.get(
        f"/api/v1/device-remote-sessions/{sid}/signaling-poll",
        headers=owner,
    )
    assert owner_msgs.status_code == 200, owner_msgs.text
    owner_sdps = [str(m.get("sdp") or "") for m in owner_msgs.json().get("messages") or []]
    assert any("owner-answer" in s for s in owner_sdps)
    assert not any("viewer-answer" in s for s in owner_sdps)

    viewer_msgs = client.get(
        f"/api/v1/device-remote-sessions/{sid}/signaling-poll",
        headers=admin,
    )
    assert viewer_msgs.status_code == 200, viewer_msgs.text
    viewer_sdps = [str(m.get("sdp") or "") for m in viewer_msgs.json().get("messages") or []]
    assert any("viewer-answer" in s for s in viewer_sdps)
    assert not any("owner-answer" in s for s in viewer_sdps)
