"""Runner 注册、心跳与令牌。"""

from __future__ import annotations

import json
import secrets
from typing import cast

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from autopilot_platform.core.schemas import (
    DeviceInfo,
    HeartbeatIn,
    RunnerDeviceInventoryItem,
    RunnerDeviceInventoryOut,
    RunnerDeviceSelectionOut,
    RunnerOut,
    RunnerRegister,
)

from ....core import api_messages as msg
from ....core.models import (
    DeviceReservationRow,
    DeviceRow,
    JobRow,
    RunnerRow,
    utcnow,
    db_get,
    new_id,
)
from ....auth import hash_api_token
from ....core.list_page import slice_page
from ...remote.reservations import expire_reservations
from ...shared import is_online, runner_to_out
from ..devices.scheduling import reconcile_multi_runner_udids


def register_runner(
    db: Session,
    body: RunnerRegister,
    *,
    owner_user_id: str | None = None,
    registration_source: str | None = None,
) -> RunnerOut:
    """幂等注册/刷新：同 runner_id 重复调用安全。"""
    row = db_get(db, RunnerRow, body.runner_id)
    created = row is None
    if row is None:
        row = RunnerRow(runner_id=body.runner_id)
        db.add(row)
    source = (registration_source or body.registration_source or "platform").strip().lower()
    if source not in {"ide", "platform", "managed"}:
        raise ValueError("registration_source must be ide, platform or managed")
    # 已有登记不被普通心跳/重复注册改写来源；显式 owner 仅用于用户 IDE 预注册。
    if created or not (row.registration_source or "").strip():
        row.registration_source = source
    if owner_user_id is not None:
        row.owner_user_id = (owner_user_id or "").strip()
    row.hostname = body.hostname or row.hostname or ""
    row.version = body.version or row.version or ""
    caps = list(body.capabilities or [])
    for b in body.host_backends or []:
        tag = (b or "").strip()
        if tag and tag not in caps:
            caps.append(tag)
    if caps:
        row.capabilities = caps
    row.last_heartbeat_at = utcnow()
    db.commit()
    db.refresh(row)
    return runner_to_out(row)


def heartbeat(db: Session, body: HeartbeatIn) -> RunnerOut:
    """upsert 设备列表：保留 busy_job_id；调和多 Runner 同 UDID；未注册时自动补注册。"""

    expire_reservations(db)
    row = db_get(db, RunnerRow, body.runner_id)
    auto_registered = False
    if row is None:
        # 兜底：网络抖动丢 register / Agent 重启竞态时，心跳可自愈注册
        row = RunnerRow(runner_id=body.runner_id)
        db.add(row)
        auto_registered = True
    now = utcnow()
    row.last_heartbeat_at = now

    caps = list(body.capabilities or [])
    for b in body.host_backends or []:
        tag = (b or "").strip()
        if tag and tag not in caps:
            caps.append(tag)
    if caps:
        row.capabilities = caps
    if auto_registered and not (row.hostname or "").strip():
        row.hostname = ""
        row.version = ""

    row.device_inventory = [
        item.model_dump(mode="json") for item in body.inventory
    ]

    selected = set(row.selected_device_udids)
    reported_devices = list(body.devices or [])
    if (row.device_selection_mode or "all") == "include":
        # 服务端再次执行 allowlist，避免客户端异常上报把未选设备写回 TR 池。
        reported_devices = [d for d in reported_devices if (d.udid or "").strip() in selected]
        # Runner 本地策略未同步时可能上报空 devices；用 inventory ∩ allowlist 保活 TR 池。
        if selected:
            reported_udids = {
                str(getattr(d, "udid", "") or "").strip() for d in reported_devices
            }
            inv_by_udid = {
                str(raw.get("udid") or "").strip(): raw for raw in row.device_inventory
            }
            for uid in sorted(selected):
                if uid in reported_udids or uid not in inv_by_udid:
                    continue
                reported_devices.append(_device_info_from_inventory(inv_by_udid[uid]))

    seen = _upsert_device_rows(
        db,
        row,
        reported_devices,
        now=now,
        prune_unseen=True,
        protect_udids=selected if (row.device_selection_mode or "all") == "include" else None,
    )
    # 先 flush，使本心跳新建的 DeviceRow 参与多 Runner 冲突查询
    db.flush()
    reconcile_multi_runner_udids(db, runner_id=row.runner_id, seen_udids=seen, now=now)

    db.commit()
    db.refresh(row)
    return runner_to_out(row, now=now)


