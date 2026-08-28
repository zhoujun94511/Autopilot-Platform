"""HTTP 请求上下文：request_id 与 client IP。"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Awaitable, Callable, MutableMapping

# contextvars 是 3.7+ 标准库，同名 PyPI backport 会让依赖检查误报
# noinspection PyPackageRequirements
from contextvars import ContextVar

REQUEST_ID_HEADER = "X-Request-ID"
_request_id: ContextVar[str] = ContextVar("platform_request_id", default="")
log = logging.getLogger("autopilot_platform.platform.access")


def get_request_id() -> str:
    return _request_id.get()


def set_request_id(value: str) -> None:
    _request_id.set((value or "").strip())


def client_ip_from_scope(scope: MutableMapping[str, Any]) -> str:
    client = scope.get("client")
    if isinstance(client, (list, tuple)) and client:
        host = str(client[0] or "").strip()
        return host or "unknown"
    return "unknown"


def _header_value(scope: MutableMapping[str, Any], name: str) -> str:
    target = name.lower().encode("latin-1")
    for key, val in scope.get("headers") or []:
        if key.lower() == target:
            return val.decode("latin-1", errors="replace").strip()
    return ""


def _normalize_request_id(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return uuid.uuid4().hex
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in text)
    return safe[:128] or uuid.uuid4().hex


class RequestContextMiddleware:
    """注入 ``X-Request-ID``；应用日志与 500 错误可关联同一 ID。"""

    def __init__(self, app: Callable[..., Awaitable[Any]]) -> None:
        self.app = app

    async def __call__(self, scope: MutableMapping[str, Any], receive, send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        incoming = _header_value(scope, REQUEST_ID_HEADER)
        request_id = _normalize_request_id(incoming)
        token = _request_id.set(request_id)
        started = time.perf_counter()
        status_code = 500
        method = (scope.get("method") or "?").upper()
        path = scope.get("path") or "/"

        async def send_wrapper(message: MutableMapping[str, Any]) -> None:
            nonlocal status_code
            if message.get("type") == "http.response.start":
                status_code = int(message.get("status") or 500)
                headers = list(message.get("headers") or [])
                headers.append(
                    (REQUEST_ID_HEADER.lower().encode("latin-1"), request_id.encode("latin-1"))
                )
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            if path not in ("/health", "/health/turn", "/metrics"):
                log.debug(
                    "%s %s %s %.1fms request_id=%s",
                    method,
                    path,
                    status_code,
                    elapsed_ms,
                    request_id,
                )
            _request_id.reset(token)
