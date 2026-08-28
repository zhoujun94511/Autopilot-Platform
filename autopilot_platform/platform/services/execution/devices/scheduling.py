"""设备池与占用看板。"""

from __future__ import annotations

from datetime import timezone

# noinspection PyPackageRequirements
from sqlalchemy import select, update
# noinspection PyPackageRequirements
from sqlalchemy.orm import Session, selectinload

from autopilot_platform.core.backends import backends_ok, required_backends
from autopilot_platform.core.constants import (
    DEVICE_STATE_CONFLICT,
    DEVICE_STATE_READY,
    DEVICE_STATES_SCHEDULABLE,
    JobStatus,
)
from ....core import api_messages as msg
from ....core.list_page import slice_page
from ....core.models import DeviceRow, JobRow, utcnow, db_get
from ...shared import BEST_EFFORT_ERRS, is_online
from ..resources.pools import device_allowed_for_project


def _remaining_seconds(expires_at, now) -> int:
    if expires_at is None:
        return 0
    if expires_at.tzinfo is None and now.tzinfo is not None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if now.tzinfo is None and expires_at.tzinfo is not None:
        now = now.replace(tzinfo=timezone.utc)
    return max(0, int((expires_at - now).total_seconds()))


# 人工预占原因标签（前端预设；写入 reason 前缀，便于摘要与日后远控旁路对齐）
_RESERVE_PURPOSE_TAGS: tuple[tuple[str, str], ...] = (
    ("[远控预留]", "远控预留"),
    ("[手工调试]", "手工调试"),
    ("[演示联调]", "演示联调"),
)


def parse_reservation_purpose(reason: str) -> str:
    text = (reason or "").strip()
    for tag, label in _RESERVE_PURPOSE_TAGS:
        if text.startswith(tag):
            return label
    return ""


def build_occupy_summary(
    *,
    busy_kind: str,
    busy_job_name: str = "",
    busy_job_id: str | None = None,
    busy_job_project_id: str = "",
    reservation_username: str = "",
    reservation_reason: str = "",
) -> str:
    """人读占用摘要：批跑占用 vs 人工预占。"""
    kind = (busy_kind or "").strip()
    if kind == "job":
        name = (busy_job_name or "").strip() or "批跑任务"
        jid = (busy_job_id or "").strip()
        short = f"{jid[:8]}…" if len(jid) > 8 else jid
        proj = (busy_job_project_id or "").strip()
        parts = ["批跑占用", name]
        if short:
            parts.append(short)
        if proj:
            parts.append(f"项目 {proj}")
        return " · ".join(parts)
    if kind == "reservation":
        user = (reservation_username or "").strip() or "用户"
        purpose = parse_reservation_purpose(reservation_reason)
        parts = ["人工预占", user]
        if purpose:
            parts.append(purpose)
        return " · ".join(parts)
    return ""


def _clear_multi_runner_note(device: DeviceRow) -> None:
    note = (device.health_note or "").strip()
    if note.startswith("multi-runner"):
        device.health_note = ""


def reconcile_multi_runner_udids(
    db: Session,
    *,
    runner_id: str,
    seen_udids: set[str],
    now=None,
) -> None:
    """多 Runner 同 UDID 在线冲突调和。

    策略（稳定优先，避免 last-heartbeat 抖动夺权）：
    - 仅一台在线挂载 → 清除 conflict 标记（恢复为可调度语义由本机上报 state 决定）
    - 多台在线且某台已 busy → 忙的一侧保持；其余标 conflict
    - 多台在线且皆空闲 → ``runner_id`` 字典序最小者为 primary，其余 conflict

    ``runner_id`` 为触发本次调和的心跳方（诊断用）；裁决只看全局在线 peer 集合。
    """
    if not seen_udids:
        return
    # 心跳方 id：供调试/断点；primary 裁决不依赖「谁先到」
    _heartbeat_runner_id = (runner_id or "").strip()
    now = now or utcnow()
    for uid in seen_udids:
        peers = list(
            db.scalars(
                select(DeviceRow)
                .where(DeviceRow.udid == uid)
                .options(selectinload(DeviceRow.runner))
            ).all()
        )
        online = [
            d
            for d in peers
            if d.runner is not None and is_online(d.runner.last_heartbeat_at, now=now)
        ]
        if len(online) <= 1:
            for d in online:
                if (d.state or "").strip().lower() == DEVICE_STATE_CONFLICT:
                    d.state = DEVICE_STATE_READY
                    _clear_multi_runner_note(d)
                    d.updated_at = now
            continue

        busy = next((d for d in online if (d.busy_job_id or "").strip()), None)
        if busy is not None:
            primary_id = busy.runner_id
            reason = (
                f"multi-runner conflict: UDID also online on {primary_id} "
                f"(busy_job={busy.busy_job_id}); not schedulable here"
                f" (heartbeat={_heartbeat_runner_id})"
            )
        else:
            primary_id = min(d.runner_id for d in online)
            reason = (
                f"multi-runner conflict: UDID also online on {primary_id}; "
                f"primary wins until the other runner goes offline"
                f" (heartbeat={_heartbeat_runner_id})"
            )

        for d in online:
            if d.runner_id == primary_id:
                if (d.state or "").strip().lower() == DEVICE_STATE_CONFLICT:
                    d.state = DEVICE_STATE_READY
                    _clear_multi_runner_note(d)
                    d.updated_at = now
                continue
            d.state = DEVICE_STATE_CONFLICT
            d.health_note = reason[:512]
            d.updated_at = now


