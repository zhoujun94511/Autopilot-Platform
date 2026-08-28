"""操作审计日志。"""

from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from autopilot_platform.core.schemas import AuditOut

from ..auth import AuthContext
from ..core.models import AuditLogRow, new_id, utcnow
from ..core.settings import audit_log_retention_days

logger = logging.getLogger(__name__)


def write_audit(
    db: Session,
    *,
    action: str,
    actor: str = "",
    actor_kind: str = "",
    resource_type: str = "",
    resource_id: str = "",
    detail: str = "",
    org_id: str = "",
) -> None:
    """尽力写入；失败不影响主业务流程。"""
    try:
        db.add(
            AuditLogRow(
                id=new_id(),
                action=(action or "")[:64],
                actor=(actor or "")[:128],
                actor_kind=(actor_kind or "")[:32],
                resource_type=(resource_type or "")[:32],
                resource_id=(resource_id or "")[:128],
                org_id=(org_id or "")[:128],
                detail=(detail or "")[:2000],
            )
        )
        db.commit()
    except SQLAlchemyError as exc:
        logger.warning("audit write failed: %s", exc)
        try:
            db.rollback()
        except SQLAlchemyError:
            pass


def write_audit_auth(
    db: Session,
    auth: AuthContext | None,
    *,
    action: str,
    resource_type: str = "",
    resource_id: str = "",
    detail: str = "",
    org_id: str | None = None,
) -> None:
    actor = ""
    kind = ""
    oid = (org_id or "").strip() if org_id is not None else ""
    if auth is not None:
        actor = auth.username or ""
        kind = auth.kind or ""
        if org_id is None:
            oid = (getattr(auth, "org_id", "") or "").strip()
    write_audit(
        db,
        action=action,
        actor=actor,
        actor_kind=kind,
        resource_type=resource_type,
        resource_id=resource_id,
        detail=detail,
        org_id=oid,
    )


def list_audits(
    db: Session,
    *,
    page: int = 1,
    page_size: int = 100,
    action: str = "",
    actor: str = "",
    org_id: str = "",
) -> tuple[list[AuditOut], int]:
    from ..services.shared.pagination import paginate

    q = select(AuditLogRow).order_by(AuditLogRow.created_at.desc())
    act = (action or "").strip()
    if act:
        # 以「.」结尾视为前缀（如 design. / acl.）；否则精确匹配
        if act.endswith("."):
            q = q.where(AuditLogRow.action.startswith(act))
        else:
            q = q.where(AuditLogRow.action == act)
    who = (actor or "").strip()
    if who:
        q = q.where(AuditLogRow.actor == who)
    oid = (org_id or "").strip()
    if oid:
        q = q.where(AuditLogRow.org_id == oid)
    size = max(1, min(200, int(page_size)))
    pg = max(1, int(page))
    rows, total = paginate(db, q, page=pg, page_size=size)
    items = [
        AuditOut(
            id=r.id,
            action=r.action or "",
            actor=r.actor or "",
            actor_kind=r.actor_kind or "",
            resource_type=r.resource_type or "",
            resource_id=r.resource_id or "",
            org_id=getattr(r, "org_id", "") or "",
            detail=r.detail or "",
            created_at=r.created_at,
        )
        for r in rows
    ]
    return items, total


def purge_audit_logs(
    db: Session,
    *,
    older_than_days: int | None = None,
) -> tuple[int, int]:
    """删除早于 N 天的审计行；返回 (deleted, days_used)。"""
    days = (
        audit_log_retention_days()
        if older_than_days is None
        else max(0, int(older_than_days))
    )
    if days <= 0:
        return 0, days
    cutoff = utcnow() - timedelta(days=days)
    try:
        result = db.execute(delete(AuditLogRow).where(AuditLogRow.created_at < cutoff))
        db.commit()
        deleted = int(getattr(result, "rowcount", 0) or 0)
    except SQLAlchemyError as exc:
        logger.warning("audit purge failed: %s", exc)
        try:
            db.rollback()
        except SQLAlchemyError:
            pass
        return 0, days
    return deleted, days
