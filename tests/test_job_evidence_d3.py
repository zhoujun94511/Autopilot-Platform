"""D3：evidence.zip 上传与安全路径解析。"""

from __future__ import annotations

import io
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

from autopilot_platform.platform.app import create_app
from autopilot_platform.platform.core.db import reset_engine


TOKEN = {"X-API-Token": "runner-global-token"}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "ev.db"
    url = f"sqlite:///{db_path.as_posix()}"
    monkeypatch.setenv("MC_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("MC_APP_BUILDS_DIR", str(tmp_path / "app_builds"))
    monkeypatch.setenv("MC_ADMIN_USER", "admin")
    monkeypatch.setenv("MC_ADMIN_PASSWORD", "admin")
    monkeypatch.setenv("MC_SCHEDULE_ENABLED", "0")
    monkeypatch.setenv("MC_RUNTIME_CONFIG", str(tmp_path / "mc_runtime_config.json"))
    monkeypatch.setenv("MC_JOB_LOGS_DIR", str(tmp_path / "job_logs"))
    monkeypatch.setenv("MC_REPORTS_DIR", str(tmp_path / "reports"))
    monkeypatch.setenv("MC_API_TOKEN", "runner-global-token")
    monkeypatch.setenv("MC_ADMIN_API_TOKEN", "admin-ops-token")
    monkeypatch.delenv("MC_ENV", raising=False)
    reset_engine()
    from autopilot_platform.platform.ops.runtime_config import reload_runtime_config

    reload_runtime_config()
    app = create_app(database_url=url)
    with TestClient(app) as c:
        yield c
    reset_engine()
    reload_runtime_config()


def _ah(client: TestClient) -> dict:
    login = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "admin"}
    ).json()
    return {"Authorization": f"Bearer {login['access_token']}"}


def test_upload_and_get_evidence(client: TestClient):
    ah = _ah(client)
    client.post(
        "/api/v1/runners/heartbeat",
        headers=TOKEN,
        json={"runner_id": "r-ev", "inventory": [], "devices": [], "capabilities": ["web"]},
    )
    job = client.post(
        "/api/v1/jobs",
        headers=ah,
        json={ "project_id": "p-mc",
            "name": "ev",
            "project_dir": "/tmp/ev",
            "platform": "web",
            "preferred_runner_id": "r-ev",
        },
    ).json()
    claimed = client.post(
        "/api/v1/jobs/claim?runner_id=r-ev", headers=TOKEN
    ).json()
    assert claimed["id"] == job["id"]

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("reports/evidence/c1/s1/screenshot.png", b"\x89PNGFAKE")
    buf.seek(0)
    up = client.post(
        f"/api/v1/jobs/{job['id']}/report?runner_id=r-ev",
        headers=TOKEN,
        files={"file": ("evidence.zip", buf.getvalue(), "application/zip")},
    )
    assert up.status_code == 200, up.text

    got = client.get(
        f"/api/v1/jobs/{job['id']}/evidence/c1/s1/screenshot.png",
        headers=ah,
    )
    assert got.status_code == 200
    assert got.content.startswith(b"\x89PNG")
    assert "image/png" in (got.headers.get("content-type") or "")

    # 路径穿越拒绝
    bad = client.get(
        f"/api/v1/jobs/{job['id']}/evidence/../result.json",
        headers=ah,
    )
    assert bad.status_code == 404


def test_evidence_list_and_mp4_mime(client: TestClient):
    ah = _ah(client)
    client.post(
        "/api/v1/runners/heartbeat",
        headers=TOKEN,
        json={"runner_id": "r-ev2", "inventory": [], "devices": [], "capabilities": ["android"]},
    )
    job = client.post(
        "/api/v1/jobs",
        headers=ah,
        json={ "project_id": "p-mc",
            "name": "ev-mp4",
            "project_dir": "/tmp/ev-mp4",
            "platform": "android",
            "preferred_runner_id": "r-ev2",
        },
    ).json()
    claimed = client.post(
        "/api/v1/jobs/claim?runner_id=r-ev2", headers=TOKEN
    ).json()
    assert claimed["id"] == job["id"]

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("reports/evidence/screen_record_demo.mp4", b"\x00\x00\x00\x18ftypmp42")
        zf.writestr("reports/evidence/c1/s1/screenshot.png", b"\x89PNGFAKE")
    buf.seek(0)
    up = client.post(
        f"/api/v1/jobs/{job['id']}/report?runner_id=r-ev2",
        headers=TOKEN,
        files={"file": ("evidence.zip", buf.getvalue(), "application/zip")},
    )
    assert up.status_code == 200, up.text

    listed = client.get(f"/api/v1/jobs/{job['id']}/evidence", headers=ah)
    assert listed.status_code == 200, listed.text
    body = listed.json()
    paths = {f["path"] for f in body.get("files") or []}
    kinds = {f["path"]: f.get("kind") for f in body.get("files") or []}
    assert "screen_record_demo.mp4" in paths
    assert kinds.get("screen_record_demo.mp4") == "video"
    assert "c1/s1/screenshot.png" in paths

    vid = client.get(
        f"/api/v1/jobs/{job['id']}/evidence/screen_record_demo.mp4",
        headers=ah,
    )
    assert vid.status_code == 200
    assert "video/mp4" in (vid.headers.get("content-type") or "")
    assert vid.content.startswith(b"\x00\x00\x00\x18ftyp")
