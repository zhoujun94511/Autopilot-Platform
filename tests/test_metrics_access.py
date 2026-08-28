"""AUD-P2-008：/metrics 匿名旁路不信任 Forwarded 头。"""

from __future__ import annotations

from starlette.requests import Request

from autopilot_platform.platform.core.metrics_access import metrics_peer_is_local


def _request(*, client: tuple[str, int], headers: list[tuple[bytes, bytes]]) -> Request:
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/metrics",
        "raw_path": b"/metrics",
        "query_string": b"",
        "headers": headers,
        "client": client,
        "server": ("10.0.0.1", 8000),
    }
    return Request(scope)


def test_metrics_peer_local_loopback():
    req = _request(client=("127.0.0.1", 9), headers=[])
    assert metrics_peer_is_local(req) is True


def test_metrics_peer_ignores_forwarded_for_spoof():
    req = _request(
        client=("203.0.113.50", 40000),
        headers=[
            (b"x-forwarded-for", b"127.0.0.1"),
            (b"x-real-ip", b"127.0.0.1"),
        ],
    )
    assert metrics_peer_is_local(req) is False


def test_metrics_peer_remote_without_spoof():
    req = _request(client=("198.51.100.9", 80), headers=[])
    assert metrics_peer_is_local(req) is False
