"""TestRunner：后端匹配、健康门禁、claim 过滤。"""

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

from autopilot_platform.core.backends import backends_ok, required_backends
from autopilot_platform.core.constants import (
    BACKEND_ANDROID_APPIUM,
    BACKEND_IOS_APPIUM,
    BACKEND_IOS_WDA,
    DEFAULT_API_TOKEN,
)
from autopilot_platform.platform.app import create_app
from autopilot_platform.platform.core.db import reset_engine

TOKEN = {"X-API-Token": DEFAULT_API_TOKEN}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "mc_runner_backends.db"
    url = f"sqlite:///{db_path.as_posix()}"
    monkeypatch.setenv("MC_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("MC_DATABASE_URL", url)
    reset_engine()
    app = create_app()
    with TestClient(app) as c:
        yield c
    reset_engine()


def test_required_backends_mapping():
    assert required_backends("android", "auto") is None
    assert required_backends("android", "uia2") == {BACKEND_ANDROID_APPIUM}
    assert required_backends("ios", "wda") == {BACKEND_IOS_WDA}
    assert required_backends("ios", "appium") == {BACKEND_IOS_APPIUM}
    assert required_backends("android", "appium") == {BACKEND_ANDROID_APPIUM}


def test_backends_ok_legacy_empty_allows():
    assert backends_ok([], platform="android", backend_mode="uia2") is True
    assert backends_ok(
        [BACKEND_IOS_WDA], platform="ios", backend_mode="wda"
    ) is True
    assert backends_ok(
        [BACKEND_IOS_WDA], platform="ios", backend_mode="appium"
    ) is False


def test_claim_skips_unauthorized_and_backend_mismatch(client: TestClient):
    rid = "probe-runner-1"
    client.post(
        "/api/v1/runners/register",
        headers=TOKEN,
        json={
            "runner_id": rid,
            "hostname": "h",
            "capabilities": ["android", BACKEND_ANDROID_APPIUM],
            "host_backends": [BACKEND_ANDROID_APPIUM],
        },
    )
    client.post(
        "/api/v1/runners/heartbeat",
        headers=TOKEN,
        json={
            "runner_id": rid,
            "inventory": [
                {
                    "udid": "bad-1",
                    "platform": "android",
                    "state": "unauthorized",
                    "backends": [BACKEND_ANDROID_APPIUM],
                    "health_note": "deny",
                },
                {
                    "udid": "wda-only",
                    "platform": "ios",
                    "state": "ready",
                    "backends": [BACKEND_IOS_WDA],
                },
                {
                    "udid": "ok-android",
                    "platform": "android",
                    "state": "ready",
                    "model": "Pixel",
                    "os_version": "14",
                    "backends": [BACKEND_ANDROID_APPIUM],
                },
            ], "devices": [
                {
                    "udid": "bad-1",
                    "platform": "android",
                    "state": "unauthorized",
                    "backends": [BACKEND_ANDROID_APPIUM],
                    "health_note": "deny",
                },
                {
                    "udid": "wda-only",
                    "platform": "ios",
                    "state": "ready",
                    "backends": [BACKEND_IOS_WDA],
                },
                {
                    "udid": "ok-android",
                    "platform": "android",
                    "state": "ready",
                    "model": "Pixel",
                    "os_version": "14",
                    "backends": [BACKEND_ANDROID_APPIUM],
                },
            ],
        },
    )
    devices = page_items(client.get("/api/v1/devices", headers=TOKEN).json())
    by_udid = {d["udid"]: d for d in devices}
    assert by_udid["bad-1"]["state"] == "unauthorized"
    assert by_udid["ok-android"]["backends"] == [BACKEND_ANDROID_APPIUM]
    assert by_udid["ok-android"]["os_version"] == "14"

    # unauthorized 目标不可 claim
    j1 = client.post(
        "/api/v1/jobs",
        headers=TOKEN,
        json={ "project_id": "p-mc",
            "name": "bad",
            "project_dir": str(ROOT),
            "platform": "android",
            "device_udids": ["bad-1"],
            "backend_mode": "uia2",
            "preferred_runner_id": rid,
        },
    ).json()
    claim = client.post(f"/api/v1/jobs/claim?runner_id={rid}", headers=TOKEN)
    assert claim.status_code == 200
    assert claim.json() is None or claim.json().get("id") != j1["id"]

    # ios-wda 设备不可领 appium 任务
    j2 = client.post(
        "/api/v1/jobs",
        headers=TOKEN,
        json={ "project_id": "p-mc",
            "name": "ios-appium",
            "project_dir": str(ROOT),
            "platform": "ios",
            "device_udids": ["wda-only"],
            "backend_mode": "appium",
            "preferred_runner_id": rid,
        },
    ).json()
    claim2 = client.post(f"/api/v1/jobs/claim?runner_id={rid}", headers=TOKEN)
    assert claim2.status_code == 200
    assert claim2.json() is None or claim2.json().get("id") != j2["id"]

    # android ready + uia2 可领
    j3 = client.post(
        "/api/v1/jobs",
        headers=TOKEN,
        json={ "project_id": "p-mc",
            "name": "ok",
            "project_dir": str(ROOT),
            "platform": "android",
            "device_udids": ["ok-android"],
            "backend_mode": "uia2",
            "preferred_runner_id": rid,
        },
    ).json()
    claim3 = client.post(f"/api/v1/jobs/claim?runner_id={rid}", headers=TOKEN)
    assert claim3.status_code == 200
    asserted = claim3.json()
    assert asserted is not None
    assert asserted["id"] == j3["id"]
    assert asserted["status"] == "claimed"


def test_heartbeat_refreshes_capabilities(client: TestClient):
    rid = "cap-refresh"
    client.post(
        "/api/v1/runners/register",
        headers=TOKEN,
        json={
            "runner_id": rid,
            "hostname": "h",
            "capabilities": ["android"],
        },
    )
    r = client.post(
        "/api/v1/runners/heartbeat",
        headers=TOKEN,
        json={
            "runner_id": rid,
            "capabilities": ["android", "parallel", BACKEND_ANDROID_APPIUM],
            "host_backends": [BACKEND_ANDROID_APPIUM],
            "inventory": [
                {
                    "udid": "d1",
                    "platform": "android",
                    "state": "ready",
                    "backends": [BACKEND_ANDROID_APPIUM],
                }
            ], "devices": [
                {
                    "udid": "d1",
                    "platform": "android",
                    "state": "ready",
                    "backends": [BACKEND_ANDROID_APPIUM],
                }
            ],
        },
    )
    assert r.status_code == 200
    caps = r.json().get("capabilities") or []
    assert "android" in caps
    assert BACKEND_ANDROID_APPIUM in caps
    assert "parallel" in caps


def test_dry_probe_importable():
    from autopilot_platform.runner.devices import format_probe_report

    text = format_probe_report()
    assert "host capabilities" in text
    assert "devices" in text


def test_web_job_routes_by_capability(client: TestClient):
    """web(Selenium) 任务：仅具备 web 能力的 Runner 可领取，移动 Runner 跳过。"""
    web_rid = "web-runner"
    client.post(
        "/api/v1/runners/register",
        headers=TOKEN,
        json={
            "runner_id": web_rid,
            "hostname": "w",
            "capabilities": ["web", "parallel", "report"],
        },
    )
    mob_rid = "android-runner"
    client.post(
        "/api/v1/runners/register",
        headers=TOKEN,
        json={
            "runner_id": mob_rid,
            "hostname": "a",
            "capabilities": ["android", BACKEND_ANDROID_APPIUM],
        },
    )
    jw = client.post(
        "/api/v1/jobs",
        headers=TOKEN,
        json={ "project_id": "p-mc","name": "web-suite", "project_dir": str(ROOT), "platform": "web"},
    ).json()

    # 移动 Runner 不得领取 web 任务
    c_mob = client.post(f"/api/v1/jobs/claim?runner_id={mob_rid}", headers=TOKEN)
    assert c_mob.status_code == 200
    assert c_mob.json() is None or c_mob.json().get("id") != jw["id"]

    # web Runner 领取成功（无 UDID 亦可）
    c_web = client.post(f"/api/v1/jobs/claim?runner_id={web_rid}", headers=TOKEN)
    assert c_web.status_code == 200
    got = c_web.json()
    assert got is not None
    assert got["id"] == jw["id"]
    assert got["platform"] == "web"
    assert got["status"] == "claimed"


def test_playwright_web_job_requires_web_playwright_capability(client: TestClient):
    """web_engine=playwright 任务：仅 web+web-playwright Runner 可领取。"""
    sel_rid = "web-selenium-only"
    client.post(
        "/api/v1/runners/register",
        headers=TOKEN,
        json={
            "runner_id": sel_rid,
            "hostname": "ws",
            "capabilities": ["web", "parallel", "report"],
        },
    )
    pw_rid = "web-playwright"
    client.post(
        "/api/v1/runners/register",
        headers=TOKEN,
        json={
            "runner_id": pw_rid,
            "hostname": "wp",
            "capabilities": ["web", "web-playwright", "parallel", "report"],
        },
    )
    jp = client.post(
        "/api/v1/jobs",
        headers=TOKEN,
        json={ "project_id": "p-mc",
            "name": "pw-suite",
            "project_dir": str(ROOT),
            "platform": "web",
            "web_engine": "playwright",
        },
    ).json()

    c_sel = client.post(f"/api/v1/jobs/claim?runner_id={sel_rid}", headers=TOKEN)
    assert c_sel.status_code == 200
    assert c_sel.json() is None or c_sel.json().get("id") != jp["id"]

    c_pw = client.post(f"/api/v1/jobs/claim?runner_id={pw_rid}", headers=TOKEN)
    assert c_pw.status_code == 200
    got = c_pw.json()
    assert got is not None
    assert got["id"] == jp["id"]
    assert got.get("web_engine") == "playwright"


def test_web_runner_skips_mobile_job(client: TestClient):
    """纯 web Runner（无 android/ios 能力）不得误抢无 UDID 的移动任务。"""
    web_rid = "web-only"
    client.post(
        "/api/v1/runners/register",
        headers=TOKEN,
        json={
            "runner_id": web_rid,
            "hostname": "w",
            "capabilities": ["web", "parallel", "report"],
        },
    )
    ja = client.post(
        "/api/v1/jobs",
        headers=TOKEN,
        json={ "project_id": "p-mc","name": "android-no-udid", "project_dir": str(ROOT), "platform": "android"},
    ).json()
    c = client.post(f"/api/v1/jobs/claim?runner_id={web_rid}", headers=TOKEN)
    assert c.status_code == 200
    assert c.json() is None or c.json().get("id") != ja["id"]
