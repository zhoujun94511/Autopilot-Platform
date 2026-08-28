"""组织 / 事业部（企业软多租户上层）。"""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from autopilot_platform.core.schemas import (
    OrganizationCreate,
    OrganizationMemberIn,
    OrganizationMemberOut,
    OrganizationOut,
    OrganizationPolicies,
    OrganizationPoliciesPatch,
)

from ..core import api_messages as msg
from ..auth import AuthContext
from ..core.models import OrganizationMemberRow, OrganizationRow, UserRow, db_get, new_id
from .projects import is_platform_admin
from ..core.list_page import slice_page
from ..services.shared.pagination import paginate

ORG_POLICY_KEYS: tuple[str, ...] = (
    "members_can_create_projects",
    "members_can_invite",
)


def default_org_policies() -> dict[str, bool]:
    return {k: False for k in ORG_POLICY_KEYS}


def parse_org_policies(raw: str | None) -> dict[str, bool]:
    out = default_org_policies()
    text = (raw or "").strip()
    if not text or text == "{}":
        return out
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return out
    if not isinstance(data, dict):
        return out
    for key in ORG_POLICY_KEYS:
        if key in data:
            out[key] = bool(data[key])
    return out


def org_policies_of(row: OrganizationRow) -> dict[str, bool]:
    return parse_org_policies(getattr(row, "policies_json", None))


def org_policy_enabled(db: Session, org_id: str, key: str) -> bool:
    oid = (org_id or "").strip()
    if not oid or key not in ORG_POLICY_KEYS:
        return False
    row = db_get(db, OrganizationRow, oid)
    if row is None:
        return False
    return bool(org_policies_of(row).get(key))


def org_to_out(row: OrganizationRow, *, my_role: str = "") -> OrganizationOut:
    return OrganizationOut(
        id=row.id,
        name=row.name or "",
        description=row.description or "",
        created_by=row.created_by or "",
        created_at=row.created_at,
        my_role=my_role,
        policies=OrganizationPolicies.model_validate(org_policies_of(row)),
    )


def member_org_ids(db: Session, user_id: str) -> set[str]:
    rows = db.scalars(
        select(OrganizationMemberRow.org_id).where(OrganizationMemberRow.user_id == user_id)
    ).all()
    return set(rows)


def admin_org_ids(db: Session, user_id: str) -> set[str]:
    """用户担任 owner/admin 的组织（不含普通 member）。"""
    uid = (user_id or "").strip()
    if not uid:
        return set()
    rows = db.scalars(
        select(OrganizationMemberRow.org_id).where(
            OrganizationMemberRow.user_id == uid,
            OrganizationMemberRow.role.in_(("owner", "admin")),
        )
    ).all()
    return set(rows)


def org_member_role(db: Session, user_id: str, org_id: str) -> str | None:
    oid = (org_id or "").strip()
    uid = (user_id or "").strip()
    if not oid or not uid:
        return None
    row = db.scalars(
        select(OrganizationMemberRow).where(
            OrganizationMemberRow.org_id == oid,
            OrganizationMemberRow.user_id == uid,
        )
    ).first()
    return (row.role if row else None) or None


def ensure_org_member(
    db: Session, org_id: str, user_id: str, *, role: str = "member"
) -> None:
    """若尚非该组织成员则加入；已有角色不改。"""
    oid = (org_id or "").strip()
    uid = (user_id or "").strip()
    if not oid or not uid:
        return
    if db_get(db, OrganizationRow, oid) is None:
        return
    if org_member_role(db, uid, oid) is not None:
        return
    r = (role or "member").strip() or "member"
    if r not in ("owner", "admin", "member"):
        r = "member"
    db.add(
        OrganizationMemberRow(
            id=new_id(),
            org_id=oid,
            user_id=uid,
            role=r,
        )
    )
    db.flush()


def assert_can_access_org(db: Session, auth: AuthContext, org_id: str) -> None:
    oid = (org_id or "").strip()
    if not oid:
        raise PermissionError(msg.ORG_NO_ACCESS)
    from ..authz.rbac import ACTION_READ, RESOURCE_ORG, can  # 延迟：拆环 rbac ↔ organizations

    if can(db, auth, RESOURCE_ORG, ACTION_READ, org_id=oid):
        return
    raise PermissionError(msg.ORG_NO_ACCESS)


