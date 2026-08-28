"""WDA 健康检查与会话保活。"""

from __future__ import annotations

from typing import Any

from .session_recovery import is_session_lost_error


def wda_http_alive(base_url: str, timeout: float = 3.0) -> bool:
    """WDA /status 是否可达。"""
    # noinspection PyBroadException
    try:
        import httpx
        r = httpx.get(f"{base_url.rstrip('/')}/status", timeout=timeout)
        return r.status_code == 200
    except Exception:
        return False


def ensure_wda_session(client: Any, *, bundle_id: str = "") -> None:
    """session 无效时通过 client.recreate_session + launch 恢复。"""
    # noinspection PyBroadException
    try:
        if client.session_id:
            client.ping()
            return
    except Exception as exc:
        if not is_session_lost_error(str(exc)):
            raise
    client.recreate_session()
    if bundle_id:
        # noinspection PyBroadException
        try:
            client.launch_app(bundle_id)
        except Exception:
            client.activate_app(bundle_id)


def wda_port_alive(port: int) -> bool:
    from .. import ios_bootstrap as ib
    return ib.wda_alive(port)
