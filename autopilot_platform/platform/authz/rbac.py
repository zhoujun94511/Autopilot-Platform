"""Harbor 风格 RBAC：ROLE_POLICIES + can() 统一求值。

边界真源：docs/architecture/RBAC_BOUNDARY_CONTRACT.md
组织是租户硬隔离；本组织 owner/admin 对本组织项目 ≡ project:owner；
org member 进组织 ≠ 进项目；跨组织 project_members 无效。
"""

from __future__ import annotations

from typing import Final

from sqlalchemy.orm import Session

from ..auth import AuthContext, is_platform_admin
from ..core.models import ProjectRow

# ---------------------------------------------------------------------------
# Resource / Action 枚举（可测常量）
# ---------------------------------------------------------------------------

RESOURCE_ORG: Final = "org"
RESOURCE_PROJECT: Final = "project"
RESOURCE_DESIGN: Final = "design"
RESOURCE_ARTIFACT: Final = "artifact"
RESOURCE_JOB: Final = "job"
RESOURCE_SCHEDULE: Final = "schedule"
RESOURCE_APP_BUILD: Final = "app_build"
RESOURCE_ACL: Final = "resource_acl"
RESOURCE_DEVICE: Final = "device"
RESOURCE_POOL: Final = "resource_pool"

ACTION_READ: Final = "read"
ACTION_WRITE: Final = "write"
ACTION_CREATE: Final = "create"
ACTION_META_READ: Final = "meta_read"
ACTION_MANAGE_MEMBERS: Final = "manage_members"
ACTION_MANAGE_USERS: Final = "manage_users"
ACTION_MANAGE: Final = "manage"
ACTION_LIST: Final = "list"

# 项目内容资源（本组织成员 ∩ (project_members / 本组织 owner·admin / 同组织 ACL)；平台 admin 旁路）
PROJECT_CONTENT_RESOURCES: Final = frozenset(
    {
        RESOURCE_DESIGN,
        RESOURCE_ARTIFACT,
        RESOURCE_JOB,
        RESOURCE_SCHEDULE,
        RESOURCE_APP_BUILD,
        RESOURCE_ACL,
        RESOURCE_PROJECT,  # meta_read / manage_members 等
    }
)

EXECUTION_RESOURCES: Final = frozenset(
    {
        RESOURCE_ARTIFACT,
        RESOURCE_JOB,
        RESOURCE_SCHEDULE,
        RESOURCE_APP_BUILD,
    }
)

PLATFORM_ROLES: Final = frozenset({"admin", "operator"})
ORG_ROLES: Final = frozenset({"owner", "admin", "member"})
PROJECT_ROLES: Final = frozenset({"owner", "member", "viewer"})