def udid_exclusive_for_runner(
    db: Session,
    runner_id: str,
    udid: str,
    *,
    now=None,
) -> bool:
    """该 UDID 对 runner 是否全局可独占调度。

    - 其它 Runner 行已 busy → 否
    - 其它 **在线且非 conflict** 的挂载 → 否（双主）
    - 其它在线但已标 conflict → 允许（本侧为 primary）
    """
    uid = (udid or "").strip()
    if not uid:
        return False
    now = now or utcnow()
    rows = list(
        db.scalars(
            select(DeviceRow)
            .where(DeviceRow.udid == uid)
            .options(selectinload(DeviceRow.runner))
        ).all()
    )
    for d in rows:
        if d.runner_id == runner_id:
            continue
        if (d.busy_job_id or "").strip():
            return False
        if d.runner is None or not is_online(d.runner.last_heartbeat_at, now=now):
            continue
        other_state = (getattr(d, "state", None) or "").strip().lower()
        if other_state != DEVICE_STATE_CONFLICT:
            return False
    return True


def _board_row_rank(item: dict) -> tuple:
    """看板去重排序：busy > 非 conflict > runner_id。"""
    state = (item.get("state") or "").strip().lower()
    busy = 0 if item.get("busy") else 1
    conflict = 0 if state != DEVICE_STATE_CONFLICT else 1
    return busy, conflict, str(item.get("runner_id") or "")


def _collapse_devices_by_udid(items: list[dict]) -> list[dict]:
    """同一 UDID 多 Runner 在线时，看板只展示 primary 一行（调度侧仍保留全量行）。"""
    from autopilot_platform.core.constants import DEVICE_STATE_CONFLICT

    groups: dict[str, list[dict]] = {}
    for item in items:
        uid = str(item.get("udid") or "").strip()
        if not uid:
            continue
        groups.setdefault(uid, []).append(item)

    out: list[dict] = []
    for uid in sorted(groups.keys()):
        peers = groups[uid]
        primary = sorted(peers, key=_board_row_rank)[0]
        row = dict(primary)
        # 展示层容错：不把 conflict 副本和 multi-runner 告警推给用户
        if (row.get("state") or "").strip().lower() == DEVICE_STATE_CONFLICT:
            row["state"] = "ready"
        row["conflict"] = False
        note = (row.get("health_note") or "").strip()
        if note.startswith("multi-runner"):
            row["health_note"] = ""
        alt = sorted(
            {
                str(p.get("runner_id") or "")
                for p in peers
                if str(p.get("runner_id") or "")
                and str(p.get("runner_id") or "") != str(row.get("runner_id") or "")
            }
        )
        if alt:
            row["alt_runner_ids"] = alt
        out.append(row)
    return out