def _device_info_from_inventory(raw: dict) -> DeviceInfo:
    return DeviceInfo(
        udid=str(raw.get("udid") or ""),
        platform=str(raw.get("platform") or ""),
        name=str(raw.get("name") or ""),
        model=str(raw.get("model") or ""),
        os_version=str(raw.get("os_version") or ""),
        labels=list(raw.get("labels") or []),
        state=str(raw.get("state") or "ready") or "ready",
        backends=list(raw.get("backends") or []),
        health_note=str(raw.get("health_note") or ""),
    )


def _upsert_device_rows(
    db: Session,
    row: RunnerRow,
    reported_devices: list,
    *,
    now,
    prune_unseen: bool,
    protect_udids: set[str] | None = None,
) -> set[str]:
    """按上报清单写入/刷新 DeviceRow。register 只补行，heartbeat 才 prune。"""
    protected = set(protect_udids or set())
    existing: dict[str, DeviceRow] = {
        row_dev.udid: row_dev
        for row_dev in cast(list[DeviceRow], list(row.devices or []))
    }
    seen: set[str] = set()
    for reported in reported_devices:
        uid = str(getattr(reported, "udid", "") or "").strip()
        if not uid:
            continue
        seen.add(uid)
        labels_json = json.dumps(list(getattr(reported, "labels", None) or []), ensure_ascii=False)
        backends_json = json.dumps(
            list(getattr(reported, "backends", None) or []), ensure_ascii=False
        )
        state = (getattr(reported, "state", None) or "ready").strip() or "ready"
        os_version = (getattr(reported, "os_version", None) or "").strip()
        health_note = (getattr(reported, "health_note", None) or "").strip()
        device_row: DeviceRow | None = existing.get(uid)
        if device_row is None:
            created = DeviceRow(
                id=new_id(),
                runner_id=row.runner_id,
                udid=uid,
                platform=getattr(reported, "platform", "") or "",
                name=getattr(reported, "name", "") or "",
                model=getattr(reported, "model", "") or "",
                os_version=os_version,
                state=state,
                backends_json=backends_json,
                health_note=health_note,
                labels_json=labels_json,
                busy_job_id=None,
                updated_at=now,
            )
            try:
                with db.begin_nested():
                    db.add(created)
                    db.flush()
            except IntegrityError:
                device_row = db.scalar(
                    select(DeviceRow).where(
                        DeviceRow.runner_id == row.runner_id, DeviceRow.udid == uid
                    )
                )
                if device_row is None:
                    raise
            else:
                existing[uid] = created
                continue
        device_row.platform = getattr(reported, "platform", "") or ""
        device_row.name = getattr(reported, "name", "") or ""
        device_row.model = getattr(reported, "model", "") or ""
        device_row.os_version = os_version
        device_row.state = state
        device_row.backends_json = backends_json
        device_row.health_note = health_note
        device_row.labels_json = labels_json
        device_row.updated_at = now
        # busy_job_id 由 claim/cancel/complete 维护，心跳不得清空
    if prune_unseen:
        for uid, stale in existing.items():
            if uid in seen:
                continue
            if uid in protected:
                stale.updated_at = now
                continue
            if stale.busy_job_id or stale.reservation_id:
                stale.updated_at = now
                continue
            db.delete(stale)
    return seen


def _ensure_allowlisted_device_rows(
    db: Session, row: RunnerRow, *, refresh: bool = False
) -> bool:
    """include 名单里的设备立刻进 TR 池，不空等下一次心跳。

    GET 库存只补缺失行；register/set 才按快照刷新已有行，避免每次读取都写库。
    """
    if (row.device_selection_mode or "all").strip() != "include":
        return False
    selected = set(row.selected_device_udids)
    if not selected:
        return False
    reported = [
        _device_info_from_inventory(raw)
        for raw in row.device_inventory
        if str(raw.get("udid") or "").strip() in selected
    ]
    if not reported:
        return False
    existing_ids = {
        str(d.udid)
        for d in cast(list[DeviceRow], list(row.devices or []))
        if str(d.udid or "").strip()
    }
    to_write = (
        reported
        if refresh
        else [item for item in reported if (item.udid or "").strip() not in existing_ids]
    )
    if not to_write:
        return False
    now = utcnow()
    seen = _upsert_device_rows(db, row, to_write, now=now, prune_unseen=False)
    db.flush()
    reconcile_multi_runner_udids(db, runner_id=row.runner_id, seen_udids=seen, now=now)
    return bool(seen - existing_ids)


