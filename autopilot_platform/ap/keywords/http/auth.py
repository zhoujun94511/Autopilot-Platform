"""HTTP Auth 助手：写入 Session 默认头 / query，或变量池。"""

from __future__ import annotations

import base64
from typing import Any

from ..context import ExecutionContext
from ..registry import KeywordError, keyword
from .session import get_http_session


def _apply_header(ctx: ExecutionContext, name: str, value: str) -> None:
    state = get_http_session(ctx)
    if state is None:
        # 无会话时写入变量，供后续 header=${http_auth_header} 使用
        ctx.set_var("http_auth_header", {name: value})
        ctx.set_var("_http_auth_header_line", f"{name}: {value}")
        return
    state.default_headers[name] = value
    try:
        state.client.headers[name] = value
    except (AttributeError, TypeError, ValueError, RuntimeError):
        pass


@keyword("http_set_auth_basic", name="设置Basic认证", category="Http")
def http_set_auth_basic(
    ctx: ExecutionContext,
    username: str = "",
    password: str = "",
    **_kw: Any,
) -> dict:
    user = str(username or "")
    pwd = str(password or "")
    if not user:
        raise KeywordError("http_set_auth_basic: username 不能为空")
    token = base64.b64encode(f"{user}:{pwd}".encode("utf-8")).decode("ascii")
    _apply_header(ctx, "Authorization", f"Basic {token}")
    return {}


@keyword("http_set_auth_bearer", name="设置Bearer令牌", category="Http")
def http_set_auth_bearer(ctx: ExecutionContext, token: str = "", **_kw: Any) -> dict:
    raw = str(token or "").strip()
    if not raw:
        raise KeywordError("http_set_auth_bearer: token 不能为空")
    if raw.lower().startswith("bearer "):
        raw = raw[7:].strip()
    _apply_header(ctx, "Authorization", f"Bearer {raw}")
    return {}


@keyword("http_set_auth_apikey", name="设置API Key", category="Http")
def http_set_auth_apikey(
    ctx: ExecutionContext,
    name: str = "X-API-Key",
    value: str = "",
    location: str = "header",
    **_kw: Any,
) -> dict:
    key = str(name or "").strip() or "X-API-Key"
    val = str(value or "")
    if not val:
        raise KeywordError("http_set_auth_apikey: value 不能为空")
    loc = str(location or "header").strip().lower()
    if loc in ("query", "param", "params"):
        state = get_http_session(ctx)
        if state is None:
            ctx.set_var("http_auth_query", {key: val})
            return {}
        state.query_defaults[key] = val
        return {}
    _apply_header(ctx, key, val)
    return {}