def _collect_tr_devices(
    db: Session,
    auth=None,
    *,
    project_id: str = "",
) -> list[dict]:
    """在线 TR 设备全量（折叠 + ACL 过滤后）。

    仅包含 Runner 心跳在线的设备；注册名单离线时只在 inventory API 可见。
    """
    from ....core.models import DeviceRemoteSessionRow, DeviceReservationRow, UserRow
    # 延迟：reservations → board → scheduling，避免模块顶循环依赖
    from ...remote.reservations import (
        can_user_manage_device,
        can_user_use_device,
        expire_reservations,
        runner_source,
    )

    now = utcnow()
    expire_reservations(db)
    rows = db.scalars(
        select(DeviceRow).options(selectinload(DeviceRow.runner)).order_by(DeviceRow.udid)
    ).all()
    job_ids = [d.busy_job_id for d in rows if (d.busy_job_id or "").strip()]
    jobs: dict[str, JobRow] = {}
    if job_ids:
        for j in db.scalars(select(JobRow).where(JobRow.id.in_(job_ids))).all():
            jobs[j.id] = j
    reservations = {
        row.device_id: row
        for row in db.scalars(
            select(DeviceReservationRow).where(
                DeviceReservationRow.status == "active"
            )
        ).all()
    }
    # 与 sessions._ACTIVE 对齐；勿 import sessions，避免 board ↔ remote 循环依赖
    active_remote = set(
        db.scalars(
            select(DeviceRemoteSessionRow.device_id).where(
                DeviceRemoteSessionRow.status.in_(
                    ("pending", "ready", "connected")
                )
            )
        ).all()
    )
    owner_ids = {
        (d.runner.owner_user_id or "").strip()
        for d in rows
        if d.runner is not None and (d.runner.owner_user_id or "").strip()
    }
    owner_names: dict[str, str] = {
        str(row.id): str(row.username)
        for row in (
            db.scalars(select(UserRow).where(UserRow.id.in_(owner_ids))).all()
            if owner_ids
            else []
        )
    }
    raw: list[dict] = []
    for d in rows:
        runner = d.runner
        if runner is None:
            continue
        runner_online = is_online(runner.last_heartbeat_at, now=now)
        if not runner_online:
            continue
        jid = (d.busy_job_id or "").strip() or None
        job = jobs.get(jid) if jid else None
        reservation = reservations.get(d.id)
        owner_id = (getattr(runner, "owner_user_id", None) or "").strip()
        source = runner_source(runner)
        state = getattr(d, "state", "") or "ready"
        busy_kind = "job" if jid else ("reservation" if reservation else "")
        job_name = (job.name if job else "") or ""
        job_project = (job.project_id if job else "") or ""
        res_user = reservation.username if reservation else ""
        res_reason = reservation.reason if reservation else ""
        health_note = getattr(d, "health_note", "") or ""
        raw.append(
            {
                "id": d.id,
                "udid": d.udid,
                "platform": d.platform,
                "name": d.name,
                "model": d.model,
                "os_version": getattr(d, "os_version", "") or "",
                "state": state,
                "conflict": (state or "").strip().lower() == DEVICE_STATE_CONFLICT,
                "admin_disabled": bool(getattr(d, "admin_disabled", False)),
                "backends": list(getattr(d, "backends", None) or []),
                "health_note": health_note,
                "labels": d.labels,
                "runner_id": d.runner_id,
                "runner_online": runner_online,
                "runner_org_id": (getattr(runner, "org_id", None) or "").strip(),
                "registration_source": source,
                "owner_user_id": owner_id,
                "owner_username": owner_names.get(owner_id, ""),
                "can_manage": bool(
                    auth is not None and can_user_manage_device(db, auth, d)
                ),
                "can_reserve": bool(
                    runner_online
                    and auth is not None
                    and getattr(auth, "kind", "") == "user"
                    and can_user_use_device(db, auth, d)
                    and not jid
                    and reservation is None
                ),
                "busy": bool(jid or reservation),
                "busy_kind": busy_kind,
                "busy_job_id": jid,
                "busy_job_name": job_name,
                "busy_job_status": (job.status if job else "") or "",
                "busy_job_project_id": job_project,
                "reservation_id": reservation.id if reservation else None,
                "reservation_user_id": (
                    (reservation.user_id or "") if reservation else ""
                ),
                "reservation_username": res_user,
                "remote_session_active": d.id in active_remote,
                "reservation_reason": res_reason,
                "reservation_purpose": parse_reservation_purpose(res_reason),
                "reservation_expires_at": (
                    reservation.expires_at if reservation else None
                ),
                "reservation_remaining_seconds": (
                    _remaining_seconds(reservation.expires_at, now)
                    if reservation
                    else 0
                ),
                "can_release_reservation": bool(
                    reservation
                    and auth is not None
                    and getattr(auth, "kind", "") == "user"
                    and (
                        reservation.user_id == getattr(auth, "user_id", "")
                        or can_user_manage_device(db, auth, d)
                    )
                ),
                "occupy_summary": build_occupy_summary(
                    busy_kind=busy_kind,
                    busy_job_name=job_name,
                    busy_job_id=jid,
                    busy_job_project_id=job_project,
                    reservation_username=res_user,
                    reservation_reason=res_reason,
                ),
            }
        )
    collapsed = _collapse_devices_by_udid(raw)
    return _filter_devices_for_auth(db, collapsed, auth, project_id=project_id)