def _inventory_registered(row: RunnerRow, uid: str, current: DeviceRow | None) -> bool:
    """已注册 = include 名单内；all 模式仍看是否已进 TR 池。"""
    if (row.device_selection_mode or "all").strip() == "include":
        return uid in set(row.selected_device_udids)
    return current is not None


def get_device_inventory(db: Session, runner_id: str) -> RunnerDeviceInventoryOut:

    expire_reservations(db)
    row = db_get(db, RunnerRow, runner_id)
    if row is None:
        raise LookupError(msg.RUNNER_NOT_FOUND.format(runner_id=runner_id))
    if _ensure_allowlisted_device_rows(db, row, refresh=False):
        db.commit()
        db.refresh(row)
    active: dict[str, DeviceRow] = {}
    for device in cast(list[DeviceRow], list(row.devices or [])):
        active[str(device.udid)] = device
    job_ids = {
        str(d.busy_job_id or "").strip()
        for d in active.values()
        if str(d.busy_job_id or "").strip()
    }
    jobs: dict[str, JobRow] = {}
    if job_ids:
        for job in db.scalars(select(JobRow).where(JobRow.id.in_(job_ids))).all():
            jobs[str(job.id)] = job
    reservation_ids = {
        str(d.reservation_id or "").strip()
        for d in active.values()
        if str(d.reservation_id or "").strip()
    }
    reservations: dict[str, DeviceReservationRow] = {}
    if reservation_ids:
        reservation_rows = db.scalars(
            select(DeviceReservationRow).where(
                DeviceReservationRow.id.in_(reservation_ids),
                DeviceReservationRow.status == "active",
            )
        ).all()
        for reservation in reservation_rows:
            reservations[str(reservation.id)] = reservation
    items: list[RunnerDeviceInventoryItem] = []
    for raw in row.device_inventory:
        uid = str(raw.get("udid") or "").strip()
        if not uid:
            continue
        current = active.get(uid)
        job = jobs.get(str(current.busy_job_id or "").strip()) if current else None
        reservation = (
            reservations.get(str(current.reservation_id or "").strip())
            if current
            else None
        )
        occupancy_kind = "job" if job else ("reservation" if reservation else "")
        items.append(
            RunnerDeviceInventoryItem(
                **raw,
                registered=_inventory_registered(row, uid, current),
                busy=bool(job),
                reserved=bool(reservation),
                occupancy_kind=occupancy_kind,
                occupancy_username=(
                    (job.created_by or "") if job else
                    (reservation.username or "") if reservation else ""
                ),
                occupancy_start_at=(
                    job.claimed_at if job else
                    reservation.start_at if reservation else None
                ),
                occupancy_end_at=(
                    reservation.expires_at if reservation else None
                ),
                occupancy_reference=(
                    job.id if job else reservation.id if reservation else ""
                ),
                occupancy_reason=(
                    job.name if job else reservation.reason if reservation else ""
                ),
                rejection_reason=(
                    "设备正在执行任务"
                    if job
                    else "设备处于有效预占"
                    if reservation
                    else ""
                ),
            )
        )
    return RunnerDeviceInventoryOut(
        runner_id=row.runner_id,
        org_id=(row.org_id or "").strip(),
        selection_mode=row.device_selection_mode or "all",
        selected_udids=list(row.selected_device_udids),
        policy_revision=int(row.device_policy_revision or 0),
        devices=items,
    )


def set_device_inventory(db: Session, runner_id: str, devices: list) -> RunnerDeviceInventoryOut:
    """保存完整发现清单；仅供可信的 managed probe / Runner 心跳路径。"""
    row = db_get(db, RunnerRow, runner_id)
    if row is None:
        raise LookupError(msg.RUNNER_NOT_FOUND.format(runner_id=runner_id))
    row.device_inventory = [
        d.model_dump(mode="json") if hasattr(d, "model_dump") else dict(d)
        for d in devices
    ]
    db.commit()
    return get_device_inventory(db, runner_id)


