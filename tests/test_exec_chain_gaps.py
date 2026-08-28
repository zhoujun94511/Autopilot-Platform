"""上一轮执行链审计软缺口：result.json 假成功、enqueue zip 回退、应用资源软警告。"""

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
from autopilot_platform.platform.core.db import reset_engine, session_factory
from autopilot_platform.platform.core.models import ArtifactRow
from autopilot_platform.runner.contract import JobOut, JobStatus
from autopilot_platform.runner.execute import execute_job


class _FakeSuite:
    name = "Suite"
    duration_ms = 12
    results: list = []

    @staticmethod
    def case_counts() -> dict:
        return {"passed": 1, "failed": 0, "total": 1}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "mc_gaps.db"
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


def _zip_artifact(tmp_path: Path, *, project_id: str, case_id: str) -> bytes:
    suite = tmp_path / "suite"
    suite.mkdir()
    (suite / "c1.tc.yaml").write_text(
        f"name: c1\nlogical_case_id: {case_id}\nsteps: []\n",
        encoding="utf-8",
    )
    manifest = {
        "schema_version": "1.0",
        "artifact_version": "1",
        "project_id": project_id,
        "sha256": hashlib.sha256(b"x").hexdigest(),
        "required_runtime_version": "0.1.0-vendored",
        "required_capabilities": [],
        "case_index": [{"relative_path": "c1.tc.yaml", "logical_case_id": case_id}],
    }
    (suite / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.write(suite / "c1.tc.yaml", "c1.tc.yaml")
        zf.write(suite / "manifest.json", "manifest.json")
    return buf.getvalue()


def test_android_job_warns_without_app_build(client: TestClient, tmp_path):
    h = _admin(client)
    r = client.post(
        "/api/v1/artifacts",
        headers=h,
        files={"file": ("suite.zip", _zip_artifact(tmp_path, project_id="p-app", case_id="lc-1"), "application/zip")},
        data={"name": "suite", "project_id": "p-app"},
    )
    assert r.status_code == 200, r.text
    aid = r.json()["id"]
    r = client.post(
        "/api/v1/jobs",
        headers=h,
        json={"name": "mobile", "artifact_id": aid, "project_id": "p-app", "platform": "android"},
    )
    assert r.status_code == 200, r.text
    warns = r.json().get("warnings") or []
    assert any("应用资源" in str(w) for w in warns)

    r = client.post(
        "/api/v1/jobs",
        headers=h,
        json={"name": "web", "artifact_id": aid, "project_id": "p-app", "platform": "web"},
    )
    assert r.status_code == 200, r.text
    web_warns = r.json().get("warnings") or []
    assert not any("应用资源" in str(w) and "未指定" in str(w) for w in web_warns)


def test_enqueue_resolves_entries_from_zip_when_extract_missing(client: TestClient, tmp_path):
    h = _admin(client)
    r = client.post(
        "/api/v1/design/logical-cases",
        headers=h,
        json={
            "project_id": "p-zip",
            "title": "login",
            "logical_steps": ["open"],
            "expected_results": ["ok"],
            "review_status": "APPROVED",
        },
    )
    assert r.status_code == 200, r.text
    case_id = r.json()["logical_case_id"]
    r = client.post(
        "/api/v1/artifacts",
        headers=h,
        files={
            "file": (
                "suite.zip",
                _zip_artifact(tmp_path, project_id="p-zip", case_id=case_id),
                "application/zip",
            )
        },
        data={"name": "suite", "project_id": "p-zip"},
    )
    assert r.status_code == 200, r.text
    aid = r.json()["id"]
    factory = session_factory()
    assert factory is not None
    db = factory()
    try:
        row = db.get(ArtifactRow, aid)
        assert row is not None
        row.extract_path = str(tmp_path / "missing-extract")
        db.commit()
    finally:
        db.close()
    r = client.post(
        "/api/v1/design/logical-cases/enqueue-job",
        headers=h,
        json={
            "project_id": "p-zip",
            "artifact_id": aid,
            "logical_case_ids": [case_id],
            "platform": "android",
            "name": "from-zip",
        },
    )
    assert r.status_code == 200, r.text
    assert "c1.tc.yaml" in (r.json().get("entry_paths") or [])


def test_xapk_upload_accepted_as_android(client: TestClient):
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "manifest.json",
            '{"package_name":"com.demo.app","version_name":"2.1.0","version_code":21}',
        )
    payload = buf.getvalue()
    r = client.post(
        "/api/v1/app-builds",
        headers=_admin(client),
        files={"file": ("demo.xapk", payload, "application/octet-stream")},
        data={"name": "xapk-demo", "project_id": "p-app"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["platform"] == "android"
    assert body["filename"] == "demo.xapk"
    assert body["package_id"] == "com.demo.app"
    assert body["version_name"] == "2.1.0"
    assert int(body["version_code"] or 0) == 21


def test_job_echoes_pinned_app_build_version(client: TestClient, tmp_path):
    h = _admin(client)
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "manifest.json",
            '{"package_name":"com.demo.pin","version_name":"9.9.9","version_code":99}',
        )
    r = client.post(
        "/api/v1/app-builds",
        headers=h,
        files={"file": ("pin.xapk", buf.getvalue(), "application/octet-stream")},
        data={"name": "pin-app", "project_id": "p-pin"},
    )
    assert r.status_code == 200, r.text
    bid = r.json()["id"]
    r = client.post(
        "/api/v1/artifacts",
        headers=h,
        files={
            "file": (
                "suite.zip",
                _zip_artifact(tmp_path, project_id="p-pin", case_id="lc-pin"),
                "application/zip",
            )
        },
        data={"name": "suite", "project_id": "p-pin"},
    )
    assert r.status_code == 200, r.text
    aid = r.json()["id"]
    r = client.post(
        "/api/v1/jobs",
        headers=h,
        json={
            "name": "pin",
            "artifact_id": aid,
            "app_build_id": bid,
            "project_id": "p-pin",
            "platform": "android",
        },
    )
    assert r.status_code == 200, r.text
    job = r.json()
    assert job["app_build_id"] == bid
    assert job["app_build_name"] == "pin-app"
    assert job["app_version_name"] == "9.9.9"
    assert job["app_package_id"] == "com.demo.pin"
    warns = job.get("warnings") or []
    assert not any("未指定" in str(w) for w in warns)
    r = client.get(f"/api/v1/jobs/{job['id']}", headers=h)
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["app_build_name"] == "pin-app"
    assert got["app_version_name"] == "9.9.9"
    assert got["app_package_id"] == "com.demo.pin"


def test_job_warns_when_app_build_project_differs(client: TestClient, tmp_path):
    h = _admin(client)
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "manifest.json",
            '{"package_name":"com.demo.share","version_name":"1.0.0","version_code":1}',
        )
    r = client.post(
        "/api/v1/app-builds",
        headers=h,
        files={"file": ("share.xapk", buf.getvalue(), "application/octet-stream")},
        data={"name": "share-app", "project_id": "p-share-app"},
    )
    assert r.status_code == 200, r.text
    bid = r.json()["id"]
    r = client.post(
        "/api/v1/artifacts",
        headers=h,
        files={
            "file": (
                "suite.zip",
                _zip_artifact(tmp_path, project_id="p-share-job", case_id="lc-share"),
                "application/zip",
            )
        },
        data={"name": "suite", "project_id": "p-share-job"},
    )
    assert r.status_code == 200, r.text
    aid = r.json()["id"]
    r = client.post(
        "/api/v1/jobs",
        headers=h,
        json={
            "name": "share",
            "artifact_id": aid,
            "app_build_id": bid,
            "project_id": "p-share-job",
            "platform": "android",
        },
    )
    assert r.status_code == 200, r.text
    job = r.json()
    assert job["app_build_id"] == bid
    assert job["status"] == "pending"
    warns = job.get("warnings") or []
    assert any("p-share-app" in str(w) and "p-share-job" in str(w) for w in warns)