def _normalize_platform_bucket(raw: str) -> str:
    p = (raw or "").strip().lower()
    if p in ("android", "and"):
        return "android"
    if p in ("ios", "iphone", "ipad"):
        return "ios"
    if p in ("web", "browser", "chrome", "desktop"):
        return "web"
    return "other"


def _filter_devices_list(
    devices: list[dict],
    *,
    q: str = "",
    platform: str = "",
    busy: str = "",
) -> list[dict]:
    """面板筛选：平台桶 / 忙闲 / 关键词（在 auth 过滤之后、分页之前）。"""
    query = (q or "").strip().lower()
    plat = (platform or "").strip().lower()
    busy_f = (busy or "").strip().lower()

    out: list[dict] = []
    for d in devices:
        if plat and plat != "all":
            if _normalize_platform_bucket(str(d.get("platform") or "")) != plat:
                continue
        if busy_f == "free" and d.get("busy"):
            continue
        if busy_f == "busy" and not d.get("busy"):
            continue
        if query:
            hay = " ".join(
                str(x)
                for x in (
                    d.get("udid"),
                    d.get("platform"),
                    d.get("name"),
                    d.get("model"),
                    d.get("os_version"),
                    d.get("state"),
                    " ".join(d.get("backends") or []),
                    d.get("runner_id"),
                    d.get("registration_source"),
                    d.get("owner_username"),
                    d.get("reservation_username"),
                    d.get("reservation_reason"),
                    d.get("busy_job_name"),
                    d.get("busy_job_id"),
                )
                if x
            ).lower()
            if query not in hay:
                continue
        out.append(d)
    return out


def list_tr_devices(
    db: Session,
    auth=None,
    *,
    project_id: str = "",
    page: int = 1,
    page_size: int = 50,
    q: str = "",
    platform: str = "",
    busy: str = "",
) -> tuple[list[dict], int]:
    """仅返回在线 Runner 上的设备（与 IDE 本地池隔离）。

    同 UDID 被多 Runner 挂载时按 primary 折叠为一行，避免看板双行干扰选机。
    ``auth`` 非空时按组织/项目可见性过滤（平台 admin 看全部）。
    返回 (当前页 items, total)。
    """
    filtered = _filter_devices_list(
        _collect_tr_devices(db, auth=auth, project_id=project_id),
        q=q,
        platform=platform,
        busy=busy,
    )
    size = max(1, min(200, int(page_size)))
    pg = max(1, int(page))
    return slice_page(filtered, page=pg, page_size=size)


def _filter_devices_for_auth(
    db: Session, devices: list[dict], auth, *, project_id: str = ""
) -> list[dict]:
    """多组织时按 org / 项目过滤设备列表。

    - 无 auth / 平台 admin / 全局执行 Token：全部
    - 独立 Runner Token：仅本 runner_id
    - 普通用户：本 org 绑定的 Runner，或忙任务所属可见项目；无组织体系时不限制
    """
    if auth is None:
        return devices
    from ....tenancy.projects import is_platform_admin, visible_project_filter

    if is_platform_admin(auth):
        return devices
    if getattr(auth, "kind", "") == "runner":
        rid = (getattr(auth, "runner_id", None) or "").strip()
        if rid:
            return [d for d in devices if (d.get("runner_id") or "") == rid]
        # 全局 MC_API_TOKEN（执行通道）：仍看全部，便于调度诊断
        return devices

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
    devices = [
        d
        for d in devices
        if not (
            str(d.get("registration_source") or "platform") == "ide"
            and str(d.get("owner_user_id") or "")
            and str(d.get("owner_user_id") or "") != auth.user_id
            and str(d.get("runner_org_id") or "") not in manager_orgs
        )
    ]
    org_count = int(db.scalar(select(func.count()).select_from(OrganizationRow)) or 0)
    if org_count <= 0:
        return devices
    _, visible_device_ids, pool_active = visible_pool_resource_ids(
        db, auth, project_id=project_id
    )
    if pool_active:
        return [
            d
            for d in devices
            if str(d.get("id") or "") in visible_device_ids
            or str(d.get("runner_org_id") or "") in manager_orgs
        ]

    out: list[dict] = []
    for d in devices:
        r_org = str(d.get("runner_org_id") or "").strip()
        if r_org and r_org in allowed_orgs:
            out.append(d)
            continue
        jpid = str(d.get("busy_job_project_id") or "").strip()
        if jpid and jpid in visible_projects:
            out.append(d)
            continue
    return out


