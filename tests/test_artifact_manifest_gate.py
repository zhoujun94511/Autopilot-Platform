"""MC_REQUIRE_ARTIFACT_MANIFEST 门禁。"""

from __future__ import annotations

import io
import hashlib
import json
import os
import sys
import zipfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient

from autopilot_platform.core.constants import DEFAULT_API_TOKEN
from autopilot_platform.platform.app import create_app
from autopilot_platform.platform.core.db import reset_engine

TOKEN = {"X-API-Token": DEFAULT_API_TOKEN}


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
    monkeypatch.setenv("MC_REQUIRE_ARTIFACT_MANIFEST", "0")
    reset_engine()
    from autopilot_platform.platform.ops.runtime_config import reload_runtime_config

    reload_runtime_config()
    app = create_app(database_url=url)
    with TestClient(app) as c:
        yield c
    reset_engine()
    reload_runtime_config()


def _zip_with_manifest(*, project_id: str = "p1") -> bytes:
    buf = io.BytesIO()
    case_data = b"type: testcase\nname: a\n"
    digest = hashlib.sha256()
    digest.update(b"a.tc.yaml\0")
    digest.update(case_data)
    digest.update(b"\0")
    man = {
        "schema_version": "1.0",
        "artifact_version": "1.0.0",
        "project_id": project_id,
        "sha256": digest.hexdigest(),
        "required_runtime_version": "0.1.0",
        "required_capabilities": ["web.selenium"],
        "case_index": [{"relative_path": "a.tc.yaml"}],
    }
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("demo/manifest.json", json.dumps(man))
        zf.writestr("demo/a.tc.yaml", case_data)
    return buf.getvalue()


def test_require_manifest_rejects_missing(client: TestClient, monkeypatch):
    monkeypatch.setenv("MC_REQUIRE_ARTIFACT_MANIFEST", "1")
    from autopilot_platform.platform.ops.runtime_config import reload_runtime_config

    reload_runtime_config()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("demo/a.tc.yaml", "type: testcase\nname: a\n")
    r = client.post(
        "/api/v1/artifacts",
        headers=TOKEN,
        files={"file": ("x.zip", buf.getvalue(), "application/zip")},
        data={"name": "no-man", "project_id": "p1"},
    )
    assert r.status_code == 400
    body = r.json()
    detail = str(body.get("message") or body.get("detail") or "").lower()
    assert "manifest" in detail


def test_require_manifest_accepts_valid(client: TestClient, monkeypatch):
    monkeypatch.setenv("MC_REQUIRE_ARTIFACT_MANIFEST", "1")
    from autopilot_platform.platform.ops.runtime_config import reload_runtime_config

    reload_runtime_config()
    data = _zip_with_manifest(project_id="p1")
    r = client.post(
        "/api/v1/artifacts",
        headers=TOKEN,
        files={"file": ("ok.zip", data, "application/zip")},
        data={"name": "ok-man", "project_id": "p1"},
    )
    assert r.status_code == 200, r.text
    assert r.json().get("manifest_status") == "valid"


def test_manifest_rejects_content_hash_mismatch(tmp_path):
    from autopilot_platform.platform.artifacts.artifact_manifest import validate_artifact_manifest

    (tmp_path / "a.tc.yaml").write_text("changed", encoding="utf-8")
    manifest = {
        "schema_version": "1.0",
        "artifact_version": "1",
        "project_id": "p1",
        "sha256": "a" * 64,
        "required_runtime_version": "0.1.0",
        "required_capabilities": [],
        "case_index": [{"relative_path": "a.tc.yaml"}],
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    result = validate_artifact_manifest(str(tmp_path), expected_project_id="p1")
    assert result["status"] == "invalid"
    assert any("sha256" in item for item in result["errors"])


def test_manifest_gate_rejects_project_id_mismatch(tmp_path, monkeypatch):
    from autopilot_platform.platform.artifacts.artifact_manifest import (
        compute_artifact_content_sha256,
        validate_artifact_manifest,
    )

    monkeypatch.setenv("MC_REQUIRE_ARTIFACT_MANIFEST", "1")
    (tmp_path / "a.tc.yaml").write_text("ok", encoding="utf-8")
    manifest_path = tmp_path / "manifest.json"
    manifest = {
        "schema_version": "1.0",
        "artifact_version": "1",
        "project_id": "other",
        "sha256": compute_artifact_content_sha256(tmp_path),
        "required_runtime_version": "0.1.0",
        "required_capabilities": [],
        "case_index": [{"relative_path": "a.tc.yaml"}],
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    result = validate_artifact_manifest(str(tmp_path), expected_project_id="p1")
    assert result["status"] == "invalid"
    assert any("project_id" in item for item in result["errors"])