def test_execute_job_result_json_write_failure_fails_job(tmp_path, monkeypatch):
    proj = tmp_path / "p"
    proj.mkdir()
    (proj / "c.tc.yaml").write_text("name: c\nsteps: []\n", encoding="utf-8")
    monkeypatch.setattr(
        "autopilot_platform.ap.engine.run_project_directory",
        lambda *_a, **_k: _FakeSuite(),
    )
    monkeypatch.setattr("autopilot_platform.ap.report.write_report", lambda *_a, **_k: None)

    def _boom(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(
        "autopilot_platform.ap.report.result_json.write_result_json",
        _boom,
    )
    job = JobOut(
        id="j-result",
        name="n",
        status=JobStatus.CLAIMED,
        project_dir=str(proj),
        platform="web",
    )
    result = execute_job(job)
    assert result.status == JobStatus.FAILED
    assert "result.json" in (result.error or "")


def test_execute_job_logs_missing_app_build(tmp_path, monkeypatch):
    proj = tmp_path / "p"
    proj.mkdir()
    (proj / "c.tc.yaml").write_text("name: c\nsteps: []\n", encoding="utf-8")
    monkeypatch.setattr(
        "autopilot_platform.ap.engine.run_project_directory",
        lambda *_a, **_k: _FakeSuite(),
    )
    monkeypatch.setattr("autopilot_platform.ap.report.write_report", lambda *_a, **_k: None)
    monkeypatch.setattr(
        "autopilot_platform.ap.report.result_json.write_result_json",
        lambda *_a, **_k: None,
    )
    job = JobOut(
        id="j-app",
        name="n",
        status=JobStatus.CLAIMED,
        project_dir=str(proj),
        platform="android",
    )
    result = execute_job(job)
    assert "未指定 app_build_id" in (result.log or "")
