"""组织资源池：管理、可见性与调度软隔离规则。"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from autopilot_platform.core.constants import JobStatus
from autopilot_platform.core.schemas import (
    ResourcePoolCreate,
    ResourcePoolOut,
    ResourcePoolUpdate,
)

from ....auth import AuthContext
from ....core.list_page import slice_page
from ....core.models import (
    DeviceRow,
    JobRow,
    OrganizationRow,
    ProjectRow,
    ResourcePoolDeviceRow,
    ResourcePoolProjectRow,
    ResourcePoolRow,
    ResourcePoolRunnerRow,
    RunnerRow,
    utcnow,
    db_get,
    new_id,
)
from ....authz.rbac import ACTION_MANAGE, RESOURCE_POOL, can
from ....tenancy.organizations import org_member_role
from ....tenancy.projects import is_platform_admin, visible_project_filter


def _pool_or_404(db: Session, pool_id: str) -> ResourcePoolRow:
    row = db_get(db, ResourcePoolRow, (pool_id or "").strip())
    if row is None:
        raise LookupError("资源池不存在")
    return row


def _assert_manage(db: Session, auth: AuthContext, org_id: str) -> None:
    if not can(db, auth, RESOURCE_POOL, ACTION_MANAGE, org_id=org_id):
        raise PermissionError("仅组织所有者或管理员可管理资源池")


def _project_ids_for_pool(db: Session, pool_id: str) -> list[str]:
    return list(
        db.scalars(
            select(ResourcePoolProjectRow.project_id)
            .where(ResourcePoolProjectRow.pool_id == pool_id)
            .order_by(ResourcePoolProjectRow.project_id)
        ).all()
    )


def pool_to_out(
    db: Session, row: ResourcePoolRow, *, can_manage: bool = False
) -> ResourcePoolOut:
    runner_ids = list(
        db.scalars(
            select(ResourcePoolRunnerRow.runner_id)
            .where(ResourcePoolRunnerRow.pool_id == row.id)
            .order_by(ResourcePoolRunnerRow.runner_id)
        ).all()
    )
    device_ids = list(
        db.scalars(
            select(ResourcePoolDeviceRow.device_id)
            .where(ResourcePoolDeviceRow.pool_id == row.id)
            .order_by(ResourcePoolDeviceRow.device_id)
        ).all()
    )
    return ResourcePoolOut(
        id=row.id,
        org_id=row.org_id,
        name=row.name,
        description=row.description or "",
        is_default=bool(row.is_default),
        enabled=bool(row.enabled),
        runner_ids=runner_ids,
        device_ids=device_ids,
        project_ids=_project_ids_for_pool(db, row.id),
        can_manage=can_manage,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def list_resource_pools(
    db: Session,
    org_id: str,
    auth: AuthContext,
    *,
    project_id: str = "",
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[ResourcePoolOut], int]:

    oid = (org_id or "").strip()
    if not oid:
        raise ValueError("org_id required")
    pid = (project_id or "").strip()
    manageable = can(db, auth, RESOURCE_POOL, ACTION_MANAGE, org_id=oid)
    org_member = is_platform_admin(auth) or bool(org_member_role(db, auth.user_id, oid))
    visible = (
        set(visible_project_filter(db, auth) or set())
        if auth.kind == "user"
        else set()
    )
    if pid:
        from ....tenancy.projects import assert_can_access_project

        assert_can_access_project(db, auth, pid)
        visible = {pid}
    # 组织成员或本组织项目成员可进入列表；纯外人 403。
    if not manageable and not org_member:
        org_projects = set(
            db.scalars(select(ProjectRow.id).where(ProjectRow.org_id == oid)).all()
        )
        if not (visible & org_projects):
            raise PermissionError("无权查看该组织资源池")
    q = select(ResourcePoolRow).where(ResourcePoolRow.org_id == oid)
    if not manageable:
        if not visible:
            return [], 0
        granted = select(ResourcePoolProjectRow.pool_id).where(
            ResourcePoolProjectRow.project_id.in_(visible)
        )
        q = q.where(ResourcePoolRow.id.in_(granted), ResourcePoolRow.enabled.is_(True))
    rows = list(db.scalars(q.order_by(ResourcePoolRow.name, ResourcePoolRow.id)).all())
    filtered = [pool_to_out(db, row, can_manage=manageable) for row in rows]
    size = max(1, min(200, int(page_size)))
    pg = max(1, int(page))
    return slice_page(filtered, page=pg, page_size=size)


def create_resource_pool(
    db: Session, org_id: str, body: ResourcePoolCreate, auth: AuthContext
) -> ResourcePoolOut:
    oid = (org_id or "").strip()

    if db_get(db, OrganizationRow, oid) is None:
        raise LookupError("组织不存在")
    _assert_manage(db, auth, oid)
    name = body.name.strip()
    existing = db.scalar(
        select(ResourcePoolRow.id).where(
            ResourcePoolRow.org_id == oid, ResourcePoolRow.name == name
        )
    )
    if existing:
        raise ValueError("组织内资源池名称已存在")
    if body.is_default:
        for current in db.scalars(
            select(ResourcePoolRow).where(
                ResourcePoolRow.org_id == oid, ResourcePoolRow.is_default.is_(True)
            )
        ).all():
            current.is_default = False
            current.updated_at = utcnow()
    row = ResourcePoolRow(
        id=new_id(),
        org_id=oid,
        name=name,
        description=body.description or "",
        is_default=bool(body.is_default),
        enabled=bool(body.enabled),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return pool_to_out(db, row, can_manage=True)


def update_resource_pool(
    db: Session, pool_id: str, body: ResourcePoolUpdate, auth: AuthContext
) -> ResourcePoolOut:
    row = _pool_or_404(db, pool_id)
    _assert_manage(db, auth, row.org_id)
    if body.name is not None:
        name = body.name.strip()
        duplicate = db.scalar(
            select(ResourcePoolRow.id).where(
                ResourcePoolRow.org_id == row.org_id,
                ResourcePoolRow.name == name,
                ResourcePoolRow.id != row.id,
            )
        )
        if duplicate:
            raise ValueError("组织内资源池名称已存在")
        row.name = name
    if body.description is not None:
        row.description = body.description
    if body.enabled is not None:
        row.enabled = bool(body.enabled)
    if body.is_default is not None:
        if body.is_default:
            for current in db.scalars(
                select(ResourcePoolRow).where(
                    ResourcePoolRow.org_id == row.org_id,
                    ResourcePoolRow.is_default.is_(True),
                    ResourcePoolRow.id != row.id,
                )
            ).all():
                current.is_default = False
                current.updated_at = utcnow()
        row.is_default = bool(body.is_default)
    row.updated_at = utcnow()
    db.commit()
    db.refresh(row)
    return pool_to_out(db, row, can_manage=True)


def delete_resource_pool(db: Session, pool_id: str, auth: AuthContext) -> None:
    row = _pool_or_404(db, pool_id)
    _assert_manage(db, auth, row.org_id)
    runner_ids = set(
        db.scalars(
            select(ResourcePoolRunnerRow.runner_id).where(
                ResourcePoolRunnerRow.pool_id == row.id
            )
        ).all()
    )
    device_ids = set(
        db.scalars(
            select(ResourcePoolDeviceRow.device_id).where(
                ResourcePoolDeviceRow.pool_id == row.id
            )
        ).all()
    )
    if device_ids:
        busy = db.scalar(
            select(func.count())
            .select_from(DeviceRow)
            .where(DeviceRow.id.in_(device_ids), DeviceRow.busy_job_id.is_not(None))
        )
        if int(busy or 0) > 0:
            raise ValueError("资源池中存在被活动任务占用的设备")
        runner_ids.update(
            db.scalars(select(DeviceRow.runner_id).where(DeviceRow.id.in_(device_ids))).all()
        )
    if runner_ids:
        active = db.scalar(
            select(func.count())
            .select_from(JobRow)
            .where(
                JobRow.runner_id.in_(runner_ids),
                JobRow.status.in_(
                    [JobStatus.CLAIMED.value, JobStatus.RUNNING.value]
                ),
            )
        )
        if int(active or 0) > 0:
            raise ValueError("资源池中的 Runner 正在执行活动任务")
    db.delete(row)
    db.commit()


def add_runner(
    db: Session, pool_id: str, runner_id: str, auth: AuthContext
) -> ResourcePoolOut:
    pool = _pool_or_404(db, pool_id)
    _assert_manage(db, auth, pool.org_id)
    runner = db_get(db, RunnerRow, runner_id)
    if runner is None:
        raise LookupError("Runner 不存在")
    if (runner.org_id or "").strip() != pool.org_id:
        raise ValueError("Runner 必须先绑定到该组织")
    existing = db.scalar(
        select(ResourcePoolRunnerRow.id).where(
            ResourcePoolRunnerRow.pool_id == pool.id,
            ResourcePoolRunnerRow.runner_id == runner.runner_id,
        )
    )
    if not existing:
        db.add(
            ResourcePoolRunnerRow(
                id=new_id(), pool_id=pool.id, runner_id=runner.runner_id
            )
        )
        db.commit()
    return pool_to_out(db, pool, can_manage=True)


def remove_runner(
    db: Session, pool_id: str, runner_id: str, auth: AuthContext
) -> ResourcePoolOut:
    pool = _pool_or_404(db, pool_id)
    _assert_manage(db, auth, pool.org_id)
    row = db.scalar(
        select(ResourcePoolRunnerRow).where(
            ResourcePoolRunnerRow.pool_id == pool.id,
            ResourcePoolRunnerRow.runner_id == runner_id,
        )
    )
    if row is not None:
        db.delete(row)
        db.commit()
    return pool_to_out(db, pool, can_manage=True)


def add_device(
    db: Session, pool_id: str, device_id: str, auth: AuthContext
) -> ResourcePoolOut:
    pool = _pool_or_404(db, pool_id)
    _assert_manage(db, auth, pool.org_id)
    device = db_get(db, DeviceRow, device_id)
    if device is None:
        raise LookupError("设备不存在")
    runner = db_get(db, RunnerRow, device.runner_id)
    if runner is None or (runner.org_id or "").strip() != pool.org_id:
        raise ValueError("设备所属 Runner 必须先绑定到该组织")
    existing = db.scalar(
        select(ResourcePoolDeviceRow.id).where(
            ResourcePoolDeviceRow.pool_id == pool.id,
            ResourcePoolDeviceRow.device_id == device.id,
        )
    )
    if not existing:
        db.add(
            ResourcePoolDeviceRow(
                id=new_id(), pool_id=pool.id, device_id=device.id
            )
        )
        db.commit()
    return pool_to_out(db, pool, can_manage=True)


def remove_device(
    db: Session, pool_id: str, device_id: str, auth: AuthContext
) -> ResourcePoolOut:
    pool = _pool_or_404(db, pool_id)
    _assert_manage(db, auth, pool.org_id)
    row = db.scalar(
        select(ResourcePoolDeviceRow).where(
            ResourcePoolDeviceRow.pool_id == pool.id,
            ResourcePoolDeviceRow.device_id == device_id,
        )
    )
    if row is not None:
        db.delete(row)
        db.commit()
    return pool_to_out(db, pool, can_manage=True)


def grant_project(
    db: Session, pool_id: str, project_id: str, auth: AuthContext
) -> ResourcePoolOut:
    pool = _pool_or_404(db, pool_id)
    _assert_manage(db, auth, pool.org_id)
    project = db_get(db, ProjectRow, project_id)
    if project is None:
        raise LookupError("项目不存在")
    if (project.org_id or "").strip() != pool.org_id:
        raise ValueError("项目与资源池必须属于同一组织")
    existing = db.scalar(
        select(ResourcePoolProjectRow.id).where(
            ResourcePoolProjectRow.pool_id == pool.id,
            ResourcePoolProjectRow.project_id == project.id,
        )
    )
    if not existing:
        db.add(
            ResourcePoolProjectRow(
                id=new_id(), pool_id=pool.id, project_id=project.id
            )
        )
        db.commit()
    return pool_to_out(db, pool, can_manage=True)


def revoke_project(
    db: Session, pool_id: str, project_id: str, auth: AuthContext
) -> ResourcePoolOut:
    pool = _pool_or_404(db, pool_id)
    _assert_manage(db, auth, pool.org_id)
    row = db.scalar(
        select(ResourcePoolProjectRow).where(
            ResourcePoolProjectRow.pool_id == pool.id,
            ResourcePoolProjectRow.project_id == project_id,
        )
    )
    if row is not None:
        db.delete(row)
        db.commit()
    return pool_to_out(db, pool, can_manage=True)


def pool_mode_for_project(db: Session, project_id: str) -> tuple[bool, set[str]]:
    """返回 (是否池模式, 已授权且启用的 pool ids)。"""
    pid = (project_id or "").strip()
    if not pid:
        return False, set()
    project = db_get(db, ProjectRow, pid)
    if project is None or not (project.org_id or "").strip():
        return False, set()
    oid = project.org_id.strip()
    enabled_count = int(
        db.scalar(
            select(func.count())
            .select_from(ResourcePoolRow)
            .where(ResourcePoolRow.org_id == oid, ResourcePoolRow.enabled.is_(True))
        )
        or 0
    )
    grant_count = int(
        db.scalar(
            select(func.count())
            .select_from(ResourcePoolProjectRow)
            .where(ResourcePoolProjectRow.project_id == pid)
        )
        or 0
    )
    if enabled_count <= 0 and grant_count <= 0:
        return False, set()
    allowed = set(
        db.scalars(
            select(ResourcePoolRow.id)
            .join(
                ResourcePoolProjectRow,
                ResourcePoolProjectRow.pool_id == ResourcePoolRow.id,
            )
            .where(
                ResourcePoolProjectRow.project_id == pid,
                ResourcePoolRow.org_id == oid,
                ResourcePoolRow.enabled.is_(True),
            )
        ).all()
    )
    return True, allowed


def device_allowed_for_project(
    db: Session, device: DeviceRow, project_id: str
) -> bool:
    active, pools = pool_mode_for_project(db, project_id)
    if not active:
        return True
    if not pools:
        return False
    if db.scalar(
        select(ResourcePoolRunnerRow.id).where(
            ResourcePoolRunnerRow.pool_id.in_(pools),
            ResourcePoolRunnerRow.runner_id == device.runner_id,
        )
    ):
        return True
    return bool(
        db.scalar(
            select(ResourcePoolDeviceRow.id).where(
                ResourcePoolDeviceRow.pool_id.in_(pools),
                ResourcePoolDeviceRow.device_id == device.id,
            )
        )
    )


def runner_allowed_for_job(
    db: Session,
    runner_id: str,
    project_id: str,
    *,
    device_udids: list[str],
    is_deviceless: bool,
    job_username: str = "",
) -> bool:
    from ...remote.policy import username_can_use_runner

    runner = db_get(db, RunnerRow, runner_id)
    if runner is None or not username_can_use_runner(db, job_username, runner):
        return False
    active, pools = pool_mode_for_project(db, project_id)
    if not active:
        return True
    if not pools:
        return False
    runner_member = bool(
        db.scalar(
            select(ResourcePoolRunnerRow.id).where(
                ResourcePoolRunnerRow.pool_id.in_(pools),
                ResourcePoolRunnerRow.runner_id == runner_id,
            )
        )
    )
    if is_deviceless:
        return runner_member
    if not device_udids:
        if runner_member:
            return True
        return bool(
            db.scalar(
                select(ResourcePoolDeviceRow.id)
                .join(DeviceRow, DeviceRow.id == ResourcePoolDeviceRow.device_id)
                .where(
                    ResourcePoolDeviceRow.pool_id.in_(pools),
                    DeviceRow.runner_id == runner_id,
                )
            )
        )
    rows = list(
        db.scalars(
            select(DeviceRow).where(
                DeviceRow.runner_id == runner_id, DeviceRow.udid.in_(set(device_udids))
            )
        ).all()
    )
    by_udid = {row.udid: row for row in rows}
    return all(
        uid in by_udid and device_allowed_for_project(db, by_udid[uid], project_id)
        for uid in set(device_udids)
    )


def can_manage_org_resources(db: Session, auth: AuthContext, org_id: str) -> bool:
    return is_platform_admin(auth) or org_member_role(db, auth.user_id, org_id) in {
        "owner",
        "admin",
    }


def visible_pool_resource_ids(
    db: Session, auth: AuthContext, *, project_id: str = ""
) -> tuple[set[str], set[str], bool]:
    """普通用户池可见 runner/device；返回 (runner_ids, device_ids, 是否存在池模式)。"""
    if auth.kind != "user":
        return set(), set(), False
    pid = (project_id or "").strip()
    visible_projects = set(visible_project_filter(db, auth) or set())
    if pid:
        from ....tenancy.projects import assert_can_access_project

        assert_can_access_project(db, auth, pid)
        visible_projects = {pid}
    if not visible_projects:
        return set(), set(), False
    pool_ids: set[str] = set()
    active = False
    for pid in visible_projects:
        project_active, allowed = pool_mode_for_project(db, pid)
        active = active or project_active
        pool_ids.update(allowed)
    if not active:
        return set(), set(), False
    if not pool_ids:
        return set(), set(), True
    runner_members = set(
        db.scalars(
            select(ResourcePoolRunnerRow.runner_id).where(
                ResourcePoolRunnerRow.pool_id.in_(pool_ids)
            )
        ).all()
    )
    device_members = set(
        db.scalars(
            select(ResourcePoolDeviceRow.device_id).where(
                ResourcePoolDeviceRow.pool_id.in_(pool_ids)
            )
        ).all()
    )
    runners = set(runner_members)
    devices = set(device_members)
    if device_members:
        runners.update(
            db.scalars(
                select(DeviceRow.runner_id).where(DeviceRow.id.in_(device_members))
            ).all()
        )
    # Runner 成员代表整机资源；单 Device 成员只暴露该设备，不能借其所属
    # Runner 反向扩散并泄露同机其它设备。
    if runner_members:
        devices.update(
            db.scalars(
                select(DeviceRow.id).where(DeviceRow.runner_id.in_(runner_members))
            ).all()
        )
    return runners, devices, True

