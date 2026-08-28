"""项目空间与成员（软多租户）。"""

from __future__ import annotations

from ..core import api_messages as msg

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from autopilot_platform.core.schemas import (
    ProjectCreate,
    ProjectMemberIn,
    ProjectMemberOut,
    ProjectOut,
)

from ..auth import AuthContext, is_platform_admin
from ..core.models import ProjectMemberRow, ProjectRow, UserRow, new_id
from ..services.shared.pagination import paginate


def project_to_out(
    row: ProjectRow,
    db: Session | None = None,
    auth: AuthContext | None = None,
) -> ProjectOut:
    my_role = ""
    if auth is not None and is_platform_admin(auth):
        my_role = "owner"
    elif db is not None and auth is not None and auth.kind == "user":
        from ..authz.rbac import org_admin_elevates_project  # 延迟：拆环 rbac ↔ projects

        if org_admin_elevates_project(db, auth, project_id=row.id):
            my_role = "owner"
        else:
            my_role = (member_role(db, auth.user_id, row.id) or "").strip()
    return ProjectOut(
        id=row.id,
        name=row.name or "",
        description=row.description or "",
        owner_user_id=row.owner_user_id or "",
        org_id=getattr(row, "org_id", None) or "",
        created_at=row.created_at,
        my_role=my_role,
    )


def member_project_ids(db: Session, user_id: str) -> set[str]:
    rows = db.scalars(
        select(ProjectMemberRow.project_id).where(ProjectMemberRow.user_id == user_id)
    ).all()
    return set(rows)


def member_role(db: Session, user_id: str, project_id: str) -> str | None:
    """返回用户在项目中的角色；非成员为 None。"""
    pid = (project_id or "").strip()
    uid = (user_id or "").strip()
    if not pid or not uid:
        return None
    row = db.scalars(
        select(ProjectMemberRow).where(
            ProjectMemberRow.project_id == pid,
            ProjectMemberRow.user_id == uid,
        )
    ).first()
    return (row.role if row else None) or None


def assert_can_access_project(db: Session, auth: AuthContext, project_id: str) -> None:
    pid = (project_id or "").strip()
    if not pid:
        raise PermissionError(msg.PROJECT_ID_REQUIRED)
    from ..authz.rbac import ACTION_META_READ, RESOURCE_PROJECT, can  # 延迟：拆环 rbac ↔ projects

    # Harbor 式统一求值：组织角色不满足项目 meta/内容读
    if can(db, auth, RESOURCE_PROJECT, ACTION_META_READ, project_id=pid):
        return
    if auth.kind != "user":
        # Runner / 执行通道不得借「项目校验旁路」读写任意项目空间
        raise PermissionError(msg.PROJECT_NO_ACCESS)
    raise PermissionError(msg.PROJECT_NO_ACCESS)


def assert_can_write_project(db: Session, auth: AuthContext, project_id: str) -> None:
    """读权限基础上，禁止 viewer 写；必须有 project_id。"""
    pid = (project_id or "").strip()
    if not pid:
        raise PermissionError(msg.PROJECT_ID_REQUIRED)
    from ..authz.rbac import ACTION_WRITE, RESOURCE_PROJECT, can  # 延迟：拆环 rbac ↔ projects

    if can(db, auth, RESOURCE_PROJECT, ACTION_WRITE, project_id=pid):
        return
    if auth.kind != "user":
        raise PermissionError(msg.PROJECT_NO_WRITE)
    raise PermissionError(msg.PROJECT_NO_WRITE)


def visible_project_filter(db: Session, auth: AuthContext) -> set[str] | None:
    """None = 不过滤；否则仅这些 project_id。

    非平台管理员：只能看见自己加入的组织内的项目。
    本组织 owner/admin 看见该组织全部项目；普通成员只看见自己加入的项目。
    跨组织残留的 project_members、没有 org_id 的脏项目均不计入。
    """
    if is_platform_admin(auth):
        return None
    if auth.kind != "user":
        return set()  # 非用户身份不可枚举项目空间
    from .organizations import admin_org_ids, member_org_ids  # 延迟：organizations 顶栏已 import projects

    my_orgs = member_org_ids(db, auth.user_id)
    aoids = admin_org_ids(db, auth.user_id)
    ids: set[str] = set()
    if aoids:
        extra = db.scalars(
            select(ProjectRow.id).where(ProjectRow.org_id.in_(aoids))
        ).all()
        ids |= set(extra)
    member_pids = member_project_ids(db, auth.user_id)
    if member_pids:
        rows = db.scalars(
            select(ProjectRow).where(ProjectRow.id.in_(member_pids))
        ).all()
        for row in rows:
            poid = (getattr(row, "org_id", None) or "").strip()
            if poid and poid in my_orgs:
                ids.add(row.id)
    return ids


