"""Platform 基址统一解析（C32 配置治理）。"""

from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True)
def _clean_url_env(monkeypatch):
    for key in (
        "AUTOPILOT_PLATFORM_URL",
        "MC_PLATFORM_URL",
        "MC_SERVER",
        "MC_MANAGED_RUNNER_SERVER",
        "MC_HOST",
        "MC_PORT",
        "MC_CORS_ORIGINS",
    ):
        monkeypatch.delenv(key, raising=False)


def test_platform_base_url_autopilot_env(monkeypatch):
    from autopilot_platform.platform.core.urls import platform_base_url

    monkeypatch.setenv("AUTOPILOT_PLATFORM_URL", "https://deploy.example.com")
    assert platform_base_url() == "https://deploy.example.com"


def test_platform_base_url_from_host_port():
    from autopilot_platform.platform.core.urls import platform_base_url

    os.environ["MC_HOST"] = "127.0.0.1"
    os.environ["MC_PORT"] = "9000"
    assert platform_base_url() == "http://127.0.0.1:9000"


def test_platform_base_url_mc_server_alias():
    from autopilot_platform.platform.core.urls import platform_base_url

    os.environ["MC_SERVER"] = "http://example.com:8080"
    os.environ["MC_PORT"] = "9000"
    assert platform_base_url() == "http://example.com:8080"


def test_default_cors_follows_port():
    from autopilot_platform.platform.core.urls import default_cors_origins

    os.environ["MC_PORT"] = "9001"
    origins = default_cors_origins()
    assert "http://127.0.0.1:9001" in origins
    assert "http://127.0.0.1:5173" in origins


def test_webhook_allow_loopback_runtime_over_env(monkeypatch, tmp_path):
    from autopilot_platform.core import webhook_security as wh
    from autopilot_platform.platform.ops import runtime_config as rc

    cfg_path = tmp_path / "loopback.json"
    cfg_path.write_text("{}\n", encoding="utf-8")
    monkeypatch.setenv("MC_RUNTIME_CONFIG", str(cfg_path))
    monkeypatch.setenv("MC_WEBHOOK_ALLOW_LOOPBACK", "1")
    rc.reload_runtime_config()
    rc.save_runtime_config({"MC_WEBHOOK_ALLOW_LOOPBACK": "0"})
    rc.reload_runtime_config()
    assert wh.webhook_allow_loopback() is False


def test_describe_config_includes_bootstrap():
    from autopilot_platform.platform.ops.runtime_config import describe_config

    out = describe_config()
    boot = out.get("bootstrap") or {}
    assert boot.get("platform_base_url")
    assert "runtime_json" in str(boot.get("config_priority", ""))
