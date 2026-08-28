"""管理台 API → claim → execute_job → 关键字读 ctx 的可执行链。

覆盖 Web / Android / iOS / HTTP：运行配置从 HTTP 一直接到 Runner 注入，
再接到关键字实际读取的变量（不启真机 / 浏览器）。
"""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import sys
import zipfile
from dataclasses import replace
from io import BytesIO
from pathlib import Path

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient

from autopilot_platform.core.constants import (
    BACKEND_ANDROID_APPIUM,
    BACKEND_IOS_WDA,
    DEFAULT_API_TOKEN,
)
from autopilot_platform.core.schemas import DeviceInfo
from autopilot_platform.platform.app import create_app
from autopilot_platform.platform.core.db import reset_engine
from autopilot_platform.runner.contract import JobOut, JobStatus
from autopilot_platform.runner.execute import execute_job

TOKEN = {"X-API-Token": DEFAULT_API_TOKEN}
FE = Path(ROOT) / "autopilot_platform" / "frontend" / "src"


class _FakeSuite:
    name = "Suite"
    duration_ms = 12
    results: list = []

    @staticmethod
    def case_counts() -> dict:
        return {"passed": 1, "failed": 0, "total": 1}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "mc_exec_chain.db"
    url = f"sqlite:///{db_path.as_posix()}"
    monkeypatch.setenv("MC_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("MC_APP_BUILDS_DIR", str(tmp_path / "app_builds"))
    monkeypatch.setenv("MC_ADMIN_USER", "admin")
    monkeypatch.setenv("MC_ADMIN_PASSWORD", "admin")
    monkeypatch.setenv("MC_SCHEDULE_ENABLED", "0")
    monkeypatch.setenv("MC_RUNTIME_CONFIG", str(tmp_path / "mc_runtime_config.json"))
    monkeypatch.setenv("MC_JOB_LOGS_DIR", str(tmp_path / "job_logs"))
    monkeypatch.setenv("MC_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MC_REPORTS_DIR", str(tmp_path / "reports"))
    monkeypatch.delenv("AUTOPILOT_WEB_ENGINE", raising=False)
    reset_engine()
    from autopilot_platform.platform.ops.runtime_config import reload_runtime_config

    reload_runtime_config()
    app = create_app(database_url=url)
    with TestClient(app) as c:
        yield c
    reset_engine()
    reload_runtime_config()


def _admin(client: TestClient) -> dict:
    r = client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _seed_project(tmp_path) -> str:
    proj = tmp_path / "suite"
    proj.mkdir(exist_ok=True)
    (proj / "c1.tc.yaml").write_text("name: c1\nsteps: []\n", encoding="utf-8")
    return str(proj)


def _seed_approved(client: TestClient, headers: dict, tmp_path, project_id: str) -> tuple[str, str]:
    r = client.post(
        "/api/v1/design/logical-cases",
        headers=headers,
        json={
            "project_id": project_id,
            "title": "seed",
            "logical_steps": ["open"],
            "expected_results": ["ok"],
            "review_status": "APPROVED",
        },
    )
    assert r.status_code == 200, r.text
    case_id = r.json()["logical_case_id"]
    suite = tmp_path / f"suite-{project_id}"
    suite.mkdir()
    (suite / "c1.tc.yaml").write_text(
        f"name: c1\nlogical_case_id: {case_id}\nsteps: []\n",
        encoding="utf-8",
    )
    sha = hashlib.sha256(b"x").hexdigest()
    manifest = {
        "schema_version": "1.0",
        "artifact_version": "1",
        "project_id": project_id,
        "sha256": sha,
        "required_runtime_version": "0.1.0-vendored",
        "required_capabilities": [],
        "case_index": [{"relative_path": "c1.tc.yaml", "logical_case_id": case_id}],
    }
    (suite / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.write(suite / "c1.tc.yaml", "c1.tc.yaml")
        zf.write(suite / "manifest.json", "manifest.json")
    buf.seek(0)
    r = client.post(
        "/api/v1/artifacts",
        headers=headers,
        files={"file": ("suite.zip", buf.getvalue(), "application/zip")},
        data={"name": "suite", "project_id": project_id},
    )
    assert r.status_code == 200, r.text
    return case_id, r.json()["id"]


def _register_runner(
    client: TestClient,
    runner_id: str,
    *,
    capabilities: list[str],
    devices: list[dict] | None = None,
    host_backends: list[str] | None = None,
) -> None:
    r = client.post(
        "/api/v1/runners/register",
        headers=TOKEN,
        json={
            "runner_id": runner_id,
            "hostname": runner_id,
            "capabilities": capabilities,
            "host_backends": list(host_backends or []),
        },
    )
    assert r.status_code == 200, r.text
    hb = {
        "runner_id": runner_id,
        "capabilities": capabilities,
        "host_backends": list(host_backends or []),
        "inventory": list(devices or []),
        "devices": list(devices or []),
    }
    r = client.post("/api/v1/runners/heartbeat", headers=TOKEN, json=hb)
    assert r.status_code == 200, r.text


def _claim(client: TestClient, runner_id: str) -> dict:
    r = client.post(f"/api/v1/jobs/claim?runner_id={runner_id}", headers=TOKEN)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body and body.get("id"), body
    return body


def _patch_execute(monkeypatch, *, local_devices: list[DeviceInfo] | None = None) -> dict:
    captured: dict = {}

    def fake_run(directory, **kwargs):
        captured["directory"] = directory
        captured.update(kwargs)
        return _FakeSuite()

    monkeypatch.setattr("autopilot_platform.ap.engine.run_project_directory", fake_run)
    monkeypatch.setattr("autopilot_platform.ap.report.write_report", lambda *a, **k: None)
    monkeypatch.setattr(
        "autopilot_platform.ap.report.result_json.write_result_json",
        lambda *a, **k: None,
    )
    if local_devices is not None:
        monkeypatch.setattr(
            "autopilot_platform.runner.devices.list_local_devices",
            lambda: list(local_devices),
        )
    return captured


def _execute_claimed(claimed: dict, captured: dict, *, project_dir: str):
    job = JobOut.from_dict(claimed)
    if not (job.project_dir and os.path.isdir(job.project_dir)):
        job = replace(job, project_dir=project_dir, artifact_id=None)
    result = execute_job(job)
    assert result.status == JobStatus.SUCCEEDED, result.error
    assert "base_vars" in captured
    return job, captured


def _ctx_from_vars(base_vars: dict | None):
    from autopilot_platform.ap.keywords.context import ExecutionContext

    ctx = ExecutionContext()
    for key, value in dict(base_vars or {}).items():
        ctx.set_var(key, value)
    return ctx


def _assert_web_keywords(base_vars: dict, *, engine: str, browser: str) -> None:
    from autopilot_platform.ap.keywords.web.browser import browser_open
    from autopilot_platform.ap.keywords.web.driver import resolve_web_engine

    ctx = _ctx_from_vars(base_vars)
    assert resolve_web_engine(ctx) == engine
    type_ = ""
    picked = (type_ or "").strip() or str(ctx.get_var("__web_browser__") or "").strip() or "Chrome"
    assert picked == browser
    src = inspect.getsource(browser_open)
    assert "__web_browser__" in src
    assert "__device_udid__" not in base_vars


def _assert_mobile_keywords(base_vars: dict, *, platform: str, udid: str, backend: str) -> None:
    import autopilot_platform.ap.keywords.mobile.session as mobile_session

    ctx = _ctx_from_vars(base_vars)
    assert str(ctx.get_var("__mobile_backend_mode__") or "") == backend
    # 白盒：验证关键字从 ctx 解析设备；依赖模块内 _device_for_platform
    device_for_platform = getattr(mobile_session, "_device_for_platform")
    assert device_for_platform(ctx, platform) == udid
    src = inspect.getsource(device_for_platform)
    assert "__device_udid__" in src


def test_create_claim_execute_web_playwright_edge(client: TestClient, tmp_path, monkeypatch):
    proj = _seed_project(tmp_path)
    rid = "exec-web-pw"
    _register_runner(
        client,
        rid,
        capabilities=["web", "web-playwright", "parallel", "report"],
    )
    created = client.post(
        "/api/v1/jobs",
        headers=TOKEN,
        json={
            "project_id": "p-mc",
            "name": "web-pw",
            "project_dir": proj,
            "platform": "web",
            "web_engine": "playwright",
            "backend_mode": "edge",
            "preferred_runner_id": rid,
        },
    )
    assert created.status_code == 200, created.text
    job_row = created.json()
    assert job_row["platform"] == "web"
    assert job_row["web_engine"] == "playwright"
    assert job_row["backend_mode"] == "edge"
    assert job_row["device_udids"] == []

    captured = _patch_execute(monkeypatch)
    claimed = _claim(client, rid)
    assert claimed["id"] == job_row["id"]
    _execute_claimed(claimed, captured, project_dir=proj)

    base = captured["base_vars"] or {}
    assert base.get("__web_engine__") == "playwright"
    assert base.get("__web_browser__") == "edge"
    assert captured.get("platform") == "web"
    assert captured.get("wda_bundle") in ("", None)
    _assert_web_keywords(base, engine="playwright", browser="edge")


def test_create_claim_execute_android_uia2(client: TestClient, tmp_path, monkeypatch):
    proj = _seed_project(tmp_path)
    rid = "exec-and"
    udid = "phone-a"
    _register_runner(
        client,
        rid,
        capabilities=["android", BACKEND_ANDROID_APPIUM, "parallel"],
        host_backends=[BACKEND_ANDROID_APPIUM],
        devices=[
            {
                "udid": udid,
                "platform": "android",
                "state": "ready",
                "backends": [BACKEND_ANDROID_APPIUM],
            }
        ],
    )
    created = client.post(
        "/api/v1/jobs",
        headers=TOKEN,
        json={
            "project_id": "p-mc",
            "name": "and-uia2",
            "project_dir": proj,
            "platform": "android",
            "backend_mode": "uia2",
            "device_udids": [udid],
            "preferred_runner_id": rid,
        },
    )
    assert created.status_code == 200, created.text
    captured = _patch_execute(
        monkeypatch,
        local_devices=[
            DeviceInfo(
                udid=udid,
                platform="android",
                state="ready",
                backends=[BACKEND_ANDROID_APPIUM],
            )
        ],
    )
    claimed = _claim(client, rid)
    assert claimed["id"] == created.json()["id"]
    _execute_claimed(claimed, captured, project_dir=proj)

    base = captured["base_vars"] or {}
    assert base.get("__device_udid__") == udid
    assert base.get("__mobile_backend_mode__") == "uia2"
    assert "__web_engine__" not in base
    assert captured.get("platform") == "android"
    assert captured.get("backend_mode") == "uia2"
    assert captured.get("device_udids") == [udid]
    _assert_mobile_keywords(base, platform="Android", udid=udid, backend="uia2")


def test_create_claim_execute_ios_wda_bundle(client: TestClient, tmp_path, monkeypatch):
    proj = _seed_project(tmp_path)
    rid = "exec-ios"
    udid = "ios-1"
    wda = "com.example.WebDriverAgentRunner"
    _register_runner(
        client,
        rid,
        capabilities=["ios", BACKEND_IOS_WDA, "parallel"],
        host_backends=[BACKEND_IOS_WDA],
        devices=[
            {
                "udid": udid,
                "platform": "ios",
                "state": "ready",
                "backends": [BACKEND_IOS_WDA],
            }
        ],
    )
    created = client.post(
        "/api/v1/jobs",
        headers=TOKEN,
        json={
            "project_id": "p-mc",
            "name": "ios-wda",
            "project_dir": proj,
            "platform": "ios",
            "backend_mode": "wda",
            "wda_bundle": wda,
            "device_udids": [udid],
            "preferred_runner_id": rid,
        },
    )
    assert created.status_code == 200, created.text
    captured = _patch_execute(
        monkeypatch,
        local_devices=[
            DeviceInfo(
                udid=udid,
                platform="ios",
                state="ready",
                backends=[BACKEND_IOS_WDA],
            )
        ],
    )
    claimed = _claim(client, rid)
    _execute_claimed(claimed, captured, project_dir=proj)

    base = captured["base_vars"] or {}
    assert base.get("__device_udid__") == udid
    assert base.get("__mobile_backend_mode__") == "wda"
    assert captured.get("wda_bundle") == wda
    assert captured.get("backend_mode") == "wda"
    assert captured.get("platform") == "ios"
    _assert_mobile_keywords(base, platform="iOS", udid=udid, backend="wda")


def test_enqueue_claim_execute_web_chrome(client: TestClient, tmp_path, monkeypatch):
    h = _admin(client)
    case_id, aid = _seed_approved(client, h, tmp_path, "p-enq-exec")
    rid = "exec-enq-web"
    _register_runner(
        client,
        rid,
        capabilities=["web", "web-playwright", "parallel", "report"],
    )
    r = client.post(
        "/api/v1/design/logical-cases/enqueue-job",
        headers=h,
        json={
            "project_id": "p-enq-exec",
            "artifact_id": aid,
            "logical_case_ids": [case_id],
            "platform": "web",
            "web_engine": "playwright",
            "backend_mode": "chrome",
            "preferred_runner_id": rid,
            "name": "enq-web",
        },
    )
    assert r.status_code == 200, r.text
    job_row = r.json()
    assert job_row["platform"] == "web"
    assert job_row["web_engine"] == "playwright"
    assert job_row["backend_mode"] == "chrome"

    captured = _patch_execute(monkeypatch)
    claimed = _claim(client, rid)
    assert claimed["id"] == job_row["id"]
    _execute_claimed(claimed, captured, project_dir=_seed_project(tmp_path))
    base = captured["base_vars"] or {}
    assert base.get("__web_engine__") == "playwright"
    assert base.get("__web_browser__") == "chrome"
    _assert_web_keywords(base, engine="playwright", browser="chrome")


def test_schedule_run_now_claim_execute_ios(client: TestClient, tmp_path, monkeypatch):
    h = _admin(client)
    proj = _seed_project(tmp_path)
    rid = "exec-sch-ios"
    udid = "ios-sch"
    wda = "com.schedule.wda"
    _register_runner(
        client,
        rid,
        capabilities=["ios", BACKEND_IOS_WDA, "parallel"],
        host_backends=[BACKEND_IOS_WDA],
        devices=[
            {
                "udid": udid,
                "platform": "ios",
                "state": "ready",
                "backends": [BACKEND_IOS_WDA],
            }
        ],
    )
    r = client.post(
        "/api/v1/schedules",
        headers=h,
        json={
            "project_id": "p-mc",
            "name": "ios-sch",
            "project_dir": proj,
            "platform": "ios",
            "backend_mode": "wda",
            "wda_bundle": wda,
            "device_udids": [udid],
            "preferred_runner_id": rid,
            "delay_sec": 0,
            "interval_sec": 0,
            "repeat": 1,
            "enabled": True,
        },
    )
    assert r.status_code == 200, r.text
    sid = r.json()["id"]
    r = client.post(f"/api/v1/schedules/{sid}/run-now", headers=h)
    assert r.status_code == 200, r.text
    jid = r.json().get("last_job_id")
    job = client.get(f"/api/v1/jobs/{jid}", headers=h).json()
    assert job.get("wda_bundle") == wda
    assert job.get("backend_mode") == "wda"

    captured = _patch_execute(
        monkeypatch,
        local_devices=[
            DeviceInfo(
                udid=udid,
                platform="ios",
                state="ready",
                backends=[BACKEND_IOS_WDA],
            )
        ],
    )
    claimed = _claim(client, rid)
    assert claimed["id"] == jid
    _execute_claimed(claimed, captured, project_dir=proj)
    assert (captured.get("base_vars") or {}).get("__mobile_backend_mode__") == "wda"
    assert captured.get("wda_bundle") == wda


def test_create_claim_execute_http_env_profile(client: TestClient, tmp_path, monkeypatch):
    proj = Path(_seed_project(tmp_path))
    (proj / "api_env.yaml").write_text(
        "profiles:\n  staging:\n    base_url: https://api.example.test\n    vars:\n      api_token: t-stg\n",
        encoding="utf-8",
    )
    rid = "exec-http"
    _register_runner(client, rid, capabilities=["http", "parallel", "report"])
    created = client.post(
        "/api/v1/jobs",
        headers=TOKEN,
        json={
            "project_id": "p-mc",
            "name": "http-stg",
            "project_dir": str(proj),
            "platform": "http",
            "backend_mode": "staging",
            "device_udids": ["should-strip"],
            "preferred_runner_id": rid,
        },
    )
    assert created.status_code == 200, created.text
    job_row = created.json()
    assert job_row["platform"] == "http"
    assert job_row["backend_mode"] == "staging"
    assert job_row["device_udids"] == []

    captured = _patch_execute(monkeypatch)
    claimed = _claim(client, rid)
    assert claimed["id"] == job_row["id"]
    _execute_claimed(claimed, captured, project_dir=str(proj))
    base = captured["base_vars"] or {}
    assert base.get("__http_env_profile__") == "staging"
    assert base.get("base_url") == "https://api.example.test"
    assert base.get("api_token") == "t-stg"
    from autopilot_platform.ap.keywords.context import ExecutionContext
    from autopilot_platform.ap.keywords.http.session import http_session_begin

    ctx = ExecutionContext()
    for key, value in base.items():
        ctx.set_var(key, value)
    http_session_begin(ctx)
    assert ctx.http_session.base_url == "https://api.example.test"


def test_require_job_devices_allows_http_without_udids(client: TestClient, tmp_path, monkeypatch):
    monkeypatch.setenv("MC_REQUIRE_JOB_DEVICES", "1")
    proj = _seed_project(tmp_path)
    r = client.post(
        "/api/v1/jobs",
        headers=TOKEN,
        json={
            "project_id": "p-mc",
            "name": "http-exempt",
            "project_dir": proj,
            "platform": "http",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["device_udids"] == []


def test_http_is_a_job_platform():
    from autopilot_platform.core.job_platforms import (
        DEVICELESS_PLATFORMS,
        JOB_PLATFORMS,
        is_deviceless_platform,
    )

    assert "http" in JOB_PLATFORMS
    assert "http" in DEVICELESS_PLATFORMS
    assert is_deviceless_platform("HTTP")
    src = (FE / "composables" / "runTargetOptions.ts").read_text(encoding="utf-8")
    assert 'value: "http"' in src