def device_board(
    db: Session,
    auth=None,
    *,
    project_id: str = "",
    page: int = 1,
    page_size: int = 50,
    summary_only: bool = False,
    q: str = "",
    platform: str = "",
    busy: str = "",
) -> dict:
    """设备占用看板：汇总 + 明细（明细可分页；summary_only 时不返回 devices）。"""
    devices = _collect_tr_devices(db, auth=auth, project_id=project_id)
    filtered = _filter_devices_list(devices, q=q, platform=platform, busy=busy)
    by_platform: dict[str, dict[str, int]] = {}
    by_runner: dict[str, dict[str, int]] = {}
    for d in devices:
        plat = str(d.get("platform") or "unknown")
        rid = str(d.get("runner_id") or "unknown")
        by_platform.setdefault(plat, {"total": 0, "busy": 0, "free": 0})
        by_runner.setdefault(rid, {"total": 0, "busy": 0, "free": 0})
        by_platform[plat]["total"] += 1
        by_runner[rid]["total"] += 1
        if d.get("busy"):
            by_platform[plat]["busy"] += 1
            by_runner[rid]["busy"] += 1
        else:
            by_platform[plat]["free"] += 1
            by_runner[rid]["free"] += 1
    busy_n = sum(1 for d in devices if d.get("busy"))
    size = max(1, min(200, int(page_size)))
    pg = max(1, int(page))
    page_items, _ = slice_page(filtered, page=pg, page_size=size)
    visible_devices = [] if summary_only else page_items
    return {
        "summary": {
            "online": len(devices),
            "busy": busy_n,
            "free": len(devices) - busy_n,
            "by_platform": by_platform,
            "by_runner": by_runner,
        },
        "devices": visible_devices,
    }


def release_device(db: Session, udid: str) -> dict:
    """强制释放设备占用（admin 运维）。

    会取消占用任务；claimed/running 的 busy 保留到 Runner complete ACK，
    防止旧进程仍在使用设备时被新任务领取。
    """
    uid = (udid or "").strip()
    if not uid:
        raise ValueError("udid required")
    rows = list(db.scalars(select(DeviceRow).where(DeviceRow.udid == uid)).all())
    if not rows:
        raise LookupError(msg.DEVICE_NOT_FOUND.format(udid=uid))
    prev = ""
    for d in rows:
        if d.busy_job_id:
            prev = d.busy_job_id

    cancelled_job_id = None
    was_active = False
    jid = (prev or "").strip()
    if jid:
        job = db_get(db, JobRow, jid)
        if job is not None and job.status in (
            JobStatus.PENDING.value,
            JobStatus.CLAIMED.value,
            JobStatus.RUNNING.value,
        ):
            was_active = job.status in (
                JobStatus.CLAIMED.value,
                JobStatus.RUNNING.value,
            )
            job.status = JobStatus.CANCELLED.value
            job.error = (job.error or "") or "cancelled by device release"
            job.updated_at = utcnow()
            cancelled_job_id = jid
        if not was_active:
            for d in db.scalars(select(DeviceRow).where(DeviceRow.busy_job_id == jid)).all():
                d.busy_job_id = None
                d.updated_at = utcnow()
    elif prev:
        for d in rows:
            d.busy_job_id = None
            d.updated_at = utcnow()

    db.commit()
    warning = ""
    if was_active:
        warning = (
            "cancel signaled; device remains busy until the runner acknowledges completion"
        )
    return {
        "udid": uid,
        "released_job_id": prev or None,
        "cancelled_job_id": cancelled_job_id,
        "cleared": not was_active,
        "warning": warning,
    }


