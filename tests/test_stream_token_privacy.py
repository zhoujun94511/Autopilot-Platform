"""AUD-P1-002：SSE / query token 隐私与鉴权边界。"""

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

from autopilot_platform.platform.app import create_app
from autopilot_platform.platform.core.db import reset_engine
from autopilot_platform.platform.core.query_privacy import redact_query_string
from autopilot_platform.platform.core.security import create_stream_token, decode_access_token


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "stream_priv.db"
    monkeypatch.setenv("MC_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("MC_APP_BUILDS_DIR", str(tmp_path / "app_builds"))
    monkeypatch.setenv("MC_ADMIN_USER", "admin")
    monkeypatch.setenv("MC_ADMIN_PASSWORD", "admin")
    monkeypatch.setenv("MC_SCHEDULE_ENABLED", "0")
    monkeypatch.setenv("MC_RUNTIME_CONFIG", str(tmp_path / "mc_runtime_config.json"))
    monkeypatch.setenv("MC_JOB_LOGS_DIR", str(tmp_path / "job_logs"))
    monkeypatch.setenv("MC_API_TOKEN", "runner-global-token")
    monkeypatch.setenv("MC_ADMIN_API_TOKEN", "admin-ops-token")
    monkeypatch.setenv("MC_HOST", "127.0.0.1")
    monkeypatch.delenv("MC_ENV", raising=False)
    reset_engine()
    from autopilot_platform.platform.ops.runtime_config import reload_runtime_config

    reload_runtime_config()
    app = create_app(database_url=f"sqlite:///{db_path.as_posix()}")
    with TestClient(app) as c:
        yield c
    reset_engine()
    reload_runtime_config()


def test_redact_query_string_masks_tokens():
    out = redact_query_string(
        b"since=0&access_token=eyJhbGciOiJIUzI1NiJ9.abc&refresh_token=rr"
    ).decode("latin-1")
    assert "access_token=REDACTED" in out
    assert "refresh_token=REDACTED" in out
    assert "since=0" in out
    assert "eyJhbGciOiJIUzI1NiJ9" not in out


def test_query_user_jwt_rejected_on_normal_api(client: TestClient):
    login = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "admin"}
    ).json()
    jwt = login["access_token"]
    # 禁止把完整用户 JWT 放进 Query（即使参数名是 access_token）
    r = client.get(f"/api/v1/auth/me?access_token={jwt}")
    assert r.status_code == 401
    # Header 仍可用
    assert (
        client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {jwt}"}).status_code
        == 200
    )


def test_stream_token_default_ttl_is_two_minutes(monkeypatch):
    monkeypatch.delenv("MC_STREAM_TOKEN_MINUTES", raising=False)
    monkeypatch.setenv("MC_JWT_SECRET", "unit-test-jwt-secret-not-default-32b")
    tok = create_stream_token(
        sub="u1", role="admin", username="admin", job_id="job-1"
    )
    payload = decode_access_token(tok)
    assert payload["typ"] == "job_log_stream"
    assert payload["job_id"] == "job-1"
    exp = int(payload["exp"])
    iat = int(payload["iat"])
    assert 60 <= (exp - iat) <= 150  # ~2 minutes


def test_stream_token_endpoint_expires_in_matches_settings(client: TestClient, monkeypatch):
    monkeypatch.setenv("MC_STREAM_TOKEN_MINUTES", "3")
    admin = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "admin"}
    ).json()
    ah = {"Authorization": f"Bearer {admin['access_token']}"}
    job = client.post(
        "/api/v1/jobs",
        headers={"X-API-Token": "admin-ops-token"},
        json={ "project_id": "p-mc","name": "s", "project_dir": "/tmp", "platform": "web"},
    ).json()
    r = client.post(f"/api/v1/jobs/{job['id']}/logs/stream-token", headers=ah)
    assert r.status_code == 200
    body = r.json()
    assert body["expires_in"] == 180
    assert body.get("token_type") == "job_log_stream"
    assert decode_access_token(body["access_token"])["job_id"] == job["id"]


def test_device_log_stream_token_is_distinct_from_job_and_user_jwt(monkeypatch):
    from autopilot_platform.platform.core.security import create_device_log_stream_token

    monkeypatch.setenv("MC_JWT_SECRET", "unit-test-jwt-secret-not-default-32b")
    tok = create_device_log_stream_token(
        sub="u1", role="admin", username="admin", session_id="sess-1"
    )
    payload = decode_access_token(tok)
    assert payload["typ"] == "device_log_stream"
    assert payload["purpose"] == "device_log_stream"
    assert payload["session_id"] == "sess-1"
    assert "job_id" not in payload
