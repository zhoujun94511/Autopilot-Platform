"""Access log / 代理可见性：脱敏 URL query 中的令牌参数。"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, MutableMapping
from urllib.parse import parse_qsl, urlencode

_SENSITIVE_QUERY_KEYS = frozenset(
    {
        "access_token",
        "refresh_token",
        "id_token",
        "token",
    }
)


def redact_query_string(qs: bytes | str) -> bytes:
    """将敏感 query 值替换为 ``***``，供 uvicorn access log 使用。"""
    if isinstance(qs, bytes):
        if not qs:
            return b""
        raw = qs.decode("latin-1")
        as_bytes = True
    else:
        raw = qs or ""
        as_bytes = False
        if not raw:
            return b""
    low = raw.lower()
    if not any(f"{k}=" in low for k in _SENSITIVE_QUERY_KEYS):
        return qs if as_bytes else raw.encode("latin-1")
    pairs = parse_qsl(raw, keep_blank_values=True)
    redacted = [
        (k, "REDACTED" if k.lower() in _SENSITIVE_QUERY_KEYS else v) for k, v in pairs
    ]
    return urlencode(redacted).encode("latin-1")


def redact_scope_query_string(scope: MutableMapping[str, Any]) -> None:
    qs = scope.get("query_string") or b""
    if not isinstance(qs, (bytes, bytearray)):
        return
    new_qs = redact_query_string(bytes(qs))
    if new_qs != bytes(qs):
        scope["query_string"] = new_qs


class RedactSensitiveQueryMiddleware:
    """ASGI 中间件：在响应完成前脱敏 scope.query_string，降低 access log 泄漏面。

    鉴权依赖在脱敏前已读取原始 query，因此不影响 ``require_stream_auth``。
    """

    def __init__(self, app: Callable[..., Awaitable[Any]]) -> None:
        self.app = app

    async def __call__(self, scope: MutableMapping[str, Any], receive, send) -> None:
        if scope.get("type") != "http":
            # WebSocket 不在此脱敏：握手鉴权可能仍读兼容 query；
            # Browser 主路径已改首帧 auth，URL 默认不含 token。
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: MutableMapping[str, Any]) -> None:
            if message.get("type") == "http.response.body" and not message.get(
                "more_body", False
            ):
                redact_scope_query_string(scope)
            await send(message)

        await self.app(scope, receive, send_wrapper)