# role_key → 允许的 (resource, action) 集合
# org:* 策略表只含组织治理；本组织项目内容权在 can() 按「是否该组织 owner/admin」提升
# 跨组织成员行无效，不在策略表里用 org 角色直接发 design.write
ROLE_POLICIES: Final[dict[str, frozenset[tuple[str, str]]]] = {
    "platform:admin": frozenset(
        {
            (RESOURCE_ORG, ACTION_READ),
            (RESOURCE_ORG, ACTION_MANAGE_MEMBERS),
            (RESOURCE_ORG, ACTION_MANAGE_USERS),
            (RESOURCE_ORG, ACTION_CREATE),
            (RESOURCE_PROJECT, ACTION_CREATE),
            (RESOURCE_PROJECT, ACTION_META_READ),
            (RESOURCE_PROJECT, ACTION_MANAGE_MEMBERS),
            (RESOURCE_PROJECT, ACTION_READ),
            (RESOURCE_PROJECT, ACTION_WRITE),
            (RESOURCE_DESIGN, ACTION_READ),
            (RESOURCE_DESIGN, ACTION_WRITE),
            (RESOURCE_ARTIFACT, ACTION_READ),
            (RESOURCE_ARTIFACT, ACTION_WRITE),
            (RESOURCE_JOB, ACTION_READ),
            (RESOURCE_JOB, ACTION_WRITE),
            (RESOURCE_SCHEDULE, ACTION_READ),
            (RESOURCE_SCHEDULE, ACTION_WRITE),
            (RESOURCE_APP_BUILD, ACTION_READ),
            (RESOURCE_APP_BUILD, ACTION_WRITE),
            (RESOURCE_ACL, ACTION_READ),
            (RESOURCE_ACL, ACTION_MANAGE),
            (RESOURCE_DEVICE, ACTION_LIST),
            (RESOURCE_POOL, ACTION_READ),
            (RESOURCE_POOL, ACTION_MANAGE),
        }
    ),
    "org:owner": frozenset(
        {
            (RESOURCE_ORG, ACTION_READ),
            (RESOURCE_ORG, ACTION_MANAGE_MEMBERS),
            (RESOURCE_ORG, ACTION_MANAGE_USERS),
            (RESOURCE_PROJECT, ACTION_CREATE),
            (RESOURCE_POOL, ACTION_READ),
            (RESOURCE_POOL, ACTION_MANAGE),
        }
    ),
    "org:admin": frozenset(
        {
            (RESOURCE_ORG, ACTION_READ),
            (RESOURCE_ORG, ACTION_MANAGE_MEMBERS),
            (RESOURCE_ORG, ACTION_MANAGE_USERS),
            (RESOURCE_PROJECT, ACTION_CREATE),
            (RESOURCE_POOL, ACTION_READ),
            (RESOURCE_POOL, ACTION_MANAGE),
        }
    ),
    "org:member": frozenset(
        {
            (RESOURCE_ORG, ACTION_READ),
            # 建项目默认关；组织策略 members_can_create_projects 打开后由 can() 额外放行
        }
    ),
    "project:owner": frozenset(
        {
            (RESOURCE_PROJECT, ACTION_META_READ),
            (RESOURCE_PROJECT, ACTION_MANAGE_MEMBERS),
            (RESOURCE_PROJECT, ACTION_READ),
            (RESOURCE_PROJECT, ACTION_WRITE),
            (RESOURCE_DESIGN, ACTION_READ),
            (RESOURCE_DESIGN, ACTION_WRITE),
            (RESOURCE_ARTIFACT, ACTION_READ),
            (RESOURCE_ARTIFACT, ACTION_WRITE),
            (RESOURCE_JOB, ACTION_READ),
            (RESOURCE_JOB, ACTION_WRITE),
            (RESOURCE_SCHEDULE, ACTION_READ),
            (RESOURCE_SCHEDULE, ACTION_WRITE),
            (RESOURCE_APP_BUILD, ACTION_READ),
            (RESOURCE_APP_BUILD, ACTION_WRITE),
            (RESOURCE_ACL, ACTION_READ),
            (RESOURCE_ACL, ACTION_MANAGE),
            (RESOURCE_POOL, ACTION_READ),
        }
    ),
    "project:member": frozenset(
        {
            (RESOURCE_PROJECT, ACTION_META_READ),
            (RESOURCE_PROJECT, ACTION_READ),
            (RESOURCE_PROJECT, ACTION_WRITE),
            (RESOURCE_DESIGN, ACTION_READ),
            (RESOURCE_DESIGN, ACTION_WRITE),
            (RESOURCE_ARTIFACT, ACTION_READ),
            (RESOURCE_ARTIFACT, ACTION_WRITE),
            (RESOURCE_JOB, ACTION_READ),
            (RESOURCE_JOB, ACTION_WRITE),
            (RESOURCE_SCHEDULE, ACTION_READ),
            (RESOURCE_SCHEDULE, ACTION_WRITE),
            (RESOURCE_APP_BUILD, ACTION_READ),
            (RESOURCE_APP_BUILD, ACTION_WRITE),
            (RESOURCE_ACL, ACTION_READ),
            (RESOURCE_ACL, ACTION_MANAGE),
            (RESOURCE_POOL, ACTION_READ),
        }
    ),
    "project:viewer": frozenset(
        {
            (RESOURCE_PROJECT, ACTION_META_READ),
            (RESOURCE_PROJECT, ACTION_READ),
            (RESOURCE_DESIGN, ACTION_READ),
            (RESOURCE_ARTIFACT, ACTION_READ),
            (RESOURCE_JOB, ACTION_READ),
            (RESOURCE_SCHEDULE, ACTION_READ),
            (RESOURCE_APP_BUILD, ACTION_READ),
            (RESOURCE_ACL, ACTION_READ),
            (RESOURCE_POOL, ACTION_READ),
            # write / manage 需显式 ResourceAcl，不在策略表
        }
    ),
}

# 角色等级（Phase 2 邀请不提权）
ORG_ROLE_RANK: Final[dict[str, int]] = {"member": 1, "admin": 2, "owner": 3}
PROJECT_ROLE_RANK: Final[dict[str, int]] = {"viewer": 1, "member": 2, "owner": 3}


