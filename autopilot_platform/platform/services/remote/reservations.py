"""设备来源/所有权策略与用户限时占用。"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from autopilot_platform.core.schemas import (
    DeviceReservationCreate,
    DeviceReservationOut,
)

from ...auth import AuthContext
from ...core.models import (
    DeviceReservationRow,
    DeviceRow,
    RunnerRow,
    UserRow,
    utcnow,
    db_get,
    new_id,
)
from ...core.list_page import slice_page
from ...tenancy.projects import is_platform_admin
from ...tenancy.organizations import org_member_role


def runner_source(runner: RunnerRow | None) -> str:
    if runner is None:
        return "platform"
    return (runner.registration_source or "platform").strip().lower() or "platform"


def runner_is_private(runner: RunnerRow | None) -> bool:
    """只有来源为 IDE 且 owner 非空才是私有；存量无 owner 保持共享。"""
    return bool(
        runner is not None
        and runner_source(runner) == "ide"
        and (runner.owner_user_id or "").strip()
    )


def _user_is_runner_admin(db: Session, user: UserRow | None, runner: RunnerRow) -> bool:
    if user is None:
        return False
    if (user.role or "") == "admin":
        return True
    oid = (runner.org_id or "").strip()
    return bool(
        oid and org_member_role(db, user.id, oid) in {"owner", "admin"}
    )


def can_user_use_runner(db: Session, auth: AuthContext, runner: RunnerRow) -> bool:
    if is_platform_admin(auth):
        return True
    if auth.kind != "user":
        return False
    if not runner_is_private(runner):
        return True
    if (runner.owner_user_id or "").strip() == auth.user_id:
        return True
    user = db_get(db, UserRow, auth.user_id)
    return _user_is_runner_admin(db, user, runner)


def can_user_manage_runner(
    db: Session, auth: AuthContext, runner: RunnerRow
) -> bool:
    """平台管理员，或节点所属组织的 owner/admin，可管理设备选择策略。"""
    if is_platform_admin(auth):
        return True
    if getattr(auth, "kind", "") != "user":
        return False
    org_id = (getattr(runner, "org_id", None) or "").strip()
    if not org_id:
        return False

    return org_member_role(db, auth.user_id, org_id) in {"owner", "admin"}


def can_user_use_device(db: Session, auth: AuthContext, device: DeviceRow) -> bool:
    runner = db_get(db, RunnerRow, device.runner_id)
    return bool(runner and can_user_use_runner(db, auth, runner))


def can_user_manage_device(db: Session, auth: AuthContext, device: DeviceRow) -> bool:
    runner = db_get(db, RunnerRow, device.runner_id)
    return bool(runner and can_user_manage_runner(db, auth, runner))


def username_can_use_device(db: Session, username: str, device: DeviceRow) -> bool:
    """claim 使用 Job 创建人复核私有设备资格。"""
    runner = db_get(db, RunnerRow, device.runner_id)
    if runner is None:
        return False
    return username_can_use_runner(db, username, runner)


def username_can_use_runner(db: Session, username: str, runner: RunnerRow) -> bool:
    """claim 使用 Job 创建人复核私有 Runner 资格。"""
    if not runner_is_private(runner):
        return True
    uname = (username or "").strip()
    if not uname:
        return False
    user = db.scalar(select(UserRow).where(UserRow.username == uname))
    if user is None:
        return False
    return bool(
        (runner.owner_user_id or "").strip() == user.id
        or _user_is_runner_admin(db, user, runner)
    )


def expire_reservations(
    db: Session, *, device_id: str = "", commit: bool = True
) -> list[str]:
    now = utcnow()
    q = select(DeviceReservationRow).where(
        DeviceReservationRow.status == "active",
        DeviceReservationRow.expires_at <= now,
    )
    did = (device_id or "").strip()
    if did:
        q = q.where(DeviceReservationRow.device_id == did)
    rows = list(db.scalars(q).all())
    expired_ids: list[str] = []
    for row in rows:
        result = db.execute(
            update(DeviceReservationRow)
            .where(
                DeviceReservationRow.id == row.id,
                DeviceReservationRow.status == "active",
                DeviceReservationRow.expires_at <= now,
            )
            .values(status="expired", released_at=now)
            .execution_options(synchronize_session=False)
        )
        if int(getattr(result, "rowcount", 0) or 0) != 1:
            continue
        expired_ids.append(row.id)
        db.execute(
            update(DeviceRow)
            .where(
                DeviceRow.id == row.device_id,
                DeviceRow.reservation_id == row.id,
            )
            .values(reservation_id=None, updated_at=now)
        )
    if expired_ids and commit:
        db.commit()
    return expired_ids


def active_reservation(
    db: Session, device_id: str, *, expire: bool = True
) -> DeviceReservationRow | None:
    if expire:
        expire_reservations(db, device_id=device_id)
    return db.scalar(
        select(DeviceReservationRow)
        .where(
            DeviceReservationRow.device_id == device_id,
            DeviceReservationRow.status == "active",
        )
        .order_by(DeviceReservationRow.start_at.desc())
    )


def reservation_allows_username(
    db: Session, device: DeviceRow, username: str
) -> bool:
    row = active_reservation(db, device.id)
    return row is None or row.username == (username or "").strip()


def reservation_to_out(
    db: Session,
    row: DeviceReservationRow,
    auth: AuthContext | None = None,
) -> DeviceReservationOut:
    can_release = False
    if auth is not None:
        device = db_get(db, DeviceRow, row.device_id)
        can_release = bool(
            auth.kind == "user"
            and (
                row.user_id == auth.user_id
                or (device is not None and can_user_manage_device(db, auth, device))
            )
        )
    return DeviceReservationOut(
        id=row.id,
        device_id=row.device_id,
        user_id=row.user_id,
        username=row.username or "",
        reason=row.reason or "",
        status=row.status,
        start_at=row.start_at,
        expires_at=row.expires_at,
        released_at=row.released_at,
        can_release=can_release,
    )


def create_reservation(
    db: Session,
    device_id: str,
    body: DeviceReservationCreate,
    auth: AuthContext,
) -> DeviceReservationOut:
    if auth.kind != "user":
        raise PermissionError("必须使用登录用户占用设备")
    device = db_get(db, DeviceRow, (device_id or "").strip())
    if device is None:
        raise LookupError("设备不存在")
    if not can_user_use_device(db, auth, device):
        raise PermissionError("无权使用该设备")
    # 直连 API 也必须满足现有 org/project/resource-pool 可见性，不能只凭 device_id 绕过列表。
    from ..execution.devices.board import list_tr_devices  # 延迟：board → scheduling → reservations

    visible_ids = {
        str(item.get("id") or "")
        for item in list_tr_devices(db, auth=auth)[0]
    }
    if device.id not in visible_ids:
        raise PermissionError("设备不在当前用户可用资源范围内")
    active_reservation(db, device.id)
    now = utcnow()
    reservation_id = new_id()
    locked = db.execute(
        update(DeviceRow)
        .where(
            DeviceRow.id == device.id,
            (DeviceRow.busy_job_id.is_(None)) | (DeviceRow.busy_job_id == ""),
            DeviceRow.reservation_id.is_(None),
        )
        .values(reservation_id=reservation_id, updated_at=now)
    )
    if int(getattr(locked, "rowcount", 0) or 0) != 1:
        db.rollback()
        current = db_get(db, DeviceRow, device.id)
        if current is not None and (current.busy_job_id or "").strip():
            raise ValueError("设备正在执行任务，不能创建独立占用")
        raise ValueError("设备已被占用")
    row = DeviceReservationRow(
        id=reservation_id,
        device_id=device.id,
        user_id=auth.user_id,
        username=auth.username or "",
        reason=body.reason or "",
        status="active",
        start_at=now,
        expires_at=now + timedelta(minutes=int(body.duration_minutes)),
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ValueError("设备已被占用") from exc
    db.refresh(row)
    return reservation_to_out(db, row, auth)


def release_reservation(
    db: Session,
    reservation_id: str,
    auth: AuthContext,
) -> DeviceReservationOut:
    row = db_get(db, DeviceReservationRow, (reservation_id or "").strip())
    if row is None:
        raise LookupError("设备占用记录不存在")
    expire_reservations(db, device_id=row.device_id)
    db.refresh(row)
    device = db_get(db, DeviceRow, row.device_id)
    allowed = auth.kind == "user" and (
        row.user_id == auth.user_id
        or (device is not None and can_user_manage_device(db, auth, device))
    )
    if not allowed:
        raise PermissionError("仅占用人或管理员可停止占用")
    if row.status == "active":
        now = utcnow()
        db.execute(
            update(DeviceReservationRow)
            .where(
                DeviceReservationRow.id == row.id,
                DeviceReservationRow.status == "active",
            )
            .values(status="released", released_at=now)
        )
        db.execute(
            update(DeviceRow)
            .where(
                DeviceRow.id == row.device_id,
                DeviceRow.reservation_id == row.id,
            )
            .values(reservation_id=None, updated_at=now)
        )
        from .sessions import close_sessions_for_reservation

        close_sessions_for_reservation(db, row.id)
        db.commit()
        db.refresh(row)
    return reservation_to_out(db, row, auth)


def active_reservations_for_auth(
    db: Session,
    auth: AuthContext,
    *,
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[DeviceReservationOut], int]:

    expire_reservations(db)
    from ..execution.devices.board import list_tr_devices  # 延迟：board → scheduling → reservations

    visible_ids = {
        str(item.get("id") or "")
        for item in list_tr_devices(db, auth=auth)[0]
    }
    rows = list(
        db.scalars(
            select(DeviceReservationRow)
            .where(DeviceReservationRow.status == "active")
            .order_by(DeviceReservationRow.expires_at)
        ).all()
    )
    visible_rows = [
        row
        for row in rows
        if (device := db_get(db, DeviceRow, row.device_id)) is not None
        and row.device_id in visible_ids
        and can_user_use_device(db, auth, device)
    ]
    size = max(1, min(200, int(page_size)))
    pg = max(1, int(page))
    page_rows, total = slice_page(visible_rows, page=pg, page_size=size)
    return [reservation_to_out(db, row, auth) for row in page_rows], total