def create_project(db: Session, body: ProjectCreate, auth: AuthContext) -> ProjectOut:
    pid = body.id.strip()
    if not pid:
        raise ValueError(msg.PROJECT_ID_REQUIRED)
    if db.get(ProjectRow, pid) is not None:
        raise LookupError(f"project already exists: {pid}")
    owner = auth.user_id if auth.kind == "user" else ""
    oid = (body.org_id or getattr(auth, "org_id", "") or "").strip()
    if not oid:
        raise ValueError(msg.PROJECT_ORG_ID_REQUIRED)
    from ..authz.rbac import ACTION_CREATE, RESOURCE_PROJECT, can  # 延迟：拆环 rbac ↔ projects

    if not can(db, auth, RESOURCE_PROJECT, ACTION_CREATE, org_id=oid):
        from .organizations import org_member_role  # 延迟：organizations 顶栏已 import projects

        if org_member_role(db, auth.user_id, oid) == "member":
            raise PermissionError(msg.ORG_PROJECT_CREATE_DENIED)
        raise PermissionError(msg.ORG_NO_ACCESS)
    row = ProjectRow(
        id=pid,
        name=(body.name or pid).strip(),
        description=body.description or "",
        owner_user_id=owner,
        org_id=oid,
    )
    db.add(row)
    db.flush()  # 先落库 projects，再插 members（无 relationship 时避免 FK 乱序）
    if owner:
        db.add(
            ProjectMemberRow(
                id=new_id(),
                project_id=pid,
                user_id=owner,
                role="owner",
            )
        )
    db.commit()
    db.refresh(row)
    return project_to_out(row, db, auth)


def list_projects(
    db: Session,
    auth: AuthContext,
    *,
    org_id: str | None = None,
    q: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[ProjectOut], int]:
    oid = (org_id if org_id is not None else getattr(auth, "org_id", "") or "").strip()
    stmt = select(ProjectRow).order_by(ProjectRow.name, ProjectRow.id)
    if oid:
        stmt = stmt.where(ProjectRow.org_id == oid)
    visible = visible_project_filter(db, auth)
    if visible is not None:
        if not visible:
            return [], 0
        stmt = stmt.where(ProjectRow.id.in_(visible))
    term = (q or "").strip()
    if term:
        like = f"%{term}%"
        stmt = stmt.where(
            or_(
                ProjectRow.id.ilike(like),
                ProjectRow.name.ilike(like),
            )
        )
    size = max(1, min(200, int(page_size)))
    pg = max(1, int(page))
    rows, total = paginate(db, stmt, page=pg, page_size=size)
    return [project_to_out(r, db, auth) for r in rows], total


