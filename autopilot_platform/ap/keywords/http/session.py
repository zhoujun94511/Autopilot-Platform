"""用例级 HTTP Session（httpx.Client + cookie jar）。

挂在 ExecutionContext.http_session；无 begin 时请求关键字仍可用短生命周期 Client。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional
from urllib.parse import urljoin

# noinspection PyUnresolvedReferences
import httpx

from ..context import ExecutionContext
from ..registry import keyword


def proxy_to_url(proxy_cfg: Any) -> Optional[str]:
    """把 http_set_proxy 关键字产出的 dict 或 URL 字符串转为 httpx proxy URL。"""
    if proxy_cfg in (None, "", "NONE", "none"):
        return None
    if isinstance(proxy_cfg, str):
        s = proxy_cfg.strip()
        return s or None
    if isinstance(proxy_cfg, dict):
        host = str(proxy_cfg.get("host") or "").strip()
        port = str(proxy_cfg.get("port") or "").strip()
        if not host or not port:
            return None
        user = str(proxy_cfg.get("user") or "").strip()
        password = str(proxy_cfg.get("password") or "").strip()
        if user and user.upper() != "NONE" and password and password.upper() != "NONE":
            return f"http://{user}:{password}@{host}:{port}"
        return f"http://{host}:{port}"
    return None


@dataclass
class HttpSessionState:
    """跨步骤共享的 HTTP 会话。"""

    client: httpx.Client
    base_url: str = ""
    default_headers: dict[str, str] = field(default_factory=dict)
    # API-Key 走 query 时累积；请求时合并
    query_defaults: dict[str, str] = field(default_factory=dict)

    def resolve_url(self, url: str) -> str:
        raw = (url or "").strip()
        if not raw:
            return self.base_url or raw
        if self.base_url and not raw.lower().startswith(("http://", "https://")):
            return urljoin(self.base_url.rstrip("/") + "/", raw.lstrip("/"))
        return raw

    def close(self) -> None:
        try:
            self.client.close()
        except (OSError, RuntimeError, AttributeError):
            pass


def get_http_session(ctx: ExecutionContext) -> Optional[HttpSessionState]:
    return getattr(ctx, "http_session", None)


def close_http_session(ctx: ExecutionContext) -> None:
    state = get_http_session(ctx)
    if state is not None:
        state.close()
    setattr(ctx, "http_session", None)


def _truthy(val: Any, default: bool = True) -> bool:
    if val in (None, ""):
        return default
    return str(val).strip().lower() not in ("0", "false", "no", "off", "否")


@keyword(
    "http_session_begin",
    name="开启HTTP会话",
    category="Http",
    out_params=[],
)
def http_session_begin(
    ctx: ExecutionContext,
    base_url: str = "",
    timeout: str = "20",
    verify: str = "true",
    proxy: str = "",
    header: str = "",
    follow_redirects: str = "true",
    **_kw: Any,
) -> dict:
    """创建用例级 httpx.Client，后续 http_* 请求默认复用 cookie / 默认头 / base_url。"""
    close_http_session(ctx)
    timeout_s = 20.0
    if timeout not in (None, ""):
        try:
            timeout_s = min(max(float(timeout), 0.1), 120.0)
        except (TypeError, ValueError):
            pass
    headers: dict[str, str] = {}
    if header:
        from .client import _parse_mapping  # 延迟：拆 client↔session 环

        headers = {str(k): str(v) for k, v in _parse_mapping(header).items()}
    proxy_url = proxy_to_url(proxy)
    # 若 proxy 是变量名，尝试从变量池取 dict
    if proxy_url is None and proxy and str(proxy) not in ("", "NONE"):
        proxy_url = proxy_to_url(ctx.get_var(str(proxy).strip(), None))
    kwargs: dict[str, Any] = {
        "timeout": timeout_s,
        "follow_redirects": _truthy(follow_redirects, True),
        "verify": _truthy(verify, True),
        "headers": headers or None,
    }
    if proxy_url:
        kwargs["proxy"] = proxy_url
    base = str(base_url or "").strip() or str(ctx.get_var("base_url") or "").strip()
    if base:
        kwargs["base_url"] = base.rstrip("/")
    client = httpx.Client(**kwargs)
    state = HttpSessionState(client=client, base_url=base, default_headers=dict(headers))
    setattr(ctx, "http_session", state)
    ctx.log(f"HTTP 会话已开启 base_url={base or '(none)'}")
    return {}


@keyword(
    "http_session_end",
    name="关闭HTTP会话",
    category="Http",
    out_params=[],
)
def http_session_end(ctx: ExecutionContext, **_kw: Any) -> dict:
    """关闭用例级 Client 并清理 cookie jar。"""
    close_http_session(ctx)
    ctx.log("HTTP 会话已关闭")
    return {}


def merge_headers(state: Optional[HttpSessionState], header: Any) -> dict[str, str]:
    from .client import _parse_mapping  # 延迟：拆 client↔session 环

    out: dict[str, str] = {}
    if state is not None:
        out.update(state.default_headers)
    out.update({str(k): str(v) for k, v in _parse_mapping(header).items()})
    return out
