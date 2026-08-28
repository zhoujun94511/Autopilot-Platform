"""远控设备日志：独立 SSE / Runner HTTP 投递，不与画面 media 队列混用。"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient

from autopilot_platform.core.constants import DEFAULT_API_TOKEN
from autopilot_platform.platform.app import create_app
from autopilot_platform.platform.core.db import reset_engine
from autopilot_platform.platform.core.security import decode_access_token
from tests.test_remote_link_whitebox import (
    login,
    open_remote,
    register_device,
    reserve,
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


def test_android_logcat_filterspec():
    from autopilot_platform.runner.remote.android.device_log import build_filterspec

    assert build_filterspec("I") == "*:I"
    assert build_filterspec("W", "MyTag") == "MyTag:W *:S"
    assert build_filterspec("nope") == "*:I"


def test_device_log_bus_replay_and_wait():
    from autopilot_platform.platform.services.remote import device_log_bus

    sid = "sess-bus-1"
    device_log_bus.drop(sid)
    device_log_bus.append(sid, ["line-a", "line-b"])
    cursor, snapshot = device_log_bus.subscribe(sid)
    assert snapshot[-2:] == ["line-a", "line-b"]
    device_log_bus.append(sid, ["line-c"])
    nxt, new = device_log_bus.wait_lines(sid, cursor, 0.2)
    assert "line-c" in new
    assert nxt > cursor
    assert device_log_bus.unsubscribe(sid) == 0
    device_log_bus.drop(sid)


def test_device_log_stream_token_and_sse_isolated_from_media(client: TestClient):
    auth = login(client)
    device_id = register_device(client, runner_id="runner-log-1", udid="ANDROID-LOG-1")
    reserve(client, auth, device_id)
    session = open_remote(client, auth, device_id)
    sid = session["id"]
    user_jwt = auth["Authorization"].split(" ", 1)[1]

    denied = client.get(
        f"/api/v1/device-remote-sessions/{sid}/logs/stream?access_token={user_jwt}"
    )
    assert denied.status_code == 401

    token_res = client.post(
        f"/api/v1/device-remote-sessions/{sid}/logs/stream-token",
        headers=auth,
    )
    assert token_res.status_code == 200, token_res.text
    body = token_res.json()
    assert body["token_type"] == "device_log_stream"
    payload = decode_access_token(body["access_token"])
    assert payload["typ"] == "device_log_stream"
    assert payload["session_id"] == sid

    posted = client.post(
        f"/api/v1/device-remote-sessions/{sid}/logs",
        headers=TOKEN,
        json={"lines": ["I/foo: hello-sse"]},
    )
    assert posted.status_code == 200, posted.text
    assert posted.json()["accepted"] == 1

    media = client.get(
        f"/api/v1/device-remote-sessions/{sid}/media-poll",
        headers=TOKEN,
    )
    assert media.status_code == 200, media.text
    assert not any(
        "hello-sse" in str(item)
        for item in media.json().get("messages") or []
    )

    from autopilot_platform.platform.services.remote import device_log_bus

    cursor, snapshot = device_log_bus.subscribe(sid)
    assert "I/foo: hello-sse" in snapshot
    device_log_bus.unsubscribe(sid)

    started = client.post(
        f"/api/v1/device-remote-sessions/{sid}/commands",
        headers=auth,
        json={"name": "log.start", "payload": {"level": "I"}},
    )
    assert started.status_code == 200, started.text
    start_msgs = client.get(
        f"/api/v1/device-remote-sessions/{sid}/media-poll",
        headers=TOKEN,
    ).json()["messages"]
    assert any(
        item.get("t") == "log.start" or item.get("name") == "log.start"
        for item in start_msgs
    )


def test_device_log_clear_controller_only_and_job_token_rejected(client: TestClient):
    from autopilot_platform.platform.core.security import create_stream_token

    auth = login(client)
    device_id = register_device(client, runner_id="runner-log-2", udid="ANDROID-LOG-2")
    reserve(client, auth, device_id)
    session = open_remote(client, auth, device_id)
    sid = session["id"]

    cleared = client.post(
        f"/api/v1/device-remote-sessions/{sid}/logs/clear",
        headers=auth,
    )
    assert cleared.status_code == 200, cleared.text

    job_tok = create_stream_token(
        sub="u1", role="admin", username="admin", job_id="job-x"
    )
    mixed = client.get(
        f"/api/v1/device-remote-sessions/{sid}/logs/stream?access_token={job_tok}"
    )
    assert mixed.status_code in (401, 403)

    ingest_as_user = client.post(
        f"/api/v1/device-remote-sessions/{sid}/logs",
        headers=auth,
        json={"lines": ["nope"]},
    )
    assert ingest_as_user.status_code == 403