def update_device_selection(
    db: Session,
    runner_id: str,
    *,
    action: str,
    udids: list[str],
) -> RunnerDeviceSelectionOut:
    """持久化显式 allowlist，并立即从 TR 池删除被取消且未占用的设备。"""

    expire_reservations(db)
    row = db_get(db, RunnerRow, runner_id)
    if row is None:
        raise LookupError(msg.RUNNER_NOT_FOUND.format(runner_id=runner_id))
    requested = list(dict.fromkeys(str(x).strip() for x in udids if str(x).strip()))
    inventory_ids = {
        str(x.get("udid") or "").strip() for x in row.device_inventory
    }
    inventory_ids.discard("")
    unknown = [uid for uid in requested if uid not in inventory_ids]
    rejected: dict[str, str] = {
        uid: "设备不在该 Runner 最近发现清单中" for uid in unknown
    }
    valid = [uid for uid in requested if uid in inventory_ids]
    active = {
        d.udid: d for d in cast(list[DeviceRow], list(row.devices or []))
    }
    mode = (row.device_selection_mode or "all").strip()
    previous_selected = set(row.selected_device_udids)
    selected = set(previous_selected)
    op = (action or "set").strip().lower()
    if op not in {"set", "register", "unregister"}:
        raise ValueError("action must be set, register or unregister")
    if mode != "include":
        # all → include：unregister/set 以完整发现清单为基线；
        # register 只叠加「当前已在 TR 池」的设备，避免扫描后勾选一台却把整份清单写进 allowlist。
        selected = set(active) if op == "register" else set(inventory_ids)
        previous_selected = set(selected)
    target = set(valid)
    newly = [uid for uid in target if uid not in previous_selected]
    if op == "set":
        remove_candidates = selected - target
        selected = set(target)
        newly = sorted(target)
    elif op == "register":
        remove_candidates = set()
        selected.update(target)
    else:
        remove_candidates = set(target)
        selected.difference_update(target)
        newly = []

    unregistered: list[str] = []
    for uid in sorted(remove_candidates):
        device = active.get(uid)
        if device and device.busy_job_id:
            rejected[uid] = "设备正在执行任务，不能取消注册"
            selected.add(uid)
            continue
        if device and device.reservation_id:
            rejected[uid] = "设备处于有效预占，不能取消注册"
            selected.add(uid)
            continue
        if device is not None:
            db.delete(device)
        unregistered.append(uid)

    before = set(row.selected_device_udids) if mode == "include" else set(inventory_ids)
    row.device_selection_mode = "include"
    row.selected_device_udids = sorted(selected)
    if selected != before or mode != "include":
        row.device_policy_revision = int(row.device_policy_revision or 0) + 1
    if op in {"set", "register"}:
        _ensure_allowlisted_device_rows(db, row, refresh=True)
    db.commit()
    return RunnerDeviceSelectionOut(
        runner_id=row.runner_id,
        selection_mode="include",
        selected_udids=sorted(selected),
        policy_revision=int(row.device_policy_revision or 0),
        registered=sorted(uid for uid in newly if uid in selected and uid not in rejected)
        if op in {"set", "register"}
        else [],
        unregistered=unregistered,
        rejected=rejected,
    )


def list_runners(
    db: Session,
    auth=None,
    *,
    project_id: str = "",
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[RunnerOut], int]:

    rows = db.scalars(select(RunnerRow).order_by(RunnerRow.runner_id)).all()
    now = utcnow()
    outs = [runner_to_out(r, now=now) for r in rows]
    filtered = _filter_runners_for_auth(db, outs, auth, project_id=project_id)
    size = max(1, min(200, int(page_size)))
    pg = max(1, int(page))
    return slice_page(filtered, page=pg, page_size=size)


