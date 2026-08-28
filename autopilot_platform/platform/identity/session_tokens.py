"""Refresh token 签发 / 轮换 / 吊销。"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from autopilot_platform.core.schemas import TokenOut, UserOut

from ..core import api_messages as msg
from ..core.models import RefreshTokenRow, UserRow, db_get, new_id
from ..core.security import create_access_token
from ..core.settings import access_token_minutes, refresh_token_days


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def hash_refresh_token(raw: str) -> str:
    return hashlib.sha256((raw or "").encode("utf-8")).hexdigest()


def _user_out(row: UserRow) -> UserOut:
    return UserOut(
        id=row.id,
        username=row.username,
        role=row.role or "operator",
        disabled=bool(row.disabled),
        created_at=row.created_at,
    )


def _make_refresh_row(user_id: str, raw: str) -> RefreshTokenRow:
    return RefreshTokenRow(
        id=new_id(),
        user_id=user_id,
        token_hash=hash_refresh_token(raw),
        expires_at=_utcnow() + timedelta(days=refresh_token_days()),
        revoked=False,
    )


def issue_session(db: Session, user: UserRow) -> TokenOut:
    """签发 access + refresh。"""
    if user.disabled:
        raise PermissionError(msg.AUTH_USER_DISABLED)
    raw = secrets.token_urlsafe(48)
    db.add(_make_refresh_row(user.id, raw))
    db.commit()
    access = create_access_token(
        sub=user.id, role=user.role or "operator", username=user.username
    )
    return TokenOut(
        access_token=access,
        token_type="bearer",
        expires_in=access_token_minutes() * 60,
        refresh_token=raw,
        user=_user_out(user),
    )


def _get_valid_row(db: Session, raw: str) -> RefreshTokenRow:
    th = hash_refresh_token(raw)
    row = db.scalars(select(RefreshTokenRow).where(RefreshTokenRow.token_hash == th)).first()
    if row is None:
        raise PermissionError(msg.AUTH_REFRESH_INVALID)
    if row.revoked:
        raise PermissionError(msg.AUTH_REFRESH_REVOKED)
    exp = row.expires_at
    if exp is not None:
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp < _utcnow():
            raise PermissionError(msg.AUTH_REFRESH_EXPIRED)
    return row


def refresh_session(db: Session, raw_refresh: str) -> TokenOut:
    """轮换 refresh：旧令牌吊销，发新一对。"""
    row = _get_valid_row(db, (raw_refresh or "").strip())
    user = db_get(db, UserRow, row.user_id)
    if user is None or user.disabled:
        raise PermissionError(msg.AUTH_USER_DISABLED)

    new_raw = secrets.token_urlsafe(48)
    new_row = _make_refresh_row(str(user.id), new_raw)
    row.revoked = True
    row.replaced_by = new_row.id
    db.add(row)
    db.add(new_row)
    db.commit()

    access = create_access_token(
        sub=str(user.id),
        role=str(user.role or "operator"),
        username=str(user.username),
    )
    return TokenOut(
        access_token=access,
        token_type="bearer",
        expires_in=access_token_minutes() * 60,
        refresh_token=new_raw,
        user=_user_out(user),
    )


def revoke_refresh_token(db: Session, raw_refresh: str) -> None:
    raw = (raw_refresh or "").strip()
    if not raw:
        return
    th = hash_refresh_token(raw)
    row = db.scalars(select(RefreshTokenRow).where(RefreshTokenRow.token_hash == th)).first()
    if row is None:
        return
    row.revoked = True
    db.add(row)
    db.commit()


def revoke_all_refresh_tokens(db: Session, user_id: str) -> int:
    rows = list(
        db.scalars(
            select(RefreshTokenRow).where(
                RefreshTokenRow.user_id == user_id,
                RefreshTokenRow.revoked.is_(False),
            )
        ).all()
    )
    for r in rows:
        r.revoked = True
        db.add(r)
    if rows:
        db.commit()
    return len(rows)
