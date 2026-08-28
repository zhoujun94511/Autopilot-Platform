"""链路修补：result.json 回写、runners 组织过滤、APPROVED enqueue、runtime 版本。"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import zipfile
from io import BytesIO

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient

from list_page_helpers import page_items

from autopilot_platform.platform.app import create_app
from autopilot_platform.platform.core.db import reset_engine

TOKEN = {"X-API-Token": "dev-mc-token"}


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


def test_result_json_writes_back_automation_status(client: TestClient):
    h = _admin(client)
    r = client.post(
        "/api/v1/design/logical-cases",
        headers=h,
        json={
            "project_id": "p-sync",
            "title": "login",
            "logical_steps": ["打开登录页", "输入账号", "点击登录"],
            "expected_results": ["进入首页"],
            "review_status": "APPROVED",
            "automation_status": "PENDING_VERIFY",
        },
    )
    assert r.status_code == 200, r.text
    case_id = r.json()["logical_case_id"]
    assert r.json()["automation_status"] == "PENDING_VERIFY"

    # 建 job + claim 以便上报 result
    rid = "r-sync"
    client.post(
        "/api/v1/runners/register",
        headers=TOKEN,
        json={"runner_id": rid, "hostname": "h"},
    )
    jid = client.post(
        "/api/v1/jobs",
        headers=TOKEN,
        json={ "project_id": "p-sync","name": "sync", "project_dir": "/tmp/x", "platform": "android"},
    ).json()["id"]
    client.post(f"/api/v1/jobs/claim?runner_id={rid}", headers=TOKEN)
    client.post(
        f"/api/v1/jobs/{jid}/complete?runner_id={rid}",
        headers=TOKEN,
        json={"status": "succeeded"},
    )

    payload = {
        "schema_version": "1.0",
        "job_id": jid,
        "status": "succeeded",
        "suite": {"name": "s", "passed": 1, "failed": 0, "total": 1, "duration_ms": 10},
        "environment": {},
        "cases": [
            {"name": "login", "status": "passed", "logical_case_id": case_id},
        ],
    }
    r = client.post(
        f"/api/v1/jobs/{jid}/report?runner_id={rid}",
        headers=TOKEN,
        files={"file": ("result.json", json.dumps(payload).encode("utf-8"), "application/json")},
    )
    assert r.status_code == 200, r.text

    r = client.get(f"/api/v1/design/logical-cases/{case_id}", headers=h)
    assert r.status_code == 200
    assert r.json()["automation_status"] == "EXECUTABLE"


def test_runners_list_org_filter(client: TestClient):
    h = _admin(client)
    # 建两个组织 + 两个 runner
    r = client.post("/api/v1/orgs", headers=h, json={"id": "orga", "name": "OrgA"})
    assert r.status_code in (200, 201), r.text
    org_a = r.json()["id"]
    r = client.post("/api/v1/orgs", headers=h, json={"id": "orgb", "name": "OrgB"})
    assert r.status_code in (200, 201), r.text
    org_b = r.json()["id"]

    client.post(
        "/api/v1/runners/register",
        headers=TOKEN,
        json={"runner_id": "runner-a", "hostname": "a"},
    )
    client.post(
        "/api/v1/runners/register",
        headers=TOKEN,
        json={"runner_id": "runner-b", "hostname": "b"},
    )
    ra = client.post(
        "/api/v1/runners/runner-a/token",
        headers=h,
        json={"org_id": org_a, "project_ids": []},
    )
    assert ra.status_code == 200, ra.text
    rb = client.post(
        "/api/v1/runners/runner-b/token",
        headers=h,
        json={"org_id": org_b, "project_ids": []},
    )
    assert rb.status_code == 200, rb.text

    # 普通用户加入 orgA
    r = client.post(
        "/api/v1/auth/users",
        headers=h,
        json={"username": "u-orga", "password": "Userpass1", "duty": "user"},
    )
    assert r.status_code == 200, r.text
    r = client.post(
        f"/api/v1/orgs/{org_a}/members",
        headers=h,
        json={"username": "u-orga", "role": "member"},
    )
    assert r.status_code == 200, r.text

    login = client.post(
        "/api/v1/auth/login", json={"username": "u-orga", "password": "Userpass1"}
    )
    assert login.status_code == 200
    uh = {
        "Authorization": f"Bearer {login.json()['access_token']}",
        "X-Org-Id": org_a,
    }
    r = client.get("/api/v1/runners", headers=uh)
    assert r.status_code == 200, r.text
    ids = {x["runner_id"] for x in page_items(r.json())}
    assert "runner-a" in ids
    assert "runner-b" not in ids


def test_enqueue_approved_job(client: TestClient, tmp_path):
    h = _admin(client)
    # 创建 APPROVED 用例
    r = client.post(
        "/api/v1/design/logical-cases",
        headers=h,
        json={
            "project_id": "p-enq",
            "title": "case1",
            "logical_steps": ["step1"],
            "expected_results": ["ok"],
            "review_status": "APPROVED",
        },
    )
    assert r.status_code == 200, r.text
    case_id = r.json()["logical_case_id"]

    # 制品 zip：含 logical_case_id
    suite = tmp_path / "suite"
    suite.mkdir()
    (suite / "c1.tc.yaml").write_text(
        f"name: c1\nlogical_case_id: {case_id}\nsteps: []\n",
        encoding="utf-8",
    )
    sha = hashlib.sha256(b"x").hexdigest()
    manifest = {
        "schema_version": "1.0",
        "artifact_version": "1",
        "project_id": "p-enq",
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
        headers=h,
        files={"file": ("suite.zip", buf.getvalue(), "application/zip")},
        data={"name": "suite", "project_id": "p-enq"},
    )
    assert r.status_code == 200, r.text
    aid = r.json()["id"]

    r = client.post(
        "/api/v1/design/logical-cases/enqueue-job",
        headers=h,
        json={
            "project_id": "p-enq",
            "artifact_id": aid,
            "logical_case_ids": [case_id],
            "platform": "android",
            "name": "from-approved",
            "backend_mode": "uia2",
            "wda_bundle": "",
            "parallel": True,
            "parallel_workers": 2,
            "preferred_runner_id": None,
        },
    )
    assert r.status_code == 200, r.text
    job = r.json()
    assert job["status"] == "pending"
    assert job["artifact_id"] == aid
    assert "c1.tc.yaml" in (job.get("entry_paths") or [])
    assert job.get("backend_mode") == "uia2"
    assert job.get("parallel") is True
    assert job.get("parallel_workers") == 2
    warns = job.get("warnings") or []
    assert any("Binding" in str(w) for w in warns)
    assert any("应用资源" in str(w) for w in warns)


def test_enqueue_approved_job_web_engine_playwright(client: TestClient, tmp_path):
    h = _admin(client)
    r = client.post(
        "/api/v1/design/logical-cases",
        headers=h,
        json={
            "project_id": "p-enq-web",
            "title": "web-case",
            "logical_steps": ["open"],
            "expected_results": ["ok"],
            "review_status": "APPROVED",
        },
    )
    assert r.status_code == 200, r.text
    case_id = r.json()["logical_case_id"]

    suite = tmp_path / "suite"
    suite.mkdir()
    (suite / "c1.tc.yaml").write_text(
        f"name: c1\nlogical_case_id: {case_id}\nsteps: []\n",
        encoding="utf-8",
    )
    sha = hashlib.sha256(b"x").hexdigest()
    manifest = {
        "schema_version": "1.0",
        "artifact_version": "1",
        "project_id": "p-enq-web",
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
        headers=h,
        files={"file": ("suite.zip", buf.getvalue(), "application/zip")},
        data={"name": "suite", "project_id": "p-enq-web"},
    )
    assert r.status_code == 200, r.text
    aid = r.json()["id"]

    r = client.post(
        "/api/v1/design/logical-cases/enqueue-job",
        headers=h,
        json={
            "project_id": "p-enq-web",
            "artifact_id": aid,
            "logical_case_ids": [case_id],
            "platform": "web",
            "web_engine": "playwright",
            "name": "from-approved-web",
        },
    )
    assert r.status_code == 200, r.text
    job = r.json()
    assert job.get("web_engine") == "playwright"
    assert job.get("platform") == "web"


def test_schedule_fire_preserves_web_engine(client: TestClient):
    h = _admin(client)
    r = client.post(
        "/api/v1/schedules",
        headers=h,
        json={ "project_id": "p-mc",
            "name": "web-pw",
            "project_dir": "/tmp/web-suite",
            "platform": "web",
            "backend_mode": "chrome",
            "web_engine": "playwright",
            "delay_sec": 0,
            "interval_sec": 0,
            "repeat": 1,
            "enabled": True,
        },
    )
    assert r.status_code == 200, r.text
    sid = r.json()["id"]
    assert r.json().get("web_engine") == "playwright"

    r = client.post(f"/api/v1/schedules/{sid}/run-now", headers=h)
    assert r.status_code == 200, r.text
    jid = r.json().get("last_job_id")
    assert jid
    r = client.get(f"/api/v1/jobs/{jid}", headers=h)
    assert r.status_code == 200
    assert r.json().get("web_engine") == "playwright"
    assert r.json().get("platform") == "web"


def test_schedule_create_http_strips_mobile_and_fire_keeps_profile(client: TestClient):
    h = _admin(client)
    r = client.post(
        "/api/v1/schedules",
        headers=h,
        json={
            "project_id": "p-mc",
            "name": "http-nightly",
            "project_dir": "/tmp/http-suite",
            "platform": "http",
            "backend_mode": "staging",
            "web_engine": "playwright",
            "device_udids": ["should-strip"],
            "parallel": True,
            "parallel_workers": 4,
            "wda_bundle": "com.should.not",
            "delay_sec": 0,
            "interval_sec": 0,
            "repeat": 1,
            "enabled": True,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    sid = body["id"]
    assert body.get("platform") == "http"
    assert body.get("backend_mode") == "staging"
    assert body.get("web_engine") == "selenium"
    assert body.get("device_udids") == []
    assert body.get("parallel") is False
    assert body.get("parallel_workers") == 0
    assert body.get("wda_bundle") in ("", None)

    r = client.post(f"/api/v1/schedules/{sid}/run-now", headers=h)
    assert r.status_code == 200, r.text
    jid = r.json().get("last_job_id")
    assert jid
    r = client.get(f"/api/v1/jobs/{jid}", headers=h)
    assert r.status_code == 200
    job = r.json()
    assert job.get("platform") == "http"
    assert job.get("backend_mode") == "staging"
    assert job.get("device_udids") == []
    assert job.get("web_engine") == "selenium"


def test_schedule_create_mobile_backend_and_workers(client: TestClient):
    h = _admin(client)
    r = client.post(
        "/api/v1/schedules",
        headers=h,
        json={
            "project_id": "p-mc",
            "name": "ios-nightly",
            "project_dir": "/tmp/ios-suite",
            "platform": "ios",
            "backend_mode": "wda",
            "wda_bundle": "com.example.WebDriverAgentRunner",
            "parallel": True,
            "parallel_workers": 3,
            "delay_sec": 0,
            "interval_sec": 0,
            "repeat": 1,
            "enabled": True,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("backend_mode") == "wda"
    assert body.get("wda_bundle") == "com.example.WebDriverAgentRunner"
    assert body.get("parallel") is True
    assert body.get("parallel_workers") == 3

    r = client.post(f"/api/v1/schedules/{body['id']}/run-now", headers=h)
    assert r.status_code == 200, r.text
    jid = r.json().get("last_job_id")
    assert jid
    job = client.get(f"/api/v1/jobs/{jid}", headers=h).json()
    assert job.get("backend_mode") == "wda"
    assert job.get("wda_bundle") == "com.example.WebDriverAgentRunner"
    assert job.get("parallel_workers") == 3


def test_job_create_non_web_forces_selenium_engine(client: TestClient):
    h = _admin(client)
    r = client.post(
        "/api/v1/jobs",
        headers=h,
        json={ "project_id": "p-mc",
            "name": "android-no-pw",
            "project_dir": "/tmp/suite",
            "platform": "android",
            "web_engine": "playwright",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json().get("web_engine") == "selenium"


def test_ops_runtime_version(client: TestClient):
    h = _admin(client)
    r = client.get("/api/v1/ops/runtime-version", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("ap_version")
    assert "runtime_pin" in body
    assert body.get("contract_runtime_version") == "0.1.0"
    assert "intent_binding_status_v1" in body.get("capabilities", [])


def test_runtime_version_is_safe_for_logged_in_user(client: TestClient):
    h = _admin(client)
    client.post(
        "/api/v1/auth/users",
        headers=h,
        json={"username": "runtime-user", "password": "Runtime123", "duty": "user"},
    )
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "runtime-user", "password": "Runtime123"},
    )
    uh = {"Authorization": f"Bearer {login.json()['access_token']}"}
    r = client.get("/api/v1/ops/runtime-version", headers=uh)
    assert r.status_code == 200, r.text
    assert "ap_version" in r.json()
    assert "MC_" not in r.text


def test_platform_admin_issues_project_scoped_runner_token(client: TestClient):
    h = _admin(client)
    assert client.post(
        "/api/v1/orgs", headers=h, json={"id": "org-scope", "name": "Scope"}
    ).status_code == 200
    assert client.post(
        "/api/v1/projects",
        headers={**h, "X-Org-Id": "org-scope"},
        json={"id": "scope-project", "name": "Scope", "org_id": "org-scope"},
    ).status_code == 200
    assert client.post(
        "/api/v1/auth/users",
        headers=h,
        json={"username": "runner-user", "password": "Runner123", "duty": "user"},
    ).status_code == 200
    assert client.post(
        "/api/v1/projects/scope-project/members",
        headers=h,
        json={"username": "runner-user", "role": "member"},
    ).status_code == 200
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "runner-user", "password": "Runner123"},
    ).json()
    uh = {"Authorization": f"Bearer {login['access_token']}"}
    assert client.post(
        "/api/v1/runners/register",
        headers=uh,
        json={
            "runner_id": "ide-scope-runner",
            "hostname": "ide",
            "registration_source": "ide",
        },
    ).status_code == 200
    denied = client.post(
        "/api/v1/runners/ide-scope-runner/scoped-token",
        headers=uh,
        json={"org_id": "", "project_ids": ["scope-project"]},
    )
    assert denied.status_code == 403, denied.text
    issued = client.post(
        "/api/v1/runners/ide-scope-runner/scoped-token",
        headers=h,
        json={"org_id": "", "project_ids": ["scope-project"]},
    )
    assert issued.status_code == 200, issued.text
    assert issued.json()["project_ids"] == ["scope-project"]
    token_h = {"X-API-Token": issued.json()["api_token"]}
    listed = client.get("/api/v1/runners", headers=token_h)
    assert [x["runner_id"] for x in page_items(listed.json())] == ["ide-scope-runner"]


def test_platform_admin_issues_org_scoped_runner_token(client: TestClient):
    h = _admin(client)
    assert client.post(
        "/api/v1/orgs", headers=h, json={"id": "org-ide-runner", "name": "IDE"}
    ).status_code == 200
    assert client.post(
        "/api/v1/runners/register",
        headers=h,
        json={
            "runner_id": "ide-org-runner",
            "hostname": "ide",
            "registration_source": "ide",
        },
    ).status_code == 200
    empty = client.post(
        "/api/v1/runners/ide-org-runner/scoped-token",
        headers=h,
        json={"org_id": "", "project_ids": []},
    )
    assert empty.status_code == 400, empty.text
    issued = client.post(
        "/api/v1/runners/ide-org-runner/scoped-token",
        headers=h,
        json={"org_id": "org-ide-runner", "project_ids": []},
    )
    assert issued.status_code == 200, issued.text
    assert issued.json()["org_id"] == "org-ide-runner"
    assert issued.json()["project_ids"] == []


def test_result_json_binding_and_mapping_statuses(client: TestClient):
    h = _admin(client)
    ids: dict[str, str] = {}
    for title in ("partial", "mapping"):
        row = client.post(
            "/api/v1/design/logical-cases",
            headers=h,
            json={
                "project_id": "p-status",
                "title": title,
                "logical_steps": ["step"],
                "expected_results": ["ok"],
                "review_status": "APPROVED",
                "automation_status": "PENDING_VERIFY",
            },
        )
        assert row.status_code == 200, row.text
        ids[title] = row.json()["logical_case_id"]

    from autopilot_platform.platform.core.db import get_session
    from autopilot_platform.platform.services.design.automation_sync import (
        apply_result_json_to_logical_cases,
    )

    session_iter = get_session()
    db = next(session_iter)
    try:
        result = apply_result_json_to_logical_cases(
            db,
            {
                "cases": [
                    {
                        "logical_case_id": ids["partial"],
                        "status": "passed",
                        "automation_status_evidence": "BINDING_PARTIAL",
                        "steps": [
                            {
                                "intent_id": "i1",
                                "binding_hit": "failed",
                                "status": "FAIL",
                            }
                        ],
                    },
                    {
                        "logical_case_id": ids["mapping"],
                        "status": "failed",
                        "mapping_required": True,
                        "automation_status_evidence": "MAPPING_REQUIRED",
                    },
                ]
            },
        )
        assert result["updated"] == 2
        db.commit()
    finally:
        session_iter.close()
    assert client.get(
        f"/api/v1/design/logical-cases/{ids['partial']}", headers=h
    ).json()["automation_status"] == "BINDING_PARTIAL"
    assert client.get(
        f"/api/v1/design/logical-cases/{ids['mapping']}", headers=h
    ).json()["automation_status"] == "MAPPING_REQUIRED"


def test_result_json_skips_cross_project_cases(client: TestClient):
    h = _admin(client)
    own = client.post(
        "/api/v1/design/logical-cases",
        headers=h,
        json={
            "project_id": "p-own",
            "title": "own",
            "logical_steps": ["step"],
            "expected_results": ["ok"],
            "review_status": "APPROVED",
            "automation_status": "PENDING_VERIFY",
        },
    )
    assert own.status_code == 200, own.text
    other = client.post(
        "/api/v1/design/logical-cases",
        headers=h,
        json={
            "project_id": "p-other",
            "title": "other",
            "logical_steps": ["step"],
            "expected_results": ["ok"],
            "review_status": "APPROVED",
            "automation_status": "PENDING_VERIFY",
        },
    )
    assert other.status_code == 200, other.text
    own_id = own.json()["logical_case_id"]
    other_id = other.json()["logical_case_id"]

    from autopilot_platform.platform.core.db import get_session
    from autopilot_platform.platform.services.design.automation_sync import (
        apply_result_json_to_logical_cases,
    )

    session_iter = get_session()
    db = next(session_iter)
    try:
        result = apply_result_json_to_logical_cases(
            db,
            {
                "cases": [
                    {
                        "logical_case_id": own_id,
                        "status": "passed",
                        "automation_status_evidence": "EXECUTABLE",
                    },
                    {
                        "logical_case_id": other_id,
                        "status": "passed",
                        "automation_status_evidence": "EXECUTABLE",
                    },
                ]
            },
            project_id="p-own",
        )
        assert result["updated"] == 1
        assert any(d.get("action") == "skip_project_mismatch" for d in result["details"])
        db.commit()
    finally:
        session_iter.close()
    assert client.get(
        f"/api/v1/design/logical-cases/{own_id}", headers=h
    ).json()["automation_status"] == "EXECUTABLE"
    assert client.get(
        f"/api/v1/design/logical-cases/{other_id}", headers=h
    ).json()["automation_status"] == "PENDING_VERIFY"


def test_result_json_pending_verify_on_missing_verification(client: TestClient):
    h = _admin(client)
    row = client.post(
        "/api/v1/design/logical-cases",
        headers=h,
        json={
            "project_id": "p-verify",
            "title": "unverified",
            "logical_steps": ["click"],
            "expected_results": ["ok"],
            "review_status": "APPROVED",
            "automation_status": "INTENT_READY",
        },
    )
    assert row.status_code == 200, row.text
    lc_id = row.json()["logical_case_id"]

    from autopilot_platform.platform.core.db import get_session
    from autopilot_platform.platform.services.design.automation_sync import (
        apply_result_json_to_logical_cases,
    )

    session_iter = get_session()
    db = next(session_iter)
    try:
        result = apply_result_json_to_logical_cases(
            db,
            {
                "cases": [
                    {
                        "logical_case_id": lc_id,
                        "status": "passed",
                        "automation_status_evidence": "EXECUTABLE",
                        "steps": [
                            {
                                "intent_id": "s1",
                                "binding_hit": "cache",
                                "status": "PASS",
                                "verification_status": "missing",
                            }
                        ],
                    }
                ]
            },
            project_id="p-verify",
        )
        assert result["updated"] == 1
        db.commit()
    finally:
        session_iter.close()
    assert client.get(
        f"/api/v1/design/logical-cases/{lc_id}", headers=h
    ).json()["automation_status"] == "PENDING_VERIFY"