def add_member(db: Session, project_id: str, body: ProjectMemberIn, auth: AuthContext) -> ProjectMemberOut:
    proj = db.get(ProjectRow, project_id)
    if proj is None:
        raise LookupError(msg.PROJECT_NOT_FOUND)
    actor_role: str | None = None
    if not is_platform_admin(auth):
        # 项目 owner，或本组织 owner/admin
        mem = db.scalars(
            select(ProjectMemberRow).where(
                ProjectMemberRow.project_id == project_id,
                ProjectMemberRow.user_id == auth.user_id,
            )
        ).first()
        from ..authz.rbac import org_admin_elevates_project  # 延迟：拆环 rbac ↔ projects

        org_owns = org_admin_elevates_project(db, auth, project_id=project_id)
        if (mem is None or mem.role != "owner") and not org_owns:
            raise PermissionError(msg.PROJECT_OWNER_ADMIN_ADD)
        actor_role = "owner" if org_owns or mem is None else (mem.role or "owner")
    user = db.scalars(select(UserRow).where(UserRow.username == body.username.strip())).first()
    if user is None:
        raise LookupError(msg.AUTH_USER_NOT_FOUND)
    role = (body.role or "member").strip() or "member"
    if role not in ("owner", "member", "viewer"):
        raise ValueError(msg.PROJECT_ROLE_OWNER_OR_MEMBER)
    poid = (getattr(proj, "org_id", None) or "").strip()
    if poid:
        from .organizations import ensure_org_member, org_member_role  # 延迟：organizations 顶栏已 import projects

        target_org_role = org_member_role(db, user.id, poid)
        if target_org_role is None:
            if is_platform_admin(auth):
                ensure_org_member(db, poid, user.id, role="member")
                target_org_role = org_member_role(db, user.id, poid)
            else:
                raise PermissionError(msg.PROJECT_MEMBER_MUST_BE_ORG_MEMBER)
        if target_org_role in ("owner", "admin"):
            role = "owner"
    if not is_platform_admin(auth):
        from ..authz.rbac import can_assign_project_role  # 延迟：拆环 rbac ↔ projects

        if not can_assign_project_role(actor_role, role):
            raise PermissionError(msg.PROJECT_ROLE_CANNOT_ELEVATE)
    existing = db.scalars(
        select(ProjectMemberRow).where(
            ProjectMemberRow.project_id == project_id,
            ProjectMemberRow.user_id == user.id,
        )
    ).first()
    if existing:
        existing.role = role
        db.commit()
        return ProjectMemberOut(
            user_id=user.id, username=user.username, role=role, project_id=project_id
        )
    db.add(
        ProjectMemberRow(
            id=new_id(),
            project_id=project_id,
            user_id=user.id,
            role=role,
        )
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalars(
            select(ProjectMemberRow).where(
                ProjectMemberRow.project_id == project_id,
                ProjectMemberRow.user_id == user.id,
            )
        ).first()
        if existing is None:
            raise
        existing.role = role
        db.commit()
    return ProjectMemberOut(
        user_id=user.id, username=user.username, role=role, project_id=project_id
    )


def remove_member(db: Session, project_id: str, user_id: str, auth: AuthContext) -> None:
    proj = db.get(ProjectRow, project_id)
    if proj is None:
        raise LookupError(msg.PROJECT_NOT_FOUND)
    if not is_platform_admin(auth):
        actor_member = db.scalars(
            select(ProjectMemberRow).where(
                ProjectMemberRow.project_id == project_id,
                ProjectMemberRow.user_id == auth.user_id,
            )
        ).first()
        from ..authz.rbac import org_admin_elevates_project  # 延迟：拆环 rbac ↔ projects

        org_owns = org_admin_elevates_project(db, auth, project_id=project_id)
        if (actor_member is None or actor_member.role != "owner") and not org_owns:
            raise PermissionError(msg.PROJECT_OWNER_ADMIN_REMOVE)
    member = db.scalars(
        select(ProjectMemberRow).where(
            ProjectMemberRow.project_id == project_id,
            ProjectMemberRow.user_id == user_id,
        )
    ).first()
    if member is None:
        raise LookupError(msg.PROJECT_MEMBER_NOT_FOUND)
    if member.role == "owner":
        owner_count = len(
            db.scalars(
                select(ProjectMemberRow).where(
                    ProjectMemberRow.project_id == project_id,
                    ProjectMemberRow.role == "owner",
                )
            ).all()
        )
        if owner_count <= 1:
            raise ValueError(msg.PROJECT_CANNOT_REMOVE_LAST_OWNER)
    db.delete(member)
    db.commit()


def list_members(
    db: Session,
    project_id: str,
    auth: AuthContext,
    *,
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[ProjectMemberOut], int]:
    assert_can_access_project(db, auth, project_id)
    proj = db.get(ProjectRow, project_id)
    poid = (getattr(proj, "org_id", None) or "").strip() if proj else ""
    from .organizations import org_member_role  # 延迟：organizations 顶栏已 import projects

    stmt = (
        select(ProjectMemberRow)
        .where(ProjectMemberRow.project_id == project_id)
        .order_by(ProjectMemberRow.role, ProjectMemberRow.user_id)
    )
    size = max(1, min(200, int(page_size)))
    pg = max(1, int(page))
    rows, total = paginate(db, stmt, page=pg, page_size=size)
    out: list[ProjectMemberOut] = []
    for m in rows:
        u = db.get(UserRow, m.user_id)
        role = m.role or "member"
        if poid:
            org_role = org_member_role(db, m.user_id, poid)
            if org_role in ("owner", "admin"):
                role = "owner"
        out.append(
            ProjectMemberOut(
                user_id=m.user_id,
                username=(u.username if u else ""),
                role=role,
                project_id=project_id,
            )
        )
    return out, total
