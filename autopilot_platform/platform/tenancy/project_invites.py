"""项目邀请：创建链接、预览、登录接受、自助注册入项。"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from autopilot_platform.core.schemas import (
    InviteRegisterIn,
    ProjectInviteCreate,
    ProjectInviteOut,
    ProjectInvitePreview,
    ProjectMemberOut,
    TokenOut,
    UserCreate,
    UserCreateDuty,
)

from ..core import api_messages as msg
from ..auth import AuthContext
from ..core.models import ProjectInviteRow, ProjectMemberRow, ProjectRow, UserRow, db_get, new_id
from .projects import assert_can_access_project, is_platform_admin
from ..artifacts import users_artifacts as ua
from ..authz.rbac import org_admin_elevates_project
from ..core.list_page import slice_page


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _actor(auth: AuthContext) -> str:
    return (auth.username or auth.user_id or "").strip()


def _require_owner_or_admin(db: Session, auth: AuthContext, project_id: str) -> None:
    if is_platform_admin(auth):
        return
    if auth.kind != "user":
        raise PermissionError(msg.PROJECT_OWNER_ADMIN_ADD)
    if org_admin_elevates_project(db, auth, project_id=project_id):
        return
    mem = db.scalars(
        select(ProjectMemberRow).where(
            ProjectMemberRow.project_id == project_id,
            ProjectMemberRow.user_id == auth.user_id,
        )
    ).first()
    if mem is None or mem.role != "owner":
        raise PermissionError(msg.PROJECT_OWNER_ADMIN_ADD)


def _invite_out(row: ProjectInviteRow) -> ProjectInviteOut:
    token = row.token or ""
    return ProjectInviteOut(
        id=row.id,
        project_id=row.project_id,
        token=token,
        role=row.role or "member",
        label=row.label or "",
        created_by=row.created_by or "",
        created_at=row.created_at,
        expires_at=row.expires_at,
        max_uses=int(row.max_uses or 0),
        use_count=int(row.use_count or 0),
        revoked=bool(row.revoked),
        invite_path=f"/?invite={token}" if token else "",
    )


def _consume_invite_use(db: Session, invite_id: str) -> None:
    """原子占用一次邀请次数；并发超限时 rowcount≠1。"""
    now = _utcnow()
    result = db.execute(
        update(ProjectInviteRow)
        .where(
            ProjectInviteRow.id == invite_id,
            ProjectInviteRow.revoked.is_(False),
            or_(
                ProjectInviteRow.expires_at.is_(None),
                ProjectInviteRow.expires_at > now,
            ),
            or_(
                ProjectInviteRow.max_uses <= 0,
                ProjectInviteRow.use_count < ProjectInviteRow.max_uses,
            ),
        )
        .values(use_count=ProjectInviteRow.use_count + 1),
        execution_options={"synchronize_session": False},
    )
    if int(getattr(result, "rowcount", 0) or 0) != 1:
        raise PermissionError(msg.PROJECT_INVITE_EXHAUSTED)


def _release_invite_use(db: Session, invite_id: str) -> None:
    db.execute(
        update(ProjectInviteRow)
        .where(
            ProjectInviteRow.id == invite_id,
            ProjectInviteRow.use_count > 0,
        )
        .values(use_count=ProjectInviteRow.use_count - 1),
        execution_options={"synchronize_session": False},
    )


def _validate_invite_row(row: ProjectInviteRow | None) -> ProjectInviteRow:
    if row is None:
        raise LookupError(msg.PROJECT_INVITE_NOT_FOUND)
    if row.revoked:
        raise PermissionError(msg.PROJECT_INVITE_REVOKED)
    if row.expires_at is not None:
        exp = row.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp < _utcnow():
            raise PermissionError(msg.PROJECT_INVITE_EXPIRED)
    max_uses = int(row.max_uses or 0)
    if 0 < max_uses <= int(row.use_count or 0):
        raise PermissionError(msg.PROJECT_INVITE_EXHAUSTED)
    return row


def create_invite(
    db: Session, project_id: str, body: ProjectInviteCreate, auth: AuthContext
) -> ProjectInviteOut:
    pid = (project_id or "").strip()
    proj = db.get(ProjectRow, pid)
    if proj is None:
        raise LookupError(msg.PROJECT_NOT_FOUND)
    _require_owner_or_admin(db, auth, pid)
    role = (body.role or "member").strip() or "member"
    if role not in ("member", "viewer"):
        raise ValueError(msg.PROJECT_ROLE_INVITE)
    expires_at = None
    hours = int(body.expires_hours or 0)
    if hours > 0:
        expires_at = _utcnow() + timedelta(hours=hours)
    row = ProjectInviteRow(
        id=new_id(),
        project_id=pid,
        token=secrets.token_urlsafe(24),
        role=role,
        label=(body.label or "").strip(),
        created_by=_actor(auth),
        expires_at=expires_at,
        max_uses=int(body.max_uses or 0),
        use_count=0,
        revoked=False,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _invite_out(row)


def list_invites(
    db: Session,
    project_id: str,
    auth: AuthContext,
    *,
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[ProjectInviteOut], int]:
    pid = (project_id or "").strip()
    assert_can_access_project(db, auth, pid)
    _require_owner_or_admin(db, auth, pid)
    rows = db.scalars(
        select(ProjectInviteRow)
        .where(ProjectInviteRow.project_id == pid)
        .order_by(ProjectInviteRow.created_at.desc())
    ).all()
    items = [_invite_out(r) for r in rows]
    size = max(1, min(200, int(page_size)))
    pg = max(1, int(page))
    return slice_page(items, page=pg, page_size=size)


def revoke_invite(db: Session, project_id: str, invite_id: str, auth: AuthContext) -> None:
    pid = (project_id or "").strip()
    _require_owner_or_admin(db, auth, pid)
    row = db.get(ProjectInviteRow, (invite_id or "").strip())
    if row is None or row.project_id != pid:
        raise LookupError(msg.PROJECT_INVITE_NOT_FOUND)
    row.revoked = True
    db.add(row)
    db.commit()


def preview_invite(db: Session, token: str) -> ProjectInvitePreview:
    tok = (token or "").strip()
    row = db.scalars(select(ProjectInviteRow).where(ProjectInviteRow.token == tok)).first()
    if row is None:
        return ProjectInvitePreview(
            token=tok, project_id="", valid=False, detail=msg.PROJECT_INVITE_NOT_FOUND
        )
    proj = db.get(ProjectRow, row.project_id)
    try:
        _validate_invite_row(row)
        valid = True
        detail = ""
    except (LookupError, PermissionError) as exc:
        valid = False
        detail = str(exc)
    return ProjectInvitePreview(
        token=tok,
        project_id=row.project_id,
        project_name=(proj.name if proj else "") or row.project_id,
        role=row.role or "member",
        label=row.label or "",
        expires_at=row.expires_at,
        valid=valid,
        detail=detail,
    )


def _add_or_upgrade_member(
    db: Session, *, project_id: str, user_id: str, role: str
) -> ProjectMemberOut:
    user = db_get(db, UserRow, user_id)
    proj = db.get(ProjectRow, project_id)
    poid = (getattr(proj, "org_id", None) or "").strip() if proj else ""
    if poid:
        from .organizations import ensure_org_member, org_member_role  # 延迟：仅项目挂了组织时补成员

        ensure_org_member(db, poid, user_id, role="member")
        org_role = org_member_role(db, user_id, poid)
        if org_role in ("owner", "admin"):
            role = "owner"
    existing = db.scalars(
        select(ProjectMemberRow).where(
            ProjectMemberRow.project_id == project_id,
            ProjectMemberRow.user_id == user_id,
        )
    ).first()
    # 不降级已有 owner
    if existing:
        if existing.role != "owner":
            existing.role = role
            db.add(existing)
        member_role = existing.role or role
    else:
        db.add(
            ProjectMemberRow(
                id=new_id(),
                project_id=project_id,
                user_id=user_id,
                role=role,
            )
        )
        member_role = role
    return ProjectMemberOut(
        user_id=user_id,
        username=(str(user.username) if user else ""),
        role=str(member_role),
        project_id=project_id,
    )


def accept_invite(db: Session, token: str, auth: AuthContext) -> ProjectMemberOut:
    if auth.kind != "user":
        raise PermissionError(msg.AUTH_USER_LOGIN_REQUIRED)
    row = db.scalars(
        select(ProjectInviteRow).where(ProjectInviteRow.token == (token or "").strip())
    ).first()
    row = _validate_invite_row(row)
    out = _add_or_upgrade_member(
        db, project_id=row.project_id, user_id=auth.user_id, role=row.role or "member"
    )
    _consume_invite_use(db, row.id)
    db.commit()
    return out


def register_via_invite(db: Session, token: str, body: InviteRegisterIn) -> TokenOut:
    """自助注册：仅能通过有效邀请创建 operator 并加入项目。"""
    row = db.scalars(
        select(ProjectInviteRow).where(ProjectInviteRow.token == (token or "").strip())
    ).first()
    row = _validate_invite_row(row)
    invite_id = row.id
    invite_role = (row.role or "member").strip() or "member"
    duty: UserCreateDuty
    if invite_role == "owner":
        duty = "project_owner"
    elif invite_role == "viewer":
        duty = "project_viewer"
    else:
        duty = "project_member"
    project_id = row.project_id
    _consume_invite_use(db, invite_id)
    db.commit()
    try:
        user_out = ua.create_user(
            db,
            UserCreate(
                username=body.username.strip(),
                password=body.password,
                duty=duty,
                project_id=project_id,
            ),
        )
    except Exception:
        _release_invite_use(db, invite_id)
        db.commit()
        raise
    user = db_get(db, UserRow, user_out.id)
    if user is None:
        raise LookupError(msg.AUTH_USER_NOT_FOUND)
    from ..identity.session_tokens import issue_session  # 延迟：仅自助注册入项签发会话

    return issue_session(db, user)
