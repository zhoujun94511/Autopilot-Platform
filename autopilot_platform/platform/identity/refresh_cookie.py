"""Refresh Token HttpOnly Cookie（AUD-2026-02 Phase C）。

浏览器 Console 以 Cookie 持有 refresh；IDE / API 客户端仍可走 JSON body。
SameSite=Lax + 限定 Path，降低 CSRF；JS 不可读 Cookie（HttpOnly）。
"""

from __future__ import annotations

import os

from fastapi import Request, Response

from ..core.settings import refresh_token_days

COOKIE_NAME = "mc_refresh"
COOKIE_PATH = "/api/v1/auth"


def _cookie_secure(request: Request) -> bool:
    raw = os.environ.get("MC_COOKIE_SECURE", "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    xf = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip().lower()
    if xf == "https":
        return True
    return (request.url.scheme or "").lower() == "https"


def read_refresh_cookie(request: Request) -> str:
    return (request.cookies.get(COOKIE_NAME) or "").strip()


def set_refresh_cookie(response: Response, token: str, request: Request) -> None:
    raw = (token or "").strip()
    if not raw:
        clear_refresh_cookie(response, request)
        return
    max_age = max(1, refresh_token_days()) * 86400
    response.set_cookie(
        key=COOKIE_NAME,
        value=raw,
        max_age=max_age,
        httponly=True,
        secure=_cookie_secure(request),
        samesite="lax",
        path=COOKIE_PATH,
    )


def clear_refresh_cookie(response: Response, request: Request) -> None:
    response.delete_cookie(
        key=COOKIE_NAME,
        path=COOKIE_PATH,
        httponly=True,
        secure=_cookie_secure(request),
        samesite="lax",
    )


def resolve_refresh_token(request: Request, body_token: str | None) -> str:
    """优先 body（IDE/显式），否则 Cookie（浏览器）。"""
    raw = (body_token or "").strip()
    if raw:
        return raw
    return read_refresh_cookie(request)
