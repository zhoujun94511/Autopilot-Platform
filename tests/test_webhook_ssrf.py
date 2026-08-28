from __future__ import annotations

import socket

from typing import Any, cast

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from autopilot_platform.core.schemas import JobCreate
from autopilot_platform.core.webhook_security import validate_webhook_url
from autopilot_platform.platform.ops import notify


@pytest.fixture(autouse=True)
def _isolated_runtime_config(monkeypatch, tmp_path):
    """避免本机 mc_runtime_config.json 干扰 env 优先级测试。"""
    path = tmp_path / "mc_runtime_config.json"
    path.write_text("{}\n", encoding="utf-8")
    monkeypatch.setenv("MC_RUNTIME_CONFIG", str(path))
    from autopilot_platform.platform.ops.runtime_config import reload_runtime_config

    reload_runtime_config()


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://127.0.0.1/hook",
        "http://[::1]/hook",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.1/hook",
        "http://localhost/hook",
    ],
)
def test_webhook_url_rejects_unsafe_targets(url, monkeypatch):
    monkeypatch.delenv("MC_WEBHOOK_ALLOW_LOOPBACK", raising=False)
    monkeypatch.setenv("MC_WEBHOOK_ALLOW_LOOPBACK", "0")
    with pytest.raises(ValueError):
        validate_webhook_url(url, resolve=False)


def test_webhook_loopback_allowed_when_flag_on(monkeypatch):
    from autopilot_platform.platform.ops.runtime_config import (
        reload_runtime_config,
        save_runtime_config,
    )

    monkeypatch.setenv("MC_WEBHOOK_ALLOW_LOOPBACK", "1")
    save_runtime_config({"MC_WEBHOOK_ALLOW_LOOPBACK": "1"})
    reload_runtime_config()
    assert validate_webhook_url("http://127.0.0.1:8765/hooks/intent", resolve=False).startswith(
        "http://127.0.0.1"
    )
    assert validate_webhook_url("http://localhost:8765/hooks/intent", resolve=False).startswith(
        "http://localhost"
    )


def test_job_create_rejects_private_webhook_url():
    with pytest.raises(ValidationError):
        JobCreate(
            project_dir="/tmp/project",
            webhook_url="http://169.254.169.254/latest/meta-data/",
        )


def test_create_job_service_rejects_private_webhook():
    """AUD-P2-006：服务层落库前二次校验（绕过 schema 的防御）。"""
    from types import SimpleNamespace

    from autopilot_platform.core.webhook_security import validate_webhook_url

    with pytest.raises(ValueError, match="私网|不允许"):
        validate_webhook_url("http://10.0.0.1/hook", resolve=False)

    # 同步覆盖 create_job 内调用路径：构造最小 body，在落库前应抛错
    from autopilot_platform.platform.services.execution import jobs as jobs_svc

    body = SimpleNamespace(
        name="t",
        project_dir="/tmp/p",
        artifact_id="",
        app_build_id="",
        project_id="",
        platform="android",
        parallel=False,
        parallel_workers=0,
        backend_mode="auto",
        web_engine="selenium",
        wda_bundle="",
        preferred_runner_id=None,
        webhook_url="http://10.0.0.1/hook",
        device_udids=[],
        entry_paths=[],
        depends_on=[],
    )

    class _DB:
        @staticmethod
        def scalars(*_a, **_k):
            return SimpleNamespace(all=lambda: [])

        def add(self, *_a, **_k):
            raise AssertionError("must not persist unsafe webhook")

        def commit(self):
            raise AssertionError("must not commit")

        @staticmethod
        def refresh(*_a, **_k):
            return None

    with pytest.raises(ValueError, match="私网|不允许"):
        jobs_svc.create_job(cast(Session, _DB()), cast(Any, body), auth=None)


def test_redirect_target_is_validated_before_following(monkeypatch):
    import httpx

    calls: list[str] = []

    class _Response:
        status_code = 302
        headers = {"location": "http://169.254.169.254/latest/meta-data/"}
        text = ""

    class _Client:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        @staticmethod
        def post(url, **_kwargs):
            calls.append(url)
            return _Response()

    monkeypatch.setattr(httpx, "Client", _Client)
    assert notify._post("https://8.8.8.8/hook", {"event": "test"}) is False
    assert calls == ["https://8.8.8.8/hook"]


def test_pin_webhook_url_pins_hostname_to_resolved_ip(monkeypatch):
    from autopilot_platform.core.webhook_security import pin_webhook_url

    def _fake_getaddrinfo(_host, port, *_args, **_kwargs):
        assert _host == "hooks.example.com"
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", port or 0)),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo)
    pinned = pin_webhook_url("https://hooks.example.com:8443/cb")
    assert pinned.url == "https://8.8.8.8:8443/cb"
    assert pinned.host_header == "hooks.example.com:8443"
    assert pinned.sni_hostname == "hooks.example.com"


def test_pin_rejects_mixed_public_private_records(monkeypatch):
    from autopilot_platform.core.webhook_security import pin_webhook_url

    def _fake_getaddrinfo(_host, port, *_args, **_kwargs):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", port or 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", port or 0)),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo)
    with pytest.raises(ValueError, match="私网|不允许"):
        pin_webhook_url("http://mixed.example/hook")


def test_post_connects_to_pinned_ip_not_hostname(monkeypatch):
    """模拟 rebinding：校验解析公网，连接 URL 必须是钉死 IP，而非主机名。"""
    import httpx
    from autopilot_platform.core import webhook_security as ws

    def _fake_getaddrinfo(_host, port, *_args, **_kwargs):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("1.1.1.1", port or 0)),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo)
    monkeypatch.setattr(ws.socket, "getaddrinfo", _fake_getaddrinfo)

    calls: list[tuple[str, str | None, str | None]] = []

    class _Response:
        status_code = 200
        text = "ok"
        headers: dict = {}

    class _Client:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        @staticmethod
        def post(url, **kwargs):
            hdrs = kwargs.get("headers") or {}
            host = None
            if hasattr(hdrs, "get"):
                host = hdrs.get("Host") or hdrs.get("host")
            elif isinstance(hdrs, dict):
                host = hdrs.get("Host") or hdrs.get("host")
            ext = kwargs.get("extensions") or {}
            calls.append((str(url), host, ext.get("sni_hostname")))
            return _Response()

    monkeypatch.setattr(httpx, "Client", _Client)
    assert notify._post("https://rebinding.example/hook", {"event": "test"}) is True
    assert calls == [
        ("https://1.1.1.1/hook", "rebinding.example", "rebinding.example")
    ]
