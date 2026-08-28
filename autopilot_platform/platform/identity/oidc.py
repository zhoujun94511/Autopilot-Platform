"""OIDC（Authorization Code）登录：发现文档 → 授权 → 换票 → 绑定/建用户 → 发平台 JWT。"""

from __future__ import annotations

import logging
import secrets
import time
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt
from jwt import PyJWKClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from autopilot_platform.core.schemas import TokenOut

from ..core import api_messages as msg
from ..core.models import UserRow, new_id
from ..core.security import hash_password
from ..core.settings import (
    jwt_secret,
    oidc_auto_provision,
    oidc_client_id,
    oidc_client_secret,
    oidc_default_role,
    oidc_enabled,
    oidc_frontend_redirect,
    oidc_issuer,
    oidc_redirect_uri,
    oidc_scopes,
)

logger = logging.getLogger(__name__)

_discovery_cache: dict[str, Any] | None = None
_discovery_at: float = 0.0
_DISCOVERY_TTL = 3600.0


def oidc_status() -> dict[str, Any]:
    return {
        "enabled": oidc_enabled() and bool(oidc_issuer() and oidc_client_id()),
        "issuer": oidc_issuer() if oidc_enabled() else "",
    }


def _require_configured() -> None:
    if not oidc_enabled():
        raise RuntimeError(msg.AUTH_OIDC_DISABLED)
    if not oidc_issuer() or not oidc_client_id() or not oidc_client_secret():
        raise RuntimeError(msg.AUTH_OIDC_CONFIG_REQUIRED)


def get_discovery(*, force: bool = False) -> dict[str, Any]:
    global _discovery_cache, _discovery_at
    _require_configured()
    now = time.time()
    if not force and _discovery_cache and (now - _discovery_at) < _DISCOVERY_TTL:
        return _discovery_cache
    url = f"{oidc_issuer()}/.well-known/openid-configuration"
    with httpx.Client(timeout=15.0) as client:
        r = client.get(url)
        r.raise_for_status()
        data = r.json()
    _discovery_cache = data
    _discovery_at = now
    return data


def reset_oidc_cache() -> None:
    global _discovery_cache, _discovery_at
    _discovery_cache = None
    _discovery_at = 0.0


def make_state() -> str:
    """签名 state（含随机 nonce + 过期），无需服务端会话存储。"""
    now = int(time.time())
    payload = {"n": secrets.token_urlsafe(16), "exp": now + 600, "iat": now}
    return jwt.encode(payload, jwt_secret(), algorithm="HS256")


def verify_state(state: str) -> None:
    try:
        payload = jwt.decode(state, jwt_secret(), algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise ValueError(msg.AUTH_OIDC_INVALID_STATE) from exc
    if int(payload.get("exp") or 0) < int(time.time()):
        raise ValueError(msg.AUTH_OIDC_STATE_EXPIRED)


def build_authorize_url(*, state: str | None = None) -> tuple[str, str]:
    disc = get_discovery()
    auth_ep = disc.get("authorization_endpoint")
    if not auth_ep:
        raise RuntimeError("OIDC discovery missing authorization_endpoint")
    st = state or make_state()
    q = urlencode(
        {
            "response_type": "code",
            "client_id": oidc_client_id(),
            "redirect_uri": oidc_redirect_uri(),
            "scope": oidc_scopes(),
            "state": st,
        }
    )
    return f"{auth_ep}?{q}", st


def _exchange_code(code: str) -> dict[str, Any]:
    disc = get_discovery()
    token_ep = disc.get("token_endpoint")
    if not token_ep:
        raise RuntimeError("OIDC discovery missing token_endpoint")
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": oidc_redirect_uri(),
        "client_id": oidc_client_id(),
        "client_secret": oidc_client_secret(),
    }
    with httpx.Client(timeout=20.0) as client:
        r = client.post(token_ep, data=data)
        if r.status_code >= 400:
            raise ValueError(f"token exchange failed: {r.status_code} {r.text[:300]}")
        return r.json()


def _decode_id_token(id_token: str) -> dict[str, Any]:
    disc = get_discovery()
    jwks_uri = disc.get("jwks_uri")
    if not jwks_uri:
        raise RuntimeError("OIDC discovery missing jwks_uri")
    jwks = PyJWKClient(jwks_uri)
    key = jwks.get_signing_key_from_jwt(id_token)
    issuer = disc.get("issuer") or oidc_issuer()
    return jwt.decode(
        id_token,
        key.key,
        algorithms=["RS256", "ES256", "HS256"],
        audience=oidc_client_id(),
        issuer=issuer,
    )


def _username_from_claims(claims: dict[str, Any]) -> str:
    for key in ("preferred_username", "email", "name", "sub"):
        v = claims.get(key)
        if isinstance(v, str) and v.strip():
            # email → local part if needed, keep simple
            name = v.strip()
            if "@" in name and key == "email":
                name = name.split("@", 1)[0]
            # sanitize
            name = "".join(c if c.isalnum() or c in "._-" else "_" for c in name)[:64]
            if name:
                return name
    return f"oidc_{secrets.token_hex(4)}"


def resolve_or_create_user(db: Session, claims: dict[str, Any]) -> UserRow:
    sub = str(claims.get("sub") or "").strip()
    if not sub:
        raise ValueError("id_token missing sub")
    row = db.scalars(select(UserRow).where(UserRow.oidc_sub == sub)).first()
    if row is not None:
        return row

    username = _username_from_claims(claims)
    # 若同名本地用户存在且未绑定 OIDC，则绑定
    existing = db.scalars(select(UserRow).where(UserRow.username == username)).first()
    if existing is not None:
        if existing.oidc_sub and existing.oidc_sub != sub:
            username = f"{username}_{secrets.token_hex(2)}"
        else:
            existing.oidc_sub = sub
            db.commit()
            db.refresh(existing)
            return existing

    if not oidc_auto_provision():
        raise PermissionError(msg.AUTH_OIDC_USER_NOT_PROVISIONED)

    # 保证唯一用户名
    base = username
    n = 0
    while db.scalars(select(UserRow).where(UserRow.username == username)).first():
        n += 1
        username = f"{base}_{n}"

    row = UserRow(
        id=new_id(),
        username=username,
        password_hash=hash_password(secrets.token_urlsafe(24)),
        role=oidc_default_role(),
        oidc_sub=sub,
    )
    try:
        db.add(row)
        db.commit()
        db.refresh(row)
        return row
    except IntegrityError:
        db.rollback()
        raced = db.scalars(select(UserRow).where(UserRow.oidc_sub == sub)).first()
        if raced is not None:
            return raced
        raise


def complete_oidc_login(db: Session, *, code: str, state: str) -> TokenOut:
    verify_state(state)
    tokens = _exchange_code(code)
    id_token = tokens.get("id_token")
    if not id_token:
        raise ValueError("token response missing id_token")
    claims = _decode_id_token(str(id_token))
    user = resolve_or_create_user(db, claims)
    from .session_tokens import issue_session

    return issue_session(db, user)


def frontend_success_redirect(token: TokenOut) -> str:
    """把 token 放进 URL fragment，避免进 access log / Referer。"""
    base = oidc_frontend_redirect().strip() or "/"
    if "#" in base:
        base = base.split("#", 1)[0]
    base = base.rstrip("/") or ""
    params = {
        "oidc": "1",
        "access_token": token.access_token,
        "username": token.user.username,
        "role": token.user.role,
        "user_id": token.user.id,
    }
    if token.refresh_token:
        params["refresh_token"] = token.refresh_token
    q = urlencode(params)
    return f"{base}/#{q}" if base else f"/#{q}"
