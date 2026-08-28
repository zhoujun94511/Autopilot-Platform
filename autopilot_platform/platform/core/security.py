"""密码哈希与 JWT。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

from .settings import access_token_minutes, jwt_secret, stream_token_minutes

_ITERATIONS = 120_000


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _ITERATIONS)
    return "pbkdf2${}${}${}".format(
        _ITERATIONS,
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(digest).decode("ascii"),
    )


def validate_password_policy(password: str) -> None:
    """企业软多租户基础口令策略：长度 ≥8，且同时含字母与数字。

    bootstrap 默认 admin/admin 不走此校验；新建/改密/邀请注册必须满足。
    """
    pwd = password or ""
    if len(pwd) < 8:
        raise ValueError("密码至少 8 位。")
    if len(pwd) > 128:
        raise ValueError("密码过长（最多 128 位）。")
    has_letter = any(c.isalpha() for c in pwd)
    has_digit = any(c.isdigit() for c in pwd)
    if not (has_letter and has_digit):
        raise ValueError("密码须同时包含字母和数字。")


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters_s, salt_b64, dig_b64 = stored.split("$", 3)
        if algo != "pbkdf2":
            return False
        iters = int(iters_s)
        salt = base64.b64decode(salt_b64.encode("ascii"))
        expected = base64.b64decode(dig_b64.encode("ascii"))
        got = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iters)
        return hmac.compare_digest(got, expected)
    except (TypeError, ValueError, AttributeError):
        return False


def create_access_token(
    *, sub: str, role: str, username: str, expire_minutes: int | None = None
) -> str:
    now = datetime.now(timezone.utc)
    minutes = (
        max(1, int(expire_minutes))
        if expire_minutes is not None
        else access_token_minutes()
    )
    payload: dict[str, Any] = {
        "sub": sub,
        "role": role,
        "username": username,
        "iat": now,
        "exp": now + timedelta(minutes=minutes),
        "typ": "access",
    }
    return jwt.encode(payload, jwt_secret(), algorithm="HS256")


def create_stream_token(
    *, sub: str, role: str, username: str, job_id: str, minutes: int | None = None
) -> str:
    now = datetime.now(timezone.utc)
    ttl = max(1, int(minutes)) if minutes is not None else stream_token_minutes()
    payload: dict[str, Any] = {
        "sub": sub,
        "role": role,
        "username": username,
        "typ": "job_log_stream",
        "purpose": "job_log_stream",
        "job_id": job_id,
        "iat": now,
        "exp": now + timedelta(minutes=ttl),
    }
    return jwt.encode(payload, jwt_secret(), algorithm="HS256")


def create_device_log_stream_token(
    *,
    sub: str,
    role: str,
    username: str,
    session_id: str,
    minutes: int | None = None,
) -> str:
    """短时票：远控设备日志 SSE（EventSource Query，勿复用用户 JWT 或远控会话票）。"""
    now = datetime.now(timezone.utc)
    ttl = max(1, int(minutes)) if minutes is not None else stream_token_minutes()
    payload: dict[str, Any] = {
        "sub": sub,
        "role": role,
        "username": username,
        "typ": "device_log_stream",
        "purpose": "device_log_stream",
        "session_id": session_id,
        "iat": now,
        "exp": now + timedelta(minutes=ttl),
    }
    return jwt.encode(payload, jwt_secret(), algorithm="HS256")


def create_device_remote_token(
    *,
    sub: str,
    role: str,
    username: str,
    session_id: str,
    device_id: str,
    runner_id: str,
    minutes: int | None = None,
) -> str:
    """短时票：浏览器 ↔ Runner 远控信令/媒体门禁（复用 stream TTL）。"""
    now = datetime.now(timezone.utc)
    ttl = max(1, int(minutes)) if minutes is not None else stream_token_minutes()
    # 远控会话通常长于日志流；默认至少 60 分钟，仍可被会话 expires_at 约束
    if minutes is None:
        ttl = max(ttl, 60)
    payload: dict[str, Any] = {
        "sub": sub,
        "role": role,
        "username": username,
        "typ": "device_remote",
        "purpose": "device_remote",
        "session_id": session_id,
        "device_id": device_id,
        "runner_id": runner_id,
        "iat": now,
        "exp": now + timedelta(minutes=ttl),
    }
    return jwt.encode(payload, jwt_secret(), algorithm="HS256")


def create_turn_credentials(
    session_id: str,
    *,
    expires_at: datetime | None = None,
) -> tuple[str, str, datetime]:
    """生成 coturn ``use-auth-secret`` 标准短时用户名和 HMAC-SHA1 凭证。"""
    from .settings import (
        turn_credential_ttl_seconds,
        turn_secret,
        turn_username_prefix,
    )

    now = datetime.now(timezone.utc)
    expiry = now + timedelta(seconds=turn_credential_ttl_seconds())
    if expires_at is not None:
        bound = expires_at
        if bound.tzinfo is None:
            bound = bound.replace(tzinfo=timezone.utc)
        expiry = min(expiry, bound)
    expiry_epoch = max(int(now.timestamp()) + 30, int(expiry.timestamp()))
    username = f"{expiry_epoch}:{turn_username_prefix()}:{session_id}"
    secret = turn_secret()
    if not secret:
        raise RuntimeError("MC_TURN_SECRET 未配置")
    digest = hmac.new(
        secret.encode("utf-8"),
        username.encode("utf-8"),
        hashlib.sha1,
    ).digest()
    credential = base64.b64encode(digest).decode("ascii")
    return username, credential, datetime.fromtimestamp(expiry_epoch, timezone.utc)


def decode_access_token(token: str) -> dict[str, Any]:
    return jwt.decode(token, jwt_secret(), algorithms=["HS256"])
