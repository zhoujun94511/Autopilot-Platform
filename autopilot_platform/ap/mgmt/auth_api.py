"""IDE 侧鉴权：仅通过管理台 HTTP API（C/S），不 import managementconsole 服务端代码。

契约（Platform 提供）：
  POST /api/v1/auth/login   {username, password} → {access_token, refresh_token, user, …}
  POST /api/v1/auth/refresh {refresh_token} → 轮换双令牌
  POST /api/v1/auth/logout  {refresh_token?} → 吊销
  GET  /api/v1/auth/me      Authorization: Bearer <jwt> → 当前用户

本模块只做 httpx 调用 + 本机会话缓存（settings），不引用 Platform 的
security / users / JWT 签发实现。
"""

from __future__ import annotations

from typing import Any

from .client import MgmtClient, MgmtClientError
from ..runtime import settings


def _is_unauthorized(exc: BaseException) -> bool:
    code = int(getattr(exc, "status_code", 0) or 0)
    if code == 401:
        return True
    text = str(exc).lower()
    return "401" in text or "unauthorized" in text or "登录已失效" in str(exc)


def persist_token_pair(out: dict[str, Any], *, fallback_username: str = "") -> str:
    """把 login/refresh 返回写入 settings；返回 access_token。"""
    access = str(out.get("access_token") or "").strip()
    if not access:
        raise MgmtClientError("未返回 access_token")
    settings.set_mc_jwt(access)
    refresh = str(out.get("refresh_token") or "").strip()
    if refresh:
        settings.set_mc_refresh(refresh)
    u = out.get("user") or {}
    if isinstance(u, dict):
        settings.set_mc_user_profile(
            user_id=str(u.get("id") or ""),
            username=str(u.get("username") or fallback_username or ""),
            role=str(u.get("role") or "operator"),
        )
    return access


def api_login(base_url: str, username: str, password: str, *, timeout: float = 60.0) -> dict[str, Any]:
    """调用 Platform 登录接口，返回原始 JSON（含 access_token / refresh_token / user）。"""
    with MgmtClient(base_url, timeout=timeout) as client:
        return client.login(username, password)


def api_me(base_url: str, access_token: str, *, timeout: float = 60.0) -> dict[str, Any]:
    """调用 Platform /auth/me，校验 JWT 并返回用户档案。"""
    with MgmtClient(base_url, jwt=access_token, timeout=timeout) as client:
        return client.me()


def api_refresh(base_url: str, refresh_token: str, *, timeout: float = 60.0) -> dict[str, Any]:
    with MgmtClient(base_url, timeout=timeout) as client:
        return client.refresh(refresh_token)


def login_and_persist(
    *,
    base_url: str = "",
    username: str = "",
    password: str = "",
) -> dict[str, Any]:
    """登录 API → 写入本机 settings（access / refresh / 用户档案）。

    不触碰服务端库表或 security 模块；仅 HTTP。
    """
    url = (base_url or settings.mc_server_url()).strip().rstrip("/")
    user = (username or settings.mc_username()).strip()
    pwd = password if password is not None and password != "" else settings.mc_password()
    if not url:
        raise MgmtClientError("无法解析 Platform 地址")
    if not user or not pwd:
        raise MgmtClientError("请填写用户名和密码")

    if (base_url or "").strip():
        from ..runtime.platform_deploy import platform_url_locked

        if not platform_url_locked():
            settings.set_mc_server_url(url)
    if username:
        settings.set_mc_username(user)
    if password != "":
        settings.set_mc_password(pwd)

    out = api_login(url, user, pwd)
    persist_token_pair(out, fallback_username=user)
    return out


def refresh_and_persist(*, base_url: str = "") -> dict[str, Any]:
    """用本机 refresh 换新双令牌并持久化。"""
    url = (base_url or settings.mc_server_url()).strip().rstrip("/")
    rt = settings.mc_refresh()
    if not url:
        raise MgmtClientError("无法解析 Platform 地址")
    if not rt:
        raise MgmtClientError("无 refresh_token，请重新登录", status_code=401)
    out = api_refresh(url, rt)
    persist_token_pair(out, fallback_username=settings.mc_username())
    return out


def logout_and_clear(*, base_url: str = "") -> None:
    """尽力吊销服务端 refresh，并清空本机会话。"""
    url = (base_url or settings.mc_server_url()).strip().rstrip("/")
    rt = settings.mc_refresh()
    if url and rt:
        try:
            with MgmtClient(url, timeout=15.0) as client:
                client.logout(rt)
        except (MgmtClientError, OSError, TimeoutError, ValueError, TypeError):
            pass
    settings.clear_mc_session()


def ensure_user_session(*, require: bool = True) -> tuple[MgmtClient, str]:
    """确保本机有可用用户 JWT，并返回已挂 Bearer 的 HTTP 客户端。

    流程：读本地 jwt → GET /auth/me；
    失效则优先 POST /auth/refresh；再不行才用密码重新 login。
    require=True 时禁止 API Token 冒充用户。
    调用方负责 client.close()。
    """
    url = settings.mc_server_url()
    if not url:
        raise MgmtClientError("无法解析 Platform 地址")

    jwt = settings.mc_jwt()
    user = settings.mc_username()
    password = settings.mc_password()
    token = settings.mc_api_token()

    def _relogin_with_password() -> str:
        login_and_persist(base_url=url, username=user, password=password)
        return settings.mc_jwt()

    def _renew_access() -> str:
        """优先 refresh；失败且有密码则回退密码登录。"""
        if settings.mc_refresh():
            try:
                refresh_and_persist(base_url=url)
                return settings.mc_jwt()
            except MgmtClientError:
                settings.set_mc_refresh("")
        if user and password:
            return _relogin_with_password()
        raise MgmtClientError("会话已失效，请重新登录", status_code=401)

    if jwt or (user and password) or settings.mc_refresh():
        if not jwt:
            jwt = _renew_access()
        client = MgmtClient(url, jwt=jwt)
        try:
            me = client.me()
            settings.set_mc_user_profile(
                user_id=str(me.get("id") or ""),
                username=str(me.get("username") or user),
                role=str(me.get("role") or "operator"),
            )
            return client, jwt
        except MgmtClientError as exc:
            client.close()
            if _is_unauthorized(exc):
                jwt = _renew_access()
                return MgmtClient(url, jwt=jwt), jwt
            raise

    if require:
        raise MgmtClientError("请先登录管理台账号（POST /api/v1/auth/login）")

    if token:
        return MgmtClient(url, api_token=token), ""

    raise MgmtClientError("未配置管理台账号或 API Token")