def set_device_maintenance(
    db: Session,
    udid: str,
    disabled: bool,
    *,
    release: bool = False,
) -> dict:
    """设置/解除管理员维护态（admin 运维）。

    - True=停用：该物理设备不再参与调度（与 Runner 上报的 state 分离，心跳不覆盖）。
    - False=恢复：重新可调度。
    对所有匹配该 UDID 的设备行统一设置（多 Runner 同挂载时保持一致）。

    ``release=True`` 且 ``disabled=True`` 时「停用即腾空」：同时中断在跑任务并释放占用
    （复用 release_device 语义）；否则停用不影响正在执行的任务。
    """
    uid = (udid or "").strip()
    if not uid:
        raise ValueError("udid required")
    rows = list(db.scalars(select(DeviceRow).where(DeviceRow.udid == uid)).all())
    if not rows:
        raise LookupError(msg.DEVICE_NOT_FOUND.format(udid=uid))
    now = utcnow()
    for d in rows:
        d.admin_disabled = bool(disabled)
        d.updated_at = now
    released: dict | None = None
    if disabled and release:
        # release_device 会 select 同 UDID 行（identity map 命中上面已改的对象），
        # 中断在跑任务并 commit，一并持久化 admin_disabled。
        released = release_device(db, uid)
    else:
        db.commit()
    return {
        "udid": uid,
        "admin_disabled": bool(disabled),
        "affected": len(rows),
        "released": released,
    }


def _clear_device_busy(db: Session, job_id: str) -> None:
    rows = db.scalars(select(DeviceRow).where(DeviceRow.busy_job_id == job_id)).all()
    for d in rows:
        d.busy_job_id = None
        d.updated_at = utcnow()


def reconcile_orphan_device_busy(db: Session) -> list[str]:
    """清掉「Job 已终态或不存在」仍挂着的 busy_job_id；返回被清理的 UDID。

    不碰 claimed/running 占用；也不改心跳保 busy 的语义。
    """
    terminal = frozenset(
        {
            JobStatus.SUCCEEDED.value,
            JobStatus.FAILED.value,
            JobStatus.CANCELLED.value,
        }
    )
    rows = list(
        db.scalars(select(DeviceRow).where(DeviceRow.busy_job_id.is_not(None))).all()
    )
    cleared: list[str] = []
    for d in rows:
        jid = (d.busy_job_id or "").strip()
        if not jid:
            continue
        job = db_get(db, JobRow, jid)
        if job is None or (job.status or "") in terminal:
            d.busy_job_id = None
            d.updated_at = utcnow()
            cleared.append(str(d.udid or ""))
    cleared = [u for u in cleared if u]
    if cleared:
        db.commit()
        try:
            from ....ops import audit as audit_svc

            audit_svc.write_audit(
                db,
                action="device.busy_orphan_clear",
                actor="reconcile",
                actor_kind="system",
                resource_type="device",
                detail=(
                    f"count={len(cleared)};udids={','.join(cleared[:20])}"
                ),
            )
        except BEST_EFFORT_ERRS:
            pass
    return cleared


def _occupy_devices(
    db: Session,
    runner_id: str,
    udids: list[str],
    job_id: str,
    *,
    project_id: str = "",
    job_username: str = "",
) -> None:
    """原子占用：本 Runner 行空闲写入；并拒绝其它 Runner 已 busy / 在线同挂载。"""
    if not udids:
        return
    now = utcnow()
    # 延迟：reservations → board → scheduling，避免模块顶循环依赖
    from ...remote.reservations import (
        active_reservation,
        username_can_use_device,
    )
    for uid in set(udids):
        target = db.scalar(
            select(DeviceRow).where(
                DeviceRow.runner_id == runner_id, DeviceRow.udid == uid
            )
        )
        if target is None or not username_can_use_device(db, job_username, target):
            raise RuntimeError(f"device not authorized for job owner: {uid}")
        reservation = active_reservation(db, target.id)
        if reservation is not None and reservation.username != (job_username or "").strip():
            raise RuntimeError(f"device reserved by another user: {uid}")
        if project_id:
            if not device_allowed_for_project(db, target, project_id):
                raise RuntimeError(f"device not authorized by resource pool: {uid}")
        if not udid_exclusive_for_runner(db, runner_id, uid, now=now):
            raise RuntimeError(
                f"device contested or busy on another runner: {uid}"
            )
        result = db.execute(
            update(DeviceRow)
            .where(
                DeviceRow.runner_id == runner_id,
                DeviceRow.udid == uid,
                (DeviceRow.busy_job_id.is_(None)) | (DeviceRow.busy_job_id == ""),
                (
                    DeviceRow.reservation_id.is_(None)
                    if reservation is None
                    else (
                        DeviceRow.reservation_id.is_(None)
                        | (DeviceRow.reservation_id == reservation.id)
                    )
                ),
            )
            .values(busy_job_id=job_id, updated_at=now)
        )
        rowcount = int(getattr(result, "rowcount", 0) or 0)
        if rowcount != 1:
            raise RuntimeError(f"device not free or missing on runner: {uid}")