def assert_can_manage_org(db: Session, auth: AuthContext, org_id: str) -> None:
    """owner / admin / platform admin。"""
    oid = (org_id or "").strip()
    if not oid:
        raise PermissionError(msg.ORG_NO_ACCESS)
    from ..authz.rbac import ACTION_MANAGE_MEMBERS, RESOURCE_ORG, can  # 延迟：拆环 rbac ↔ organizations

    if can(db, auth, RESOURCE_ORG, ACTION_MANAGE_MEMBERS, org_id=oid):
        return
    raise PermissionError(msg.ORG_OWNER_ADMIN_REQUIRED)


def create_organization(
    db: Session, body: OrganizationCreate, auth: AuthContext
) -> OrganizationOut:
    if auth.kind != "user":
        raise PermissionError(msg.AUTH_USER_LOGIN_REQUIRED)
    from ..authz.rbac import ACTION_CREATE, RESOURCE_ORG, can  # 延迟：拆环 rbac ↔ organizations

    if not can(db, auth, RESOURCE_ORG, ACTION_CREATE):
        raise PermissionError(msg.AUTH_ADMIN_REQUIRED)
    oid = body.id.strip()
    if not oid:
        raise ValueError("请指定组织 ID。")
    if db_get(db, OrganizationRow, oid) is not None:
        raise LookupError(msg.ORG_ALREADY_EXISTS.format(org_id=oid))
    row = OrganizationRow(
        id=oid,
        name=(body.name or oid).strip(),
        description=body.description or "",
        created_by=auth.username or auth.user_id,
        policies_json="{}",
    )
    db.add(row)
    db.flush()
    db.add(
        OrganizationMemberRow(
            id=new_id(),
            org_id=oid,
            user_id=auth.user_id,
            role="owner",
        )
    )
    db.commit()
    db.refresh(row)
    return org_to_out(row, my_role="owner")


def list_organizations(
    db: Session,
    auth: AuthContext,
    *,
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[OrganizationOut], int]:
    rows = list(db.scalars(select(OrganizationRow).order_by(OrganizationRow.id)).all())
    if is_platform_admin(auth):
        filtered = [org_to_out(r, my_role="admin") for r in rows]
    elif auth.kind != "user":
        filtered = []
    else:
        allowed = member_org_ids(db, auth.user_id)
        filtered = [
            org_to_out(r, my_role=org_member_role(db, auth.user_id, r.id) or "member")
            for r in rows
            if r.id in allowed
        ]
    size = max(1, min(200, int(page_size)))
    pg = max(1, int(page))
    return slice_page(filtered, page=pg, page_size=size)


def get_organization(db: Session, org_id: str, auth: AuthContext) -> OrganizationOut:
    row = db_get(db, OrganizationRow, (org_id or "").strip())
    if row is None:
        raise LookupError(msg.ORG_NOT_FOUND)
    org_id_s = str(row.id)
    assert_can_access_org(db, auth, org_id_s)
    role = (
        "admin"
        if is_platform_admin(auth)
        else (org_member_role(db, auth.user_id, org_id_s) or "")
    )
    return org_to_out(row, my_role=role)


def update_org_policies(
    db: Session, org_id: str, body: OrganizationPoliciesPatch, auth: AuthContext
) -> OrganizationOut:
    oid = (org_id or "").strip()
    row = db_get(db, OrganizationRow, oid)
    if row is None:
        raise LookupError(msg.ORG_NOT_FOUND)
    assert_can_manage_org(db, auth, oid)
    current = org_policies_of(row)
    if body.members_can_create_projects is not None:
        current["members_can_create_projects"] = bool(body.members_can_create_projects)
    if body.members_can_invite is not None:
        current["members_can_invite"] = bool(body.members_can_invite)
    row.policies_json = json.dumps(current, ensure_ascii=False, separators=(",", ":"))
    db.commit()
    db.refresh(row)
    role = (
        "admin"
        if is_platform_admin(auth)
        else (org_member_role(db, auth.user_id, oid) or "")
    )
    return org_to_out(row, my_role=role)


def assert_can_add_org_member(
    db: Session, auth: AuthContext, org_id: str, *, target_role: str
) -> None:
    oid = (org_id or "").strip()
    if not oid:
        raise PermissionError(msg.ORG_NO_ACCESS)
    if is_platform_admin(auth):
        return
    from ..authz.rbac import ACTION_MANAGE_MEMBERS, RESOURCE_ORG, can, can_assign_org_role  # 延迟：拆环 rbac ↔ organizations

    actor = org_member_role(db, auth.user_id, oid)
    if can(db, auth, RESOURCE_ORG, ACTION_MANAGE_MEMBERS, org_id=oid):
        if not can_assign_org_role(actor, target_role):
            raise PermissionError(msg.ORG_ROLE_CANNOT_ELEVATE)
        return
    if org_policy_enabled(db, oid, "members_can_invite") and actor == "member":
        if target_role != "member":
            raise PermissionError(msg.ORG_ROLE_CANNOT_ELEVATE)
        return
    raise PermissionError(msg.ORG_OWNER_ADMIN_REQUIRED)