def _filter_runners_for_auth(
    db: Session, runners: list[RunnerOut], auth, *, project_id: str = ""
) -> list[RunnerOut]:
    """多组织时按 org / 项目作用域过滤 Runner 列表。

    - 无 auth / 平台 admin / 全局执行 Token：全部
    - 独立 Runner Token：仅本 runner_id
    - 普通用户：本 org 绑定，或 project_ids 与可见项目有交集；无组织体系时不限制
    """
    if auth is None:
        return runners
    from ....tenancy.projects import is_platform_admin, visible_project_filter

    if is_platform_admin(auth):
        return runners
    if getattr(auth, "kind", "") == "runner":
        rid = (getattr(auth, "runner_id", None) or "").strip()
        if rid:
            return [r for r in runners if r.runner_id == rid]
        return runners

    from sqlalchemy import func

    from ....core.models import OrganizationRow, ProjectRow
    from ....tenancy.organizations import member_org_ids, org_member_role
    from ..resources.pools import visible_pool_resource_ids

    user_orgs = member_org_ids(db, auth.user_id)
    ctx_org = (getattr(auth, "org_id", None) or "").strip()
    pid = (project_id or "").strip()
    if pid:
        from ....tenancy.projects import assert_can_access_project

        assert_can_access_project(db, auth, pid)
        project = db_get(db, ProjectRow, pid)
        project_org = (getattr(project, "org_id", None) or "").strip()
        if ctx_org and project_org and ctx_org != project_org:
            raise PermissionError("项目不属于当前组织上下文")
        allowed_orgs = {project_org} if project_org else set()
        visible_projects = {pid}
    else:
        allowed_orgs = {ctx_org} if ctx_org else set(user_orgs)
        visible_projects = visible_project_filter(db, auth) or set()
    manager_orgs = {
        oid
        for oid in allowed_orgs
        if org_member_role(db, auth.user_id, oid) in {"owner", "admin"}
    }
    runners = [
        r
        for r in runners
        if not (
            (r.registration_source or "platform") == "ide"
            and (r.owner_user_id or "")
            and r.owner_user_id != auth.user_id
            and (r.org_id or "").strip() not in manager_orgs
        )
    ]
    org_count = int(db.scalar(select(func.count()).select_from(OrganizationRow)) or 0)
    if org_count <= 0:
        return runners
    visible_runner_ids, _, pool_active = visible_pool_resource_ids(
        db, auth, project_id=project_id
    )
    if pool_active:
        return [
            r
            for r in runners
            if r.runner_id in visible_runner_ids or (r.org_id or "").strip() in manager_orgs
        ]

    out: list[RunnerOut] = []
    for r in runners:
        r_org = (r.org_id or "").strip()
        if r_org and r_org in allowed_orgs:
            out.append(r)
            continue
        r_projects = {str(p).strip() for p in (r.project_ids or []) if str(p).strip()}
        if r_projects and (r_projects & visible_projects):
            out.append(r)
            continue
        # 未绑定 org/project 的旧 Runner：仅平台 admin 可见（上面已放行）；此处隐藏
    return out


def deregister_runner(db: Session, runner_id: str) -> dict:
    """注销 Runner：删除节点记录及其设备行（relationship 级联）。

    - 节点不存在 → LookupError
    - 存在占用中设备（busy_job_id）→ ValueError，需先释放占用 / 等任务结束
    -     在线节点也可注销，但若该机 Runner 仍在运行，下次心跳会自愈重建（调用方应提示）
    """
    row = db_get(db, RunnerRow, runner_id)
    if row is None:
        raise LookupError(msg.RUNNER_NOT_FOUND.format(runner_id=runner_id))
    devices = list(row.devices or [])
    busy = [d.udid for d in devices if (d.busy_job_id or "").strip()]
    if busy:
        raise ValueError(msg.RUNNER_HAS_BUSY_DEVICES.format(udids=", ".join(busy)))
    now = utcnow()
    was_online = is_online(row.last_heartbeat_at, now=now)
    devices_removed = len(devices)
    db.delete(row)
    db.commit()
    return {
        "runner_id": runner_id,
        "devices_removed": devices_removed,
        "was_online": was_online,
    }


def issue_runner_token(
    db: Session,
    runner_id: str,
    *,
    org_id: str | None = None,
    project_ids: list[str] | None = None,
) -> tuple[str, str, str, list[str]]:
    """生成/轮换 Runner 独立令牌；可选绑定 org/project 作用域。

    ``org_id`` / ``project_ids`` 为 ``None`` 时保留原值。
    返回 (runner_id, plaintext_token, org_id, project_ids)。
    """


    row = db_get(db, RunnerRow, runner_id)
    if row is None:
        raise LookupError(msg.RUNNER_NOT_FOUND.format(runner_id=runner_id))
    raw = secrets.token_urlsafe(32)
    row.token_hash = hash_api_token(raw)
    if org_id is not None:
        row.org_id = (org_id or "").strip()
    if project_ids is not None:
        row.project_ids = list(project_ids)
    db.commit()
    return (
        str(row.runner_id),
        raw,
        (row.org_id or "").strip(),
        list(row.project_ids or []),
    )


def set_runner_scope(
    db: Session,
    runner_id: str,
    *,
    org_id: str | None = None,
    project_ids: list[str] | None = None,
) -> RunnerOut:
    """更新 Runner 作用域（不轮换 token）。"""
    row = db_get(db, RunnerRow, runner_id)
    if row is None:
        raise LookupError(msg.RUNNER_NOT_FOUND.format(runner_id=runner_id))
    if org_id is not None:
        row.org_id = (org_id or "").strip()
    if project_ids is not None:
        row.project_ids = list(project_ids)
    db.commit()
    db.refresh(row)
    return runner_to_out(row)
