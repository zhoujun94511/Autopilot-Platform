"""细粒度资源 ACL：同一组织内跨项目分享执行资源；无 project_id 不是可见通道。"""

from __future__ import annotations

from ..core import api_messages as msg

from sqlalchemy import select
from sqlalchemy.orm import Session

from autopilot_platform.core.schemas import AclGrantIn, AclGrantOut

from ..auth import AuthContext
from ..core.list_page import slice_page
from ..core.models import ResourceAclRow, UserRow, db_get, new_id
from ..tenancy.projects import is_platform_admin, visible_project_filter


RESOURCE_TYPES = frozenset({"artifact", "job", "schedule", "app_build"})


def has_acl(
    db: Session,
    user_id: str,
    resource_type: str,
    resource_id: str,
    *,
    need_write: bool = False,
) -> bool:
    rows = list(
        db.scalars(
            select(ResourceAclRow).where(
                ResourceAclRow.resource_type == resource_type,
                ResourceAclRow.resource_id == resource_id,
                ResourceAclRow.user_id == user_id,
            )
        ).all()
    )
    if not rows:
        return False
    if not need_write:
        return True
    return any((r.permission or "read") == "write" for r in rows)


def can_access_resource(
    db: Session,
    auth: AuthContext,
    *,
    resource_type: str,
    resource_id: str,
    project_id: str = "",
    owner_username: str = "",
    need_write: bool = False,
) -> bool:
    """执行资源访问：委托 rbac.can（含项目角色 / ACL / Runner）。"""
    rtype = (resource_type or "").strip().lower()
    if rtype not in RESOURCE_TYPES:
        return False
    from .rbac import ACTION_READ, ACTION_WRITE, can

    return can(
        db,
        auth,
        rtype,
        ACTION_WRITE if need_write else ACTION_READ,
        project_id=project_id,
        resource_id=resource_id,
        owner_username=owner_username,
        allow_resource_acl=True,
    )


def runner_can_access_assigned_resource(
    db: Session,
    auth: AuthContext,
    *,
    resource_type: str,
    resource_id: str,
    need_write: bool = False,
) -> bool:
    """Runner Token：仅可访问已分配任务及其制品/应用。

    - 独立 Token：仅本 runner_id 的任务
    - 全局执行 Token（无 runner_id、非 admin）：任意 runner 的 claimed/running 任务相关资源
    """
    from autopilot_platform.core.constants import JobStatus

    from ..core.models import JobRow

    if not (resource_id or "").strip():
        return False
    rid = (auth.runner_id or "").strip()
    write_ok = frozenset({JobStatus.CLAIMED.value, JobStatus.RUNNING.value})
    q = select(JobRow)
    if rid:
        q = q.where(JobRow.runner_id == rid)
    else:
        # 全局执行通道：不得枚举历史任务资源，仅进行中
        q = q.where(JobRow.status.in_(list(write_ok)))
    jobs = list(db.scalars(q).all())
    for job in jobs:
        if need_write and (job.status or "") not in write_ok:
            continue
        if resource_type == "job" and str(job.id) == resource_id:
            return True
        if resource_type == "artifact" and str(job.artifact_id or "") == resource_id:
            return True
        if resource_type == "app_build" and str(
            getattr(job, "app_build_id", None) or ""
        ) == resource_id:
            return True
    return False


def assert_can_access_resource(
    db: Session,
    auth: AuthContext,
    *,
    resource_type: str,
    resource_id: str,
    project_id: str = "",
    owner_username: str = "",
    need_write: bool = False,
) -> None:
    if not can_access_resource(
        db,
        auth,
        resource_type=resource_type,
        resource_id=resource_id,
        project_id=project_id,
        owner_username=owner_username,
        need_write=need_write,
    ):
        raise PermissionError(msg.ACL_NO_ACCESS)