def policy_allows(role_key: str, resource: str, action: str) -> bool:
    """查 ROLE_POLICIES；未知 role_key → False。"""
    allowed = ROLE_POLICIES.get(role_key)
    if not allowed:
        return False
    return (resource, action) in allowed


def org_role_key(role: str | None) -> str | None:
    r = (role or "").strip()
    if r not in ORG_ROLES:
        return None
    return f"org:{r}"


def org_admin_elevates_project(
    db: Session,
    auth: AuthContext,
    *,
    project_id: str = "",
    org_id: str = "",
) -> bool:
    """本组织 owner/admin 对本组织项目 ≡ project owner（不是「覆盖 viewer」）。"""
    if auth.kind != "user" or not (auth.user_id or "").strip():
        return False
    pid = (project_id or "").strip()
    poid = ""
    if pid:
        prow = db.get(ProjectRow, pid)
        poid = (getattr(prow, "org_id", None) or "").strip() if prow else ""
    if not poid:
        poid = (org_id or "").strip()
    if not poid:
        return False
    from ..tenancy.organizations import org_member_role  # 延迟：拆环 rbac ↔ organizations

    role = (org_member_role(db, auth.user_id, poid) or "").strip()
    return role in ("owner", "admin")


def user_in_project_org(db: Session, user_id: str, project_id: str) -> bool:
    """项目有 org_id 时，用户必须是该组织成员；无组织项目一律不可见。"""
    uid = (user_id or "").strip()
    pid = (project_id or "").strip()
    if not uid or not pid:
        return False
    prow = db.get(ProjectRow, pid)
    if prow is None:
        return False
    poid = (getattr(prow, "org_id", None) or "").strip()
    if not poid:
        return False
    from ..tenancy.organizations import org_member_role  # 延迟：拆环 rbac ↔ organizations

    return org_member_role(db, uid, poid) is not None


def project_role_key(role: str | None) -> str | None:
    r = (role or "").strip()
    if r not in PROJECT_ROLES:
        return None
    return f"project:{r}"


def can_assign_org_role(actor_role: str | None, target_role: str | None) -> bool:
    """邀请/加成员：不能授予高于自己的组织角色。platform admin 在调用方旁路。"""
    ar = ORG_ROLE_RANK.get((actor_role or "").strip(), 0)
    tr = ORG_ROLE_RANK.get((target_role or "").strip(), 0)
    if ar <= 0 or tr <= 0:
        return False
    return tr <= ar


def can_assign_project_role(actor_role: str | None, target_role: str | None) -> bool:
    ar = PROJECT_ROLE_RANK.get((actor_role or "").strip(), 0)
    tr = PROJECT_ROLE_RANK.get((target_role or "").strip(), 0)
    if ar <= 0 or tr <= 0:
        return False
    return tr <= ar


