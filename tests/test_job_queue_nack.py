"""任务池：同设备/web 排队，nack 退回 pending，不标 FAILED。"""

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
    db_path = tmp_path / "mc_job_queue.db"
    url = f"sqlite:///{db_path.as_posix()}"
    monkeypatch.setenv("MC_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("MC_APP_BUILDS_DIR", str(tmp_path / "app_builds"))
    monkeypatch.setenv("MC_ADMIN_USER", "admin")
    monkeypatch.setenv("MC_ADMIN_PASSWORD", "admin")
    monkeypatch.setenv("MC_SCHEDULE_ENABLED", "0")
    monkeypatch.setenv("MC_RUNTIME_CONFIG", str(tmp_path / "mc_runtime_config.json"))
    monkeypatch.setenv("MC_JOB_LOGS_DIR", str(tmp_path / "job_logs"))
    reset_engine()
    from autopilot_platform.platform.ops.runtime_config import reload_runtime_config

    reload_runtime_config()
    app = create_app(database_url=url)
    with TestClient(app) as c:
        yield c
    reset_engine()
    reload_runtime_config()


def _reg(client: TestClient, rid: str, caps: list[str]) -> None:
    r = client.post(
        "/api/v1/runners/register",
        headers=TOKEN,
        json={"runner_id": rid, "hostname": rid, "capabilities": caps},
    )
    assert r.status_code == 200, r.text


def _hb(client: TestClient, rid: str, devices: list[dict] | None = None) -> None:
    inventory = devices or []
    r = client.post(
        "/api/v1/runners/heartbeat",
        headers=TOKEN,
        json={"runner_id": rid, "inventory": inventory, "devices": inventory},
    )
    assert r.status_code == 200, r.text


def _job(
    client: TestClient,
    name: str,
    *,
    platform: str,
    udids: list[str] | None = None,
) -> str:
    body: dict = {
        "project_id": "p-mc",
        "name": name,
        "project_dir": "/tmp/suite",
        "platform": platform,
    }
    if udids is not None:
        body["device_udids"] = udids
    r = client.post("/api/v1/jobs", headers=TOKEN, json=body)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_occupy_busy_device_leaves_second_job_pending(client: TestClient):
    rid = "q-android"
    udid = "phone-q"
    _reg(client, rid, ["android"])
    _hb(client, rid, [{"udid": udid, "platform": "android", "name": "d"}])
    j1 = _job(client, "first", platform="android", udids=[udid])
    j2 = _job(client, "second", platform="android", udids=[udid])
    c1 = client.post(f"/api/v1/jobs/claim?runner_id={rid}", headers=TOKEN)
    assert c1.json()["id"] == j1
    c2 = client.post(f"/api/v1/jobs/claim?runner_id={rid}", headers=TOKEN)
    assert c2.json() is None
    assert client.get(f"/api/v1/jobs/{j2}", headers=TOKEN).json()["status"] == "pending"


def test_claim_skips_second_web_while_first_claimed(client: TestClient):
    rid = "q-web"
    _reg(client, rid, ["web", "android"])
    _hb(client, rid, [{"udid": "phone-w", "platform": "android", "name": "d"}])
    w1 = _job(client, "web-a", platform="web")
    w2 = _job(client, "web-b", platform="web")
    c1 = client.post(f"/api/v1/jobs/claim?runner_id={rid}", headers=TOKEN)
    assert c1.json()["id"] == w1
    c2 = client.post(f"/api/v1/jobs/claim?runner_id={rid}", headers=TOKEN)
    assert c2.json() is None
    assert client.get(f"/api/v1/jobs/{w2}", headers=TOKEN).json()["status"] == "pending"
    android = _job(client, "and", platform="android", udids=["phone-w"])
    c3 = client.post(f"/api/v1/jobs/claim?runner_id={rid}", headers=TOKEN)
    assert c3.json()["id"] == android


def test_nack_returns_claimed_to_pending_and_clears_busy(client: TestClient):
    rid = "q-nack"
    udid = "phone-nack"
    _reg(client, rid, ["android"])
    _hb(client, rid, [{"udid": udid, "platform": "android", "name": "d"}])
    jid = _job(client, "hold", platform="android", udids=[udid])
    claimed = client.post(f"/api/v1/jobs/claim?runner_id={rid}", headers=TOKEN).json()
    assert claimed["id"] == jid
    inventory = client.get(
        f"/api/v1/runners/{rid}/device-inventory", headers=TOKEN
    ).json()
    occupied = next(d for d in inventory["devices"] if d["udid"] == udid)
    assert occupied["occupancy_kind"] == "job"
    assert occupied["occupancy_reference"] == jid
    assert occupied["occupancy_start_at"]
    devices = page_items(client.get("/api/v1/devices", headers=TOKEN).json())
    assert any(d["udid"] == udid and d.get("busy_job_id") == jid for d in devices)

    nack = client.post(
        f"/api/v1/jobs/{jid}/nack?runner_id={rid}&reason=slot-busy",
        headers=TOKEN,
    )
    assert nack.status_code == 200, nack.text
    body = nack.json()
    assert body["status"] == "pending"
    assert not body.get("runner_id")
    devices = page_items(client.get("/api/v1/devices", headers=TOKEN).json())
    assert any(d["udid"] == udid and not d.get("busy") for d in devices)

    again = client.post(f"/api/v1/jobs/claim?runner_id={rid}", headers=TOKEN).json()
    assert again["id"] == jid


def test_nack_rejects_running_job(client: TestClient):
    rid = "q-nack-run"
    udid = "phone-run"
    _reg(client, rid, ["android"])
    _hb(client, rid, [{"udid": udid, "platform": "android", "name": "d"}])
    jid = _job(client, "running", platform="android", udids=[udid])
    client.post(f"/api/v1/jobs/claim?runner_id={rid}", headers=TOKEN)
    running = client.post(f"/api/v1/jobs/{jid}/running?runner_id={rid}", headers=TOKEN)
    assert running.status_code == 200
    nack = client.post(f"/api/v1/jobs/{jid}/nack?runner_id={rid}", headers=TOKEN)
    assert nack.status_code == 409
    assert client.get(f"/api/v1/jobs/{jid}", headers=TOKEN).json()["status"] == "running"
    devices = page_items(client.get("/api/v1/devices", headers=TOKEN).json())
    assert any(d["udid"] == udid and d.get("busy_job_id") == jid for d in devices)


def _claim(client: TestClient, rid: str):
    return client.post(f"/api/v1/jobs/claim?runner_id={rid}", headers=TOKEN)


def _complete(client: TestClient, job_id: str, rid: str, status: str = "succeeded"):
    r = client.post(
        f"/api/v1/jobs/{job_id}/complete?runner_id={rid}",
        headers=TOKEN,
        json={"status": status},
    )
    assert r.status_code == 200, r.text
    return r.json()


def _busy_job(client: TestClient, udid: str) -> str | None:
    for d in page_items(client.get("/api/v1/devices", headers=TOKEN).json()):
        if d["udid"] == udid:
            return d.get("busy_job_id") or None
    raise AssertionError(f"device not found: {udid}")


def test_android_and_ios_jobs_are_claimed_in_parallel(client: TestClient):
    """移动端会领任务：不相交 Android/iOS 可同时 claimed。"""
    rid = "q-mobile"
    _reg(client, rid, ["android", "ios"])
    _hb(
        client,
        rid,
        [
            {"udid": "phone-a", "platform": "android", "name": "a"},
            {"udid": "phone-i", "platform": "ios", "name": "i"},
        ],
    )
    ja = _job(client, "and", platform="android", udids=["phone-a"])
    ji = _job(client, "ios", platform="ios", udids=["phone-i"])
    c1 = _claim(client, rid).json()
    c2 = _claim(client, rid).json()
    got = {c1["id"], c2["id"]}
    assert got == {ja, ji}
    assert _busy_job(client, "phone-a") == ja
    assert _busy_job(client, "phone-i") == ji


def test_web_only_runner_does_not_claim_android(client: TestClient):
    web_rid = "q-web-only"
    and_rid = "q-and-only"
    _reg(client, web_rid, ["web"])
    _reg(client, and_rid, ["android"])
    _hb(client, web_rid, [])
    _hb(client, and_rid, [{"udid": "phone-only", "platform": "android", "name": "d"}])
    jid = _job(client, "and", platform="android", udids=["phone-only"])
    assert _claim(client, web_rid).json() is None
    got = _claim(client, and_rid).json()
    assert got["id"] == jid
    assert got["platform"] == "android"


def test_same_android_udid_claimed_after_complete_succeeded(client: TestClient):
    rid = "q-serial-ok"
    udid = "phone-serial"
    _reg(client, rid, ["android"])
    _hb(client, rid, [{"udid": udid, "platform": "android", "name": "d"}])
    j1 = _job(client, "one", platform="android", udids=[udid])
    j2 = _job(client, "two", platform="android", udids=[udid])
    assert _claim(client, rid).json()["id"] == j1
    assert _claim(client, rid).json() is None
    _complete(client, j1, rid, "succeeded")
    assert _busy_job(client, udid) is None
    got = _claim(client, rid).json()
    assert got["id"] == j2
    assert _busy_job(client, udid) == j2


def test_same_android_udid_claimed_after_complete_failed(client: TestClient):
    rid = "q-serial-fail"
    udid = "phone-fail"
    _reg(client, rid, ["android"])
    _hb(client, rid, [{"udid": udid, "platform": "android", "name": "d"}])
    j1 = _job(client, "one", platform="android", udids=[udid])
    j2 = _job(client, "two", platform="android", udids=[udid])
    assert _claim(client, rid).json()["id"] == j1
    _complete(client, j1, rid, "failed")
    assert _busy_job(client, udid) is None
    assert _claim(client, rid).json()["id"] == j2
    assert _busy_job(client, udid) == j2


def test_ios_same_udid_claimed_after_complete(client: TestClient):
    rid = "q-ios-serial"
    udid = "ios-serial"
    _reg(client, rid, ["ios"])
    _hb(client, rid, [{"udid": udid, "platform": "ios", "name": "iphone"}])
    j1 = _job(client, "ios-1", platform="ios", udids=[udid])
    j2 = _job(client, "ios-2", platform="ios", udids=[udid])
    assert _claim(client, rid).json()["id"] == j1
    assert _claim(client, rid).json() is None
    _complete(client, j1, rid)
    assert _busy_job(client, udid) is None
    assert _claim(client, rid).json()["id"] == j2


def test_web_running_still_claims_android_complete_does_not_cross_release(
    client: TestClient,
):
    """web 跑着可领设备 Job；结束 web 不释放手机；结束 Android 不挡下一条 web。"""
    rid = "q-mix"
    udid = "phone-mix"
    _reg(client, rid, ["web", "android"])
    _hb(client, rid, [{"udid": udid, "platform": "android", "name": "d"}])
    w1 = _job(client, "web-1", platform="web")
    w2 = _job(client, "web-2", platform="web")
    a1 = _job(client, "and-1", platform="android", udids=[udid])
    a2 = _job(client, "and-2", platform="android", udids=[udid])

    assert _claim(client, rid).json()["id"] == w1
    assert _claim(client, rid).json()["id"] == a1
    assert client.get(f"/api/v1/jobs/{w2}", headers=TOKEN).json()["status"] == "pending"
    assert client.get(f"/api/v1/jobs/{a2}", headers=TOKEN).json()["status"] == "pending"
    assert _busy_job(client, udid) == a1

    _complete(client, w1, rid)
    assert _busy_job(client, udid) == a1
    assert _claim(client, rid).json()["id"] == w2
    assert _claim(client, rid).json() is None

    _complete(client, a1, rid)
    assert _busy_job(client, udid) is None
    assert _claim(client, rid).json()["id"] == a2
    assert _busy_job(client, udid) == a2
    assert client.get(f"/api/v1/jobs/{w2}", headers=TOKEN).json()["status"] == "claimed"


def test_android_running_still_claims_web(client: TestClient):
    rid = "q-and-then-web"
    udid = "phone-then-web"
    _reg(client, rid, ["web", "android"])
    _hb(client, rid, [{"udid": udid, "platform": "android", "name": "d"}])
    a1 = _job(client, "and", platform="android", udids=[udid])
    w1 = _job(client, "web", platform="web")
    assert _claim(client, rid).json()["id"] == a1
    got = _claim(client, rid).json()
    assert got["id"] == w1
    assert got["platform"] == "web"
    _complete(client, a1, rid)
    assert _busy_job(client, udid) is None
    assert client.get(f"/api/v1/jobs/{w1}", headers=TOKEN).json()["status"] == "claimed"

