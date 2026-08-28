"""Access + Refresh Token 轮换与吊销。"""

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


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "mc_test.db"
    url = f"sqlite:///{db_path.as_posix()}"
    monkeypatch.setenv("MC_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("MC_ADMIN_USER", "admin")
    monkeypatch.setenv("MC_ADMIN_PASSWORD", "admin")
    monkeypatch.setenv("MC_ACCESS_TOKEN_MINUTES", "30")
    monkeypatch.setenv("MC_REFRESH_TOKEN_DAYS", "7")
    monkeypatch.setenv("MC_SCHEDULE_ENABLED", "0")
    monkeypatch.setenv("MC_RUNTIME_CONFIG", str(tmp_path / "mc_runtime_config.json"))
    monkeypatch.setenv("MC_JOB_LOGS_DIR", str(tmp_path / "job_logs"))
    monkeypatch.setenv("MC_DATA_DIR", str(tmp_path / "data"))
    reset_engine()
    from autopilot_platform.platform.ops.runtime_config import reload_runtime_config

    reload_runtime_config()
    app = create_app(database_url=url)
    with TestClient(app) as c:
        yield c
    reset_engine()
    reload_runtime_config()


def test_ide_handoff_code_is_single_use(client: TestClient):
    from autopilot_platform.platform.identity import ide_handoff

    ide_handoff.reset_for_tests()
    login = client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin"})
    assert login.status_code == 200
    token = login.json()["access_token"]
    issued = client.post(
        "/api/v1/auth/ide-handoff",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert issued.status_code == 200
    code = issued.json()["code"]
    assert code
    assert "access_token" not in issued.json()
    first = client.post("/api/v1/auth/ide-handoff/consume", json={"code": code})
    assert first.status_code == 200
    assert first.json()["access_token"]
    assert first.json()["user"]["username"] == "admin"
    second = client.post("/api/v1/auth/ide-handoff/consume", json={"code": code})
    assert second.status_code == 401


def test_login_refresh_logout_cycle(client: TestClient):
    r = client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["expires_in"] == 30 * 60
    old_refresh = body["refresh_token"]
    access = body["access_token"]
    # AUD-2026-02-C：登录同时下发 HttpOnly Cookie
    assert "mc_refresh=" in (r.headers.get("set-cookie") or "")
    assert "HttpOnly" in (r.headers.get("set-cookie") or "")

    r = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {access}"})
    assert r.status_code == 200
    assert r.json()["username"] == "admin"

    r = client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})
    assert r.status_code == 200, r.text
    new_body = r.json()
    assert new_body["refresh_token"]
    assert new_body["refresh_token"] != old_refresh
    assert new_body["access_token"]

    # 旧 refresh 不可再用
    r = client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})
    assert r.status_code == 401

    # logout 吊销新 refresh
    r = client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": new_body["refresh_token"]},
    )
    assert r.status_code == 204
    r = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": new_body["refresh_token"]},
    )
    assert r.status_code == 401


def test_refresh_and_logout_via_httponly_cookie(client: TestClient):
    """AUD-2026-02-C：空 body + Cookie 可换票；logout 清 Cookie。"""
    r = client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin"})
    assert r.status_code == 200
    assert client.cookies.get("mc_refresh")

    r = client.post("/api/v1/auth/refresh", json={})
    assert r.status_code == 200, r.text
    assert r.json()["access_token"]
    assert client.cookies.get("mc_refresh")
    assert r.json()["refresh_token"] == client.cookies.get("mc_refresh")

    r = client.post("/api/v1/auth/logout", json={})
    assert r.status_code == 204
    # TestClient 可能仍持有过期 cookie；以无法再 refresh 为准
    r = client.post("/api/v1/auth/refresh", json={})
    assert r.status_code == 401
