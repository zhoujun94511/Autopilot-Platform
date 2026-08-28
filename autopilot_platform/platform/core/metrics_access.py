"""`/metrics` 匿名抓取仅认传输层对端（AUD-P2-008）。

不信任 ``X-Forwarded-For`` / ``X-Real-IP``：这些头可被客户端伪造；
若将来经受信反代改写 ASGI ``client``，应单独配置受信代理，而不是读原始 Forwarded 头。
"""

from __future__ import annotations

from fastapi import Request

_LOCAL_METRICS_PEERS = frozenset(
    {
        "127.0.0.1",
        "::1",
        "testclient",  # Starlette TestClient
        "localhost",
    }
)


def metrics_peer_is_local(request: Request) -> bool:
    """直连 loopback 对端才允许匿名 scrape。"""
    peer = ""
    if request.client is not None:
        peer = (request.client.host or "").strip().lower()
    return peer in _LOCAL_METRICS_PEERS