def can(
    db: Session,
    auth: AuthContext,
    resource: str,
    action: str,
    *,
    project_id: str = "",
    org_id: str = "",
    resource_id: str = "",
    owner_username: str = "",
    allow_resource_acl: bool = True,
) -> bool:
    """统一权限求值。

    优先级见 RBAC_BOUNDARY_CONTRACT.md：platform admin → runner
    → 必须是项目所属组织成员 → 本组织 owner/admin ≡ project:owner
    → project 角色 → 同组织 ACL → deny。

    ``owner_username`` 仅保留调用方兼容；创建者通道已取消，求值不再使用。
    """
    from ..tenancy.projects import member_role  # 延迟：拆环 rbac ↔ projects

    _ = owner_username  # API 兼容形参
    res = (resource or "").strip()
    act = (action or "").strip()
    if not res or not act:
        return False

    if is_platform_admin(auth):
        return policy_allows("platform:admin", res, act)

    if auth.kind == "runner":
        return _runner_can(db, auth, res, act, resource_id=resource_id)

    if auth.kind != "user":
        return False

    pid = (project_id or "").strip()
    oid = (org_id or getattr(auth, "org_id", "") or "").strip()

    # 项目内容：先卡组织硬隔离，再项目角色 / 本组织管理员 / 同组织 ACL
    if res in PROJECT_CONTENT_RESOURCES and act != ACTION_CREATE:
        if pid:
            if not user_in_project_org(db, auth.user_id, pid):
                return False
            prole = member_role(db, auth.user_id, pid)
            pkey = project_role_key(prole)
            if pkey and policy_allows(pkey, res, act):
                return True
            if org_admin_elevates_project(db, auth, project_id=pid, org_id=oid):
                if policy_allows("project:owner", res, act):
                    return True
            # viewer 写 / 非成员：执行资源可走显式 ACL
            if (
                allow_resource_acl
                and res in EXECUTION_RESOURCES
                and resource_id
            ):
                from .acl import has_acl  # 延迟：仅执行资源 ACL 分支；acl 顶栏 import projects

                need_write = act in (ACTION_WRITE, ACTION_MANAGE)
                if has_acl(
                    db, auth.user_id, res, resource_id, need_write=need_write
                ):
                    return True
            return False
        return False

    # 组织治理 / 建项目
    if res == RESOURCE_ORG or (res == RESOURCE_PROJECT and act == ACTION_CREATE):
        if not oid:
            return False
        from ..tenancy.organizations import org_member_role, org_policy_enabled  # 延迟：拆环 rbac ↔ organizations

        orole = org_member_role(db, auth.user_id, oid)
        okey = org_role_key(orole)
        if okey and policy_allows(okey, res, act):
            return True
        if (
            res == RESOURCE_PROJECT
            and act == ACTION_CREATE
            and okey == "org:member"
            and org_policy_enabled(db, oid, "members_can_create_projects")
        ):
            return True
        return False

    if res == RESOURCE_POOL:
        if oid:
            from ..tenancy.organizations import org_member_role  # 延迟：拆环 rbac ↔ organizations

            okey = org_role_key(org_member_role(db, auth.user_id, oid))
            if okey and policy_allows(okey, res, act):
                return True
        if pid and act == ACTION_READ:
            pkey = project_role_key(member_role(db, auth.user_id, pid))
            return bool(pkey and policy_allows(pkey, res, act))
        return False

    if res == RESOURCE_DEVICE and act == ACTION_LIST:
        # 设备软隔离在 list 层过滤；此处仅表示「可调用列表」
        return True

    return False


def _runner_can(
    db: Session,
    auth: AuthContext,
    resource: str,
    action: str,
    *,
    resource_id: str = "",
) -> bool:
    """Runner：仅执行资源读写，且受已分配 Job / scope 约束（委托 acl）。"""
    if resource not in EXECUTION_RESOURCES:
        return False
    if action not in (ACTION_READ, ACTION_WRITE):
        return False
    if not resource_id:
        return False
    from .acl import runner_can_access_assigned_resource

    return runner_can_access_assigned_resource(
        db,
        auth,
        resource_type=resource,
        resource_id=resource_id,
        need_write=(action == ACTION_WRITE),
    )


def assert_can(
    db: Session,
    auth: AuthContext,
    resource: str,
    action: str,
    *,
    project_id: str = "",
    org_id: str = "",
    resource_id: str = "",
    owner_username: str = "",
    allow_resource_acl: bool = True,
    error: str | None = None,
) -> None:
    from ..core import api_messages as msg

    if not can(
        db,
        auth,
        resource,
        action,
        project_id=project_id,
        org_id=org_id,
        resource_id=resource_id,
        owner_username=owner_username,
        allow_resource_acl=allow_resource_acl,
    ):
        raise PermissionError(error or msg.PROJECT_NO_ACCESS)


__all__ = [
    "ACTION_CREATE",
    "ACTION_LIST",
    "ACTION_MANAGE",
    "ACTION_MANAGE_MEMBERS",
    "ACTION_MANAGE_USERS",
    "ACTION_META_READ",
    "ACTION_READ",
    "ACTION_WRITE",
    "EXECUTION_RESOURCES",
    "ORG_ROLES",
    "ORG_ROLE_RANK",
    "PLATFORM_ROLES",
    "PROJECT_CONTENT_RESOURCES",
    "PROJECT_ROLES",
    "PROJECT_ROLE_RANK",
    "RESOURCE_ACL",
    "RESOURCE_APP_BUILD",
    "RESOURCE_ARTIFACT",
    "RESOURCE_DESIGN",
    "RESOURCE_DEVICE",
    "RESOURCE_JOB",
    "RESOURCE_ORG",
    "RESOURCE_PROJECT",
    "RESOURCE_POOL",
    "RESOURCE_SCHEDULE",
    "ROLE_POLICIES",
    "assert_can",
    "can",
    "can_assign_org_role",
    "can_assign_project_role",
    "org_admin_elevates_project",
    "org_role_key",
    "policy_allows",
    "project_role_key",
    "user_in_project_org",
]
