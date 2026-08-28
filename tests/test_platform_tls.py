"""Platform TLS 配置单元测试（不启动 uvicorn）。"""

from __future__ import annotations

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from autopilot_platform.platform.core import tls as mc_tls


@pytest.fixture(autouse=True)
def _clear_tls_env(monkeypatch):
    for key in (
        "MC_SSL_CERTFILE",
        "MC_SSL_KEYFILE",
        "MC_SSL_CA_CERTS",
        "MC_SSL_ENABLED",
        "MC_BEHIND_HTTPS_PROXY",
        "MC_PLATFORM_URL",
        "MC_ENV",
    ):
        monkeypatch.delenv(key, raising=False)


def test_ssl_disabled_without_cert_files():
    assert mc_tls.ssl_enabled() is False
    assert mc_tls.uvicorn_ssl_kwargs() == {}


def test_ssl_enabled_when_cert_and_key_exist(tmp_path, monkeypatch):
    cert = tmp_path / "server.crt"
    key = tmp_path / "server.key"
    cert.write_text("fake-cert", encoding="utf-8")
    key.write_text("fake-key", encoding="utf-8")
    monkeypatch.setenv("MC_SSL_CERTFILE", str(cert))
    monkeypatch.setenv("MC_SSL_KEYFILE", str(key))
    assert mc_tls.ssl_enabled() is True
    kw = mc_tls.uvicorn_ssl_kwargs()
    assert kw["ssl_certfile"] == str(cert.resolve())
    assert kw["ssl_keyfile"] == str(key.resolve())


def test_validate_tls_files_requires_pair(tmp_path, monkeypatch):
    cert = tmp_path / "only.crt"
    cert.write_text("x", encoding="utf-8")
    monkeypatch.setenv("MC_SSL_CERTFILE", str(cert))
    errs = mc_tls.validate_tls_files()
    assert any("成对" in e for e in errs)


def test_production_https_requires_tls_or_proxy(monkeypatch):
    monkeypatch.setenv("MC_ENV", "production")
    monkeypatch.setenv("MC_PLATFORM_URL", "https://mc.example.com")
    errs = mc_tls.production_https_errors()
    assert len(errs) == 1
    assert "https://" in errs[0]


def test_production_https_ok_with_proxy(monkeypatch):
    monkeypatch.setenv("MC_ENV", "production")
    monkeypatch.setenv("MC_PLATFORM_URL", "https://mc.example.com")
    monkeypatch.setenv("MC_BEHIND_HTTPS_PROXY", "1")
    assert mc_tls.production_https_errors() == ()


def test_uvicorn_proxy_kwargs(monkeypatch):
    monkeypatch.setenv("MC_BEHIND_HTTPS_PROXY", "1")
    monkeypatch.setenv("MC_FORWARDED_ALLOW_IPS", "10.0.0.1")
    kw = mc_tls.uvicorn_proxy_kwargs()
    assert kw["proxy_headers"] is True
    assert kw["forwarded_allow_ips"] == "10.0.0.1"