def assert_can_manage_acl(
    db: Session,
    auth: AuthContext,
    *,
    resource_type: str,
    resource_id: str,
    project_id: str = "",
    owner_username: str = "",
) -> None:
    """仅项目成员(写) / 平台 admin 可分享。无 project_id 的脏行不能再经 ACL 打开通道。"""
    pid = (project_id or "").strip()
    if not pid:
        raise PermissionError(msg.PROJECT_ID_REQUIRED)
    if is_platform_admin(auth):
        return
    assert_can_access_resource(
        db,
        auth,
        resource_type=resource_type,
        resource_id=resource_id,
        project_id=pid,
        owner_username=owner_username,
        need_write=True,
    )


def _resolve_resource_meta(db: Session, resource_type: str, resource_id: str) -> tuple[str, str]:
    """返回 (project_id, owner_username)。"""
    if resource_type == "artifact":
        from ..core.models import ArtifactRow

        row = db_get(db, ArtifactRow, resource_id)
        if row is None:
            raise LookupError(msg.ARTIFACT_NOT_FOUND)
        return row.project_id or "", row.uploaded_by or ""
    if resource_type == "job":
        from ..core.models import JobRow

        row = db_get(db, JobRow, resource_id)
        if row is None:
            raise LookupError(msg.JOB_NOT_FOUND)
        return row.project_id or "", row.created_by or ""
    if resource_type == "schedule":
        from ..core.models import ScheduleRow

        row = db_get(db, ScheduleRow, resource_id)
        if row is None:
            raise LookupError(msg.SCHEDULE_NOT_FOUND)
        return row.project_id or "", row.created_by or ""
    if resource_type == "app_build":
        from ..core.models import AppBuildRow

        row = db_get(db, AppBuildRow, resource_id)
        if row is None:
            raise LookupError(msg.APP_BUILD_NOT_FOUND)
        return row.project_id or "", row.uploaded_by or ""
    raise ValueError(f"unsupported resource_type: {resource_type}")