def _devices_busy(db: Session, runner_id: str, udids: list[str]) -> bool:
    """本 Runner 上是否有任一目标 UDID 已被占用。"""
    if not udids:
        return False
    want = set(udids)
    rows = db.scalars(select(DeviceRow).where(DeviceRow.runner_id == runner_id)).all()
    for d in rows:
        if d.udid in want and d.busy_job_id:
            return True
    return False


def _required_backends(platform: str, backend_mode: str) -> set[str] | None:
    """Job 所需后端标签集合；None 表示 auto（仅按平台匹配任意可用后端）。"""
    return required_backends(platform, backend_mode)


def _device_backends_ok(device: DeviceRow, platform: str, backend_mode: str) -> bool:
    """旧 Runner 未上报 backends 时放行；有上报则须与 Job 要求有交集。"""
    return backends_ok(
        device.backends,
        platform=platform or device.platform,
        backend_mode=backend_mode,
    )


def _device_schedulable(
    db: Session, device: DeviceRow, *, job_username: str = ""
) -> bool:
    """可调度：非占用、未被管理员停用，且健康态为 ready（空态兼容旧数据）。"""
    if device.busy_job_id:
        return False
    if getattr(device, "admin_disabled", False):
        return False
    # 延迟：reservations → board → scheduling，避免模块顶循环依赖
    from ...remote.reservations import (
        reservation_allows_username,
        username_can_use_device,
    )

    if not username_can_use_device(db, job_username, device):
        return False
    if not reservation_allows_username(db, device, job_username):
        return False
    state = (getattr(device, "state", None) or "ready").strip().lower()
    return state in DEVICE_STATES_SCHEDULABLE


def _devices_ready_on_runner(
    db: Session,
    runner_id: str,
    udids: list[str],
    *,
    platform: str = "",
    backend_mode: str = "auto",
    project_id: str = "",
    job_username: str = "",
) -> bool:
    """目标 UDID 必须全部挂在本 Runner、可调度、后端匹配，且全局无其它在线/busy 冲突。

    无 udids 的 Job（任意 Runner 可领）返回 True。
    """
    if not udids:
        return True
    want = set(udids)
    now = utcnow()
    rows = db.scalars(select(DeviceRow).where(DeviceRow.runner_id == runner_id)).all()
    by_udid = {d.udid: d for d in rows}
    for uid in want:
        d = by_udid.get(uid)
        if d is None:
            return False
        if not _device_schedulable(db, d, job_username=job_username):
            return False
        if not _device_backends_ok(d, platform or d.platform, backend_mode):
            return False
        if project_id:
            if not device_allowed_for_project(db, d, project_id):
                return False
        if not udid_exclusive_for_runner(db, runner_id, uid, now=now):
            return False
    return True


def _runner_has_schedulable_device(
    db: Session,
    runner_id: str,
    *,
    platform: str = "",
    backend_mode: str = "auto",
    project_id: str = "",
    job_username: str = "",
) -> bool:
    """无指定 UDID 的 Job：本 Runner 上至少有一台匹配平台/后端的可调度设备。"""
    rows = db.scalars(select(DeviceRow).where(DeviceRow.runner_id == runner_id)).all()
    plat = (platform or "").strip().lower()
    for d in rows:
        if not _device_schedulable(db, d, job_username=job_username):
            continue
        if plat and (d.platform or "").strip().lower() != plat:
            continue
        if not _device_backends_ok(d, plat or d.platform, backend_mode):
            continue
        if project_id:
            if not device_allowed_for_project(db, d, project_id):
                continue
        return True
    return False


clear_device_busy = _clear_device_busy
occupy_devices = _occupy_devices
devices_ready_on_runner = _devices_ready_on_runner
runner_has_schedulable_device = _runner_has_schedulable_device