def add_org_member(
    db: Session, org_id: str, body: OrganizationMemberIn, auth: AuthContext
) -> OrganizationMemberOut:
    oid = (org_id or "").strip()
    row = db_get(db, OrganizationRow, oid)
    if row is None:
        raise LookupError(msg.ORG_NOT_FOUND)
    user = db.scalars(select(UserRow).where(UserRow.username == body.username.strip())).first()
    if user is None:
        raise LookupError(msg.AUTH_USER_NOT_FOUND)
    role = (body.role or "member").strip() or "member"
    if role not in ("owner", "admin", "member"):
        raise ValueError(msg.ORG_ROLE_INVALID)
    assert_can_add_org_member(db, auth, oid, target_role=role)
    actor = None if is_platform_admin(auth) else org_member_role(db, auth.user_id, oid)
    existing = db.scalars(
        select(OrganizationMemberRow).where(
            OrganizationMemberRow.org_id == oid,
            OrganizationMemberRow.user_id == user.id,
        )
    ).first()
    if existing:
        if actor == "member":
            if existing.role != "member" or role != "member":
                raise PermissionError(msg.ORG_ROLE_CANNOT_ELEVATE)
            return OrganizationMemberOut(
                user_id=user.id, username=user.username, role=existing.role, org_id=oid
            )
        existing.role = role
        db.commit()
        return OrganizationMemberOut(
            user_id=user.id, username=user.username, role=role, org_id=oid
        )
    db.add(
        OrganizationMemberRow(
            id=new_id(),
            org_id=oid,
            user_id=user.id,
            role=role,
        )
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalars(
            select(OrganizationMemberRow).where(
                OrganizationMemberRow.org_id == oid,
                OrganizationMemberRow.user_id == user.id,
            )
        ).first()
        if existing is None:
            raise
        if actor == "member":
            if existing.role != "member" or role != "member":
                raise PermissionError(msg.ORG_ROLE_CANNOT_ELEVATE)
            return OrganizationMemberOut(
                user_id=user.id, username=user.username, role=existing.role, org_id=oid
            )
        existing.role = role
        db.commit()
    return OrganizationMemberOut(
        user_id=user.id, username=user.username, role=role, org_id=oid
    )


def remove_org_member(db: Session, org_id: str, user_id: str, auth: AuthContext) -> None:
    oid = (org_id or "").strip()
    assert_can_manage_org(db, auth, oid)
    member = db.scalars(
        select(OrganizationMemberRow).where(
            OrganizationMemberRow.org_id == oid,
            OrganizationMemberRow.user_id == user_id,
        )
    ).first()
    if member is None:
        raise LookupError(msg.ORG_MEMBER_NOT_FOUND)
    if member.role == "owner":
        owners = len(
            db.scalars(
                select(OrganizationMemberRow).where(
                    OrganizationMemberRow.org_id == oid,
                    OrganizationMemberRow.role == "owner",
                )
            ).all()
        )
        if owners <= 1:
            raise ValueError(msg.ORG_CANNOT_REMOVE_LAST_OWNER)
    db.delete(member)
    db.commit()


def list_org_members(
    db: Session,
    org_id: str,
    auth: AuthContext,
    *,
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[OrganizationMemberOut], int]:
    oid = (org_id or "").strip()
    assert_can_access_org(db, auth, oid)
    stmt = (
        select(OrganizationMemberRow)
        .where(OrganizationMemberRow.org_id == oid)
        .order_by(OrganizationMemberRow.role, OrganizationMemberRow.user_id)
    )
    size = max(1, min(200, int(page_size)))
    pg = max(1, int(page))
    rows, total = paginate(db, stmt, page=pg, page_size=size)
    out: list[OrganizationMemberOut] = []
    for m in rows:
        u = db.get(UserRow, m.user_id)
        out.append(
            OrganizationMemberOut(
                user_id=m.user_id,
                username=(u.username if u else ""),
                role=m.role or "member",
                org_id=oid,
            )
        )
    return out, total