def grant_acl(db: Session, body: AclGrantIn, auth: AuthContext) -> AclGrantOut:
    rtype = (body.resource_type or "").strip().lower()
    rid = (body.resource_id or "").strip()
    if rtype not in RESOURCE_TYPES:
        raise ValueError(msg.ACL_RESOURCE_TYPE)
    if not rid:
        raise ValueError(msg.ACL_RESOURCE_ID_REQUIRED)
    perm = (body.permission or "read").strip() or "read"
    if perm not in ("read", "write"):
        raise ValueError(msg.ACL_PERMISSION)
    project_id, owner = _resolve_resource_meta(db, rtype, rid)
    assert_can_manage_acl(
        db,
        auth,
        resource_type=rtype,
        resource_id=rid,
        project_id=project_id,
        owner_username=owner,
    )
    user = db.scalars(select(UserRow).where(UserRow.username == body.username.strip())).first()
    if user is None:
        raise LookupError(msg.AUTH_USER_NOT_FOUND)
    if project_id:
        from .rbac import user_in_project_org

        if not user_in_project_org(db, user.id, project_id):
            raise PermissionError(msg.PROJECT_MEMBER_MUST_BE_ORG_MEMBER)
    existing = db.scalars(
        select(ResourceAclRow).where(
            ResourceAclRow.resource_type == rtype,
            ResourceAclRow.resource_id == rid,
            ResourceAclRow.user_id == user.id,
        )
    ).first()
    if existing:
        existing.permission = perm
        db.commit()
        db.refresh(existing)
        return _acl_out(existing, user.username)
    row = ResourceAclRow(
        id=new_id(),
        resource_type=rtype,
        resource_id=rid,
        user_id=user.id,
        permission=perm,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _acl_out(row, user.username)


def list_acl(
    db: Session,
    auth: AuthContext,
    *,
    resource_type: str,
    resource_id: str,
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[AclGrantOut], int]:
    rtype = (resource_type or "").strip().lower()
    rid = (resource_id or "").strip()
    project_id, owner = _resolve_resource_meta(db, rtype, rid)
    assert_can_access_resource(
        db,
        auth,
        resource_type=rtype,
        resource_id=rid,
        project_id=project_id,
        owner_username=owner,
    )
    rows = list(
        db.scalars(
            select(ResourceAclRow).where(
                ResourceAclRow.resource_type == rtype,
                ResourceAclRow.resource_id == rid,
            )
        ).all()
    )
    size = max(1, min(200, int(page_size)))
    pg = max(1, int(page))
    page_rows, total = slice_page(rows, page=pg, page_size=size)
    out: list[AclGrantOut] = []
    for r in page_rows:
        u = db_get(db, UserRow, r.user_id)
        out.append(_acl_out(r, u.username if u else ""))
    return out, total


def revoke_acl(db: Session, acl_id: str, auth: AuthContext) -> AclGrantOut:
    """撤销 ACL；返回撤销前快照供审计。"""
    row = db_get(db, ResourceAclRow, acl_id)
    if row is None:
        raise LookupError(msg.ACL_NOT_FOUND)
    project_id, owner = _resolve_resource_meta(
        db, str(row.resource_type), str(row.resource_id)
    )
    assert_can_manage_acl(
        db,
        auth,
        resource_type=str(row.resource_type),
        resource_id=str(row.resource_id),
        project_id=project_id,
        owner_username=owner,
    )
    u = db_get(db, UserRow, row.user_id)
    snap = _acl_out(row, u.username if u else "")
    db.delete(row)
    db.commit()
    return snap


def _acl_out(row: ResourceAclRow, username: str) -> AclGrantOut:
    return AclGrantOut(
        id=row.id,
        resource_type=row.resource_type,
        resource_id=row.resource_id,
        user_id=row.user_id,
        username=username,
        permission=row.permission or "read",
        created_at=row.created_at,
    )


def filter_resources_by_acl(
    db: Session,
    auth: AuthContext,
    rows: list,
    *,
    resource_type: str,
    project_attr: str = "project_id",
    owner_attr: str = "uploaded_by",
    id_attr: str = "id",
) -> list:
    """按可见项目 + 同组织 ACL 过滤；无 project_id 行不可见。

    ``owner_attr`` 仅保留调用方兼容；创建者通道已取消，过滤不再使用。
    """
    _ = owner_attr  # API 兼容形参
    if is_platform_admin(auth):
        return rows
    if auth.kind != "user":
        return rows
    allowed_projects = visible_project_filter(db, auth) or set()
    shared_ids = set(
        db.scalars(
            select(ResourceAclRow.resource_id).where(
                ResourceAclRow.resource_type == resource_type,
                ResourceAclRow.user_id == auth.user_id,
            )
        ).all()
    )
    from .rbac import user_in_project_org

    out = []
    for r in rows:
        pid = (getattr(r, project_attr, None) or "").strip()
        rid = getattr(r, id_attr, "")
        if pid:
            if pid in allowed_projects:
                out.append(r)
                continue
            # 同组织 ACL 才有效；跨组织残留分享丢弃
            if rid in shared_ids and user_in_project_org(db, auth.user_id, pid):
                out.append(r)
            continue
        continue
    return out


def acl_overfetch_limit(limit: int, offset: int) -> int:
    """ACL 过滤前多取一些行，降低跳页空洞。"""
    base = max(int(limit) + int(offset), int(limit), 1)
    return max(base * 3, int(limit) or 1)


def window_after_acl(rows: list, *, allow, limit: int, offset: int) -> list:
    """对已排序的候选行做 ACL 过滤，再按 offset/limit 取窗口（对齐 list_reports）。"""
    out: list = []
    skipped = 0
    for r in rows:
        if not allow(r):
            continue
        if skipped < offset:
            skipped += 1
            continue
        out.append(r)
        if len(out) >= limit:
            break
    return out


# re-export helpers
__all__ = [
    "RESOURCE_TYPES",
    "acl_overfetch_limit",
    "assert_can_access_resource",
    "assert_can_manage_acl",
    "can_access_resource",
    "filter_resources_by_acl",
    "grant_acl",
    "has_acl",
    "list_acl",
    "revoke_acl",
    "runner_can_access_assigned_resource",
    "window_after_acl",
]
