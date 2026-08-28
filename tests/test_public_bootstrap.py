"""公开 Bootstrap API（无需登录）。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from autopilot_platform.platform.app import create_app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("MC_PLATFORM_URL", raising=False)
    monkeypatch.delenv("MC_SERVER", raising=False)
    monkeypatch.delenv("MC_HOST", raising=False)
    monkeypatch.delenv("MC_PORT", raising=False)
    db = tmp_path / "boot.sqlite"
    app = create_app(database_url=f"sqlite:///{db.as_posix()}")
    with TestClient(app) as c:
        yield c


def test_public_bootstrap_no_auth(client: TestClient):
    res = client.get("/api/v1/public/bootstrap")
    assert res.status_code == 200
    body = res.json()
    assert body["schema_version"] == "1"
    assert body["api_prefix"] == "/api/v1"
    assert body["platform_base_url"].startswith("http://")
    assert body["endpoints"]["bootstrap"] == "/api/v1/public/bootstrap"
    assert "--token-env MC_RUNNER_TOKEN" in body["runner"]["cli_command"]
    assert "dev-mc-token" not in body["runner"]["cli_command"]
    # AUD-2026-06：仅布尔，不回显密钥
    assert "insecure_defaults" in body["flags"]
    assert "bind_exposed" in body["flags"]
    assert isinstance(body["flags"]["insecure_defaults"], bool)
    assert isinstance(body["flags"]["bind_exposed"], bool)
    assert "dev-mc-token" not in res.text
    assert "dev-mc-jwt-secret" not in res.text


def test_public_bootstrap_insecure_defaults_flag(tmp_path, monkeypatch):
    monkeypatch.delenv("MC_PLATFORM_URL", raising=False)
    monkeypatch.delenv("MC_SERVER", raising=False)
    monkeypatch.delenv("MC_ENV", raising=False)
    monkeypatch.setenv("MC_HOST", "127.0.0.1")
    monkeypatch.delenv("MC_API_TOKEN", raising=False)
    monkeypatch.delenv("MC_JWT_SECRET", raising=False)
    monkeypatch.setenv("MC_ADMIN_PASSWORD", "admin")
    monkeypatch.setenv("MC_ALLOW_LEGACY_TOKEN_ADMIN", "1")
    db = tmp_path / "boot-insecure.sqlite"
    app = create_app(database_url=f"sqlite:///{db.as_posix()}")
    with TestClient(app) as client:
        body = client.get("/api/v1/public/bootstrap").json()
    assert body["flags"]["insecure_defaults"] is True
    assert body["flags"]["production"] is False


def test_public_bootstrap_respects_mc_port(tmp_path, monkeypatch):
    # MC_PLATFORM_URL 优先级高于 MC_PORT：不清掉会被别处遗留的值顶掉
    monkeypatch.delenv("MC_PLATFORM_URL", raising=False)
    monkeypatch.delenv("MC_SERVER", raising=False)
    monkeypatch.delenv("MC_HOST", raising=False)
    monkeypatch.setenv("MC_PORT", "9100")
    db = tmp_path / "boot9100.sqlite"
    app = create_app(database_url=f"sqlite:///{db.as_posix()}")
    with TestClient(app) as client:
        res = client.get("/api/v1/public/bootstrap")
    assert res.status_code == 200
    body = res.json()
    assert ":9100" in body["platform_base_url"]
    assert ":9100" in body["runner"]["cli_command"]
