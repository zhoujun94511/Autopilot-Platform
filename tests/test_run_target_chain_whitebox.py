"""运行目标链路白盒：共用组件 → 入队/计划 API → Job 字段。

覆盖上一轮缺口的可执行链（不只扫 Vue 源码）：
- applyPlatformSideEffects 规则（Python 镜像 + TS 契约防漂移）
- LogicalCaseEnqueueJobIn → enqueue-job → Job 行
- Web 入队剥离设备/并行；MC_REQUIRE_JOB_DEVICES 对 web 豁免、对 android 仍强制
- 计划 PATCH 的 wda_bundle / parallel_workers 经 run-now 落到 Job
- 前端提交体与确认框仍接在同一套字段上
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import zipfile
from io import BytesIO
from pathlib import Path

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient

from autopilot_platform.platform.app import create_app
from autopilot_platform.platform.core.db import reset_engine
from autopilot_platform.platform.design.design_schemas import LogicalCaseEnqueueJobIn

FE = Path(ROOT) / "autopilot_platform" / "frontend" / "src"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "mc_test.db"
    url = f"sqlite:///{db_path.as_posix()}"
    monkeypatch.setenv("MC_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("MC_ADMIN_USER", "admin")
    monkeypatch.setenv("MC_ADMIN_PASSWORD", "admin")
    monkeypatch.setenv("MC_SCHEDULE_ENABLED", "0")
    monkeypatch.setenv("MC_RUNTIME_CONFIG", str(tmp_path / "mc_runtime_config.json"))
    monkeypatch.setenv("MC_JOB_LOGS_DIR", str(tmp_path / "job_logs"))
    monkeypatch.setenv("MC_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MC_REPORTS_DIR", str(tmp_path / "reports"))
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


# ---------------------------------------------------------------------------
# 共用组件：切平台副作用（core.job_platforms，与 runTargetOptions.ts 对齐）
# ---------------------------------------------------------------------------

from autopilot_platform.core.job_platforms import apply_platform_side_effects


def test_apply_platform_side_effects_web_clears_mobile_and_keeps_browser():
    form = {
        "device_udids": "U1, U2",
        "app_build_id": "apk-1",
        "parallel": True,
        "parallel_workers": 4,
        "wda_bundle": "com.wda",
        "backend_mode": "chrome",
        "web_engine": "",
    }
    apply_platform_side_effects(form, "web")
    assert form["device_udids"] == ""
    assert form["app_build_id"] == ""
    assert form["parallel"] is False
    assert form["parallel_workers"] == 0
    assert form["wda_bundle"] == ""
    assert form["backend_mode"] == "chrome"
    assert form["web_engine"] == "selenium"


def test_apply_platform_side_effects_web_resets_forced_mobile_backend():
    form = {"backend_mode": "uia2", "web_engine": "playwright", "device_udids": "U1"}
    apply_platform_side_effects(form, "WEB")
    assert form["backend_mode"] == "auto"
    assert form["web_engine"] == "playwright"


def test_apply_platform_side_effects_mobile_resets_browser_backend():
    form = {"backend_mode": "edge", "device_udids": "U1", "parallel": True}
    apply_platform_side_effects(form, "ios")
    assert form["backend_mode"] == "auto"
    assert form["device_udids"] == "U1"
    assert form["parallel"] is True


def test_apply_platform_side_effects_http_resets_mobile_leftover():
    form = {"backend_mode": "uia2", "web_engine": "playwright", "device_udids": "U1"}
    apply_platform_side_effects(form, "http")
    assert form["backend_mode"] == "auto"
    assert form["web_engine"] == "selenium"
    assert form["device_udids"] == ""


def test_apply_platform_side_effects_http_keeps_profile():
    form = {
        "device_udids": "U1",
        "parallel": True,
        "wda_bundle": "com.wda",
        "backend_mode": "staging",
        "web_engine": "playwright",
    }
    apply_platform_side_effects(form, "http")
    assert form["device_udids"] == ""
    assert form["parallel"] is False
    assert form["wda_bundle"] == ""
    assert form["backend_mode"] == "staging"
    assert form["web_engine"] == "selenium"


def test_ts_side_effects_contract_matches_python_mirror():
    src = (FE / "composables" / "runTargetOptions.ts").read_text(encoding="utf-8")
    assert 'new Set(["uia2", "wda", "appium"])' in src
    assert 'new Set(["chrome", "edge", "firefox", "headless"])' in src
    assert "form.device_udids = \"\"" in src
    assert "form.parallel = false" in src
    assert "form.wda_bundle = \"\"" in src
    vue = (FE / "components" / "common" / "RunTargetFields.vue").read_text(encoding="utf-8")
    assert "applyPlatformSideEffects(props.model" in vue


def test_enqueue_schema_accepts_run_target_fields():
    body = LogicalCaseEnqueueJobIn(
        project_id="p",
        artifact_id="a",
        platform="ios",
        backend_mode="wda",
        wda_bundle="com.example.wda",
        parallel=True,
        parallel_workers=2,
        preferred_runner_id="runner-1",
    )
    assert body.backend_mode == "wda"
    assert body.wda_bundle == "com.example.wda"
    assert body.parallel is True
    assert body.parallel_workers == 2
    assert body.preferred_runner_id == "runner-1"


def test_enqueue_schema_http_strips_mobile_keeps_profile():
    body = LogicalCaseEnqueueJobIn(
        project_id="p",
        artifact_id="a",
        platform="http",
        backend_mode="staging",
        web_engine="playwright",
        device_udids=["should-strip"],
        parallel=True,
        parallel_workers=3,
        wda_bundle="com.wda",
        app_build_id="apk-1",
    )
    assert body.platform == "http"
    assert body.backend_mode == "staging"
    assert body.device_udids == []
    assert body.parallel is False
    assert body.parallel_workers == 0
    assert body.wda_bundle == ""
    assert not body.app_build_id
    assert body.web_engine == "selenium"


def test_enqueue_web_strips_leftover_mobile_fields(client: TestClient, tmp_path):
    """前端误带 UDID/并行时，服务端仍按 web 语义落 Job。"""
    h = _admin(client)
    case_id, aid = _seed_approved(client, h, tmp_path, "p-enq-strip")
    r = client.post(
        "/api/v1/design/logical-cases/enqueue-job",
        headers=h,
        json={
            "project_id": "p-enq-strip",
            "artifact_id": aid,
            "logical_case_ids": [case_id],
            "platform": "web",
            "web_engine": "playwright",
            "backend_mode": "chrome",
            "device_udids": ["should-not-keep"],
            "parallel": True,
            "parallel_workers": 8,
            "wda_bundle": "com.should.not",
            "name": "web-strip",
        },
    )
    assert r.status_code == 200, r.text
    job = r.json()
    assert job["platform"] == "web"
    assert job["web_engine"] == "playwright"
    assert job["backend_mode"] == "chrome"
    assert job["device_udids"] == []
    assert job["parallel"] is False
    assert job["parallel_workers"] == 0
    assert job.get("wda_bundle") in ("", None)


def test_enqueue_http_strips_leftover_mobile_fields(client: TestClient, tmp_path):
    """HTTP 与 Web 同属无设备平台：误带 UDID/并行/应用包时服务端剥离，保留 profile。"""
    h = _admin(client)
    case_id, aid = _seed_approved(client, h, tmp_path, "p-enq-http-strip")
    r = client.post(
        "/api/v1/design/logical-cases/enqueue-job",
        headers=h,
        json={
            "project_id": "p-enq-http-strip",
            "artifact_id": aid,
            "logical_case_ids": [case_id],
            "platform": "http",
            "web_engine": "playwright",
            "backend_mode": "staging",
            "device_udids": ["should-not-keep"],
            "parallel": True,
            "parallel_workers": 8,
            "wda_bundle": "com.should.not",
            "name": "http-strip",
        },
    )
    assert r.status_code == 200, r.text
    job = r.json()
    assert job["platform"] == "http"
    assert job["backend_mode"] == "staging"
    assert job["web_engine"] == "selenium"
    assert job["device_udids"] == []
    assert job["parallel"] is False
    assert job["parallel_workers"] == 0
    assert job.get("wda_bundle") in ("", None)
    assert job.get("app_build_id") in ("", None)


def test_require_job_devices_enqueue_web_ok_android_rejected(
    client: TestClient, tmp_path, monkeypatch
):
    monkeypatch.setenv("MC_REQUIRE_JOB_DEVICES", "1")
    h = _admin(client)
    web_case, web_aid = _seed_approved(client, h, tmp_path, "p-req-web")
    and_case, and_aid = _seed_approved(client, h, tmp_path, "p-req-and")

    r = client.post(
        "/api/v1/design/logical-cases/enqueue-job",
        headers=h,
        json={
            "project_id": "p-req-web",
            "artifact_id": web_aid,
            "logical_case_ids": [web_case],
            "platform": "web",
            "name": "web-exempt",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["device_udids"] == []

    r = client.post(
        "/api/v1/design/logical-cases/enqueue-job",
        headers=h,
        json={
            "project_id": "p-req-and",
            "artifact_id": and_aid,
            "logical_case_ids": [and_case],
            "platform": "android",
            "name": "android-must-device",
        },
    )
    assert r.status_code == 400, r.text
    msg = str(r.json().get("message") or r.json().get("detail") or r.text)
    assert "device_udids" in msg


def test_schedule_patch_run_target_fields_fire_to_job(client: TestClient):
    h = _admin(client)
    r = client.post(
        "/api/v1/schedules",
        headers=h,
        json={
            "project_id": "p-mc",
            "name": "ios-patch",
            "project_dir": "/tmp/ios-suite",
            "platform": "ios",
            "backend_mode": "auto",
            "delay_sec": 0,
            "interval_sec": 0,
            "repeat": 1,
            "enabled": True,
        },
    )
    assert r.status_code == 200, r.text
    sid = r.json()["id"]
    r = client.patch(
        f"/api/v1/schedules/{sid}",
        headers=h,
        json={
            "backend_mode": "wda",
            "wda_bundle": "com.example.WebDriverAgentRunner",
            "parallel": True,
            "parallel_workers": 5,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("backend_mode") == "wda"
    assert body.get("wda_bundle") == "com.example.WebDriverAgentRunner"
    assert body.get("parallel_workers") == 5

    r = client.post(f"/api/v1/schedules/{sid}/run-now", headers=h)
    assert r.status_code == 200, r.text
    jid = r.json().get("last_job_id")
    job = client.get(f"/api/v1/jobs/{jid}", headers=h).json()
    assert job.get("backend_mode") == "wda"
    assert job.get("wda_bundle") == "com.example.WebDriverAgentRunner"
    assert job.get("parallel_workers") == 5
    assert job.get("parallel") is True


def test_frontend_submit_chain_wires_run_target_fields():
    actions = (FE / "composables" / "mcExecActions.ts").read_text(encoding="utf-8")
    assert "isDevicelessPlatform" in actions
    assert "stripDevicelessSubmitPayload" in actions
    assert "未指定设备时，任意空闲 Runner 均可领取该任务" in actions
    assert "S.scheduleForm.wda_bundle" in actions
    assert "S.scheduleForm.parallel_workers" in actions
    panel = (FE / "components" / "design" / "DesignCasesPanel.vue").read_text(
        encoding="utf-8"
    )
    assert "backend_mode:" in panel
    assert "wda_bundle:" in panel
    assert "parallel_workers:" in panel
    assert "isDevicelessPlatform" in panel
    src = (FE / "composables" / "runTargetOptions.ts").read_text(encoding="utf-8")
    assert 'value: "http"' in src
    assert "stripDevicelessSubmitPayload" in src
    for rel in (
        "components/JobCreatePanel.vue",
        "components/design/EnqueueRunConfigCard.vue",
        "components/SchedulesPanel.vue",
    ):
        text = (FE / rel).read_text(encoding="utf-8")
        assert "RunTargetFields" in text, rel
