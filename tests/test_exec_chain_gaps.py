"""上一轮执行链审计软缺口：result.json 假成功、enqueue zip 回退、应用资源软警告。"""

from __future__ import annotations

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
    from autopilot_platform.platform.artifacts.artifact_manifest import (
        compute_artifact_content_sha256,
    )

    manifest = {
        "schema_version": "1.0",
        "artifact_version": "1",
        "project_id": project_id,
        "sha256": compute_artifact_content_sha256(suite),
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


def _zip_members(members: dict[str, bytes], *, when: tuple[int, int, int, int, int, int]) -> bytes:
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, payload in members.items():
            zf.writestr(zipfile.ZipInfo(name, date_time=when), payload)
    return buf.getvalue()


def test_artifact_reused_when_zip_timestamp_differs(client: TestClient):
    """同一工程重新打包只改 zip 时间戳，应复用已有 artifact_id。"""
    members = {"c1.tc.yaml": b"name: c1\nsteps: []\n"}
    first = _zip_members(members, when=(2020, 1, 1, 0, 0, 0))
    second = _zip_members(members, when=(2024, 6, 1, 12, 0, 0))
    assert first != second
    h = _admin(client)
    r = client.post(
        "/api/v1/artifacts",
        headers=h,
        files={"file": ("suite.zip", first, "application/zip")},
        data={"name": "suite", "project_id": "p-dedup"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("reused") is False
    aid = body["id"]
    r = client.post(
        "/api/v1/artifacts",
        headers=h,
        files={"file": ("suite.zip", second, "application/zip")},
        data={"name": "suite-again", "project_id": "p-dedup"},
    )
    assert r.status_code == 200, r.text
    again = r.json()
    assert again["id"] == aid
    assert again["reused"] is True


def test_artifact_reused_when_only_manifest_changes(client: TestClient):
    """清单时间戳变化不产生新制品，用例文件相同则复用。"""
    case = b"name: c1\nsteps: []\n"

    def _pack(stamp: str) -> bytes:
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("c1.tc.yaml", case)
            zf.writestr(
                "manifest.json",
                json.dumps({"artifact_version": stamp, "created_at": stamp}),
            )
        return buf.getvalue()

    h = _admin(client)
    first = _pack("2020.01.01")
    second = _pack("2024.06.01")
    assert first != second
    r = client.post(
        "/api/v1/artifacts",
        headers=h,
        files={"file": ("suite.zip", first, "application/zip")},
        data={"name": "suite", "project_id": "p-man"},
    )
    assert r.status_code == 200, r.text
    aid = r.json()["id"]
    r = client.post(
        "/api/v1/artifacts",
        headers=h,
        files={"file": ("suite.zip", second, "application/zip")},
        data={"name": "suite", "project_id": "p-man"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["id"] == aid
    assert r.json()["reused"] is True


def test_job_rejects_invalid_manifest_and_unknown_entry(client: TestClient, tmp_path):
    h = _admin(client)
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "c1.tc.yaml").write_text("name: c1\nsteps: []\n", encoding="utf-8")
    (bad / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "artifact_version": "1",
                "project_id": "p-gate",
                "sha256": "a" * 64,
                "required_runtime_version": "0.1.0-vendored",
                "required_capabilities": [],
            }
        ),
        encoding="utf-8",
    )
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.write(bad / "c1.tc.yaml", "c1.tc.yaml")
        zf.write(bad / "manifest.json", "manifest.json")
    r = client.post(
        "/api/v1/artifacts",
        headers=h,
        files={"file": ("bad.zip", buf.getvalue(), "application/zip")},
        data={"name": "bad", "project_id": "p-gate"},
    )
    assert r.status_code == 200, r.text
    assert r.json().get("manifest_status") == "invalid"
    r = client.post(
        "/api/v1/jobs",
        headers=h,
        json={"name": "bad", "artifact_id": r.json()["id"], "project_id": "p-gate", "platform": "android"},
    )
    assert r.status_code == 400, r.text
    assert "manifest" in r.json()["message"]

    r = client.post(
        "/api/v1/artifacts",
        headers=h,
        files={
            "file": (
                "suite.zip",
                _zip_artifact(tmp_path, project_id="p-entry", case_id="lc-entry"),
                "application/zip",
            )
        },
        data={"name": "suite", "project_id": "p-entry"},
    )
    assert r.status_code == 200, r.text
    aid = r.json()["id"]
    r = client.post(
        "/api/v1/jobs",
        headers=h,
        json={
            "name": "missing-entry",
            "artifact_id": aid,
            "project_id": "p-entry",
            "platform": "android",
            "entry_paths": ["no-such.tc.yaml"],
        },
    )
    assert r.status_code == 400, r.text
    assert "no-such.tc.yaml" in r.json()["message"]


def test_job_rejects_app_build_platform_mismatch(client: TestClient, tmp_path):
    h = _admin(client)
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("Payload/App", b"ios")
    r = client.post(
        "/api/v1/app-builds",
        headers=h,
        files={"file": ("app.ipa", buf.getvalue(), "application/octet-stream")},
        data={"name": "ios-app", "project_id": "p-plat", "platform": "ios"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["platform"] == "ios"
    bid = r.json()["id"]
    r = client.post(
        "/api/v1/artifacts",
        headers=h,
        files={
            "file": (
                "suite.zip",
                _zip_artifact(tmp_path, project_id="p-plat", case_id="lc-plat"),
                "application/zip",
            )
        },
        data={"name": "suite", "project_id": "p-plat"},
    )
    assert r.status_code == 200, r.text
    r = client.post(
        "/api/v1/jobs",
        headers=h,
        json={
            "name": "cross",
            "artifact_id": r.json()["id"],
            "app_build_id": bid,
            "project_id": "p-plat",
            "platform": "android",
        },
    )
    assert r.status_code == 400, r.text
    assert "ios" in r.json()["message"] and "android" in r.json()["message"]


def test_execute_installs_pinned_build_before_cases(tmp_path, monkeypatch):
    proj = tmp_path / "p"
    proj.mkdir()
    (proj / "c.tc.yaml").write_text("name: c\nsteps: []\n", encoding="utf-8")
    apk = tmp_path / "app.apk"
    apk.write_bytes(b"PK")
    order: list[str] = []
    monkeypatch.setattr(
        "autopilot_platform.runner.execute._preflight_devices",
        lambda _job: None,
    )
    monkeypatch.setattr(
        "autopilot_platform.runner.execute._resolve_app_build_path",
        lambda *_a, **_k: (str(apk), None, None),
    )

    def _install(path, serial, replace=True):
        order.append(f"install:{serial}")
        assert replace is True
        assert path == str(apk)

    monkeypatch.setattr(
        "autopilot_platform.ap.mobile.xapk.install_android_package",
        _install,
    )

    def _run(*_a, **_k):
        order.append("run")
        return _FakeSuite()

    monkeypatch.setattr("autopilot_platform.ap.engine.run_project_directory", _run)
    monkeypatch.setattr("autopilot_platform.ap.report.write_report", lambda *_a, **_k: None)
    monkeypatch.setattr(
        "autopilot_platform.ap.report.result_json.write_result_json",
        lambda *_a, **_k: None,
    )
    job = JobOut(
        id="j-install",
        name="n",
        status=JobStatus.CLAIMED,
        project_dir=str(proj),
        platform="android",
        app_build_id="build-1",
        device_udids=["phone-1"],
    )
    result = execute_job(job)
    assert result.status == JobStatus.SUCCEEDED
    assert order == ["install:phone-1", "run"]

    def _boom(*_a, **_k):
        raise RuntimeError("install rejected")

    monkeypatch.setattr(
        "autopilot_platform.ap.mobile.xapk.install_android_package",
        _boom,
    )
    failed = execute_job(job)
    assert failed.status == JobStatus.FAILED
    assert "安装被测包失败" in (failed.error or "")
    assert "device_offline:" not in (failed.error or "")
    assert order == ["install:phone-1", "run"]
