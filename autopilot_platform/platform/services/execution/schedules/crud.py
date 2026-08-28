"""平台批跑计划：CRUD + 到期触发创建 Job。"""

from __future__ import annotations

from ....core import api_messages as msg

from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from autopilot_platform.core.schemas import JobCreate, ScheduleCreate, ScheduleOut, ScheduleUpdate
from autopilot_platform.core.job_platforms import apply_deviceless_run_target

from ....auth import AuthContext
from autopilot_platform.core.constants import JobStatus
from autopilot_platform.core.schemas import normalize_web_engine
from autopilot_platform.core.webhook_security import validate_webhook_url
from ....core.list_page import slice_page
from ....core.models import AppBuildRow, ArtifactRow, JobRow, ScheduleRow, UserRow, utcnow, db_get, new_id
from ....tenancy.projects import assert_can_access_project, assert_can_write_project
from ....authz.acl import assert_can_access_resource, filter_resources_by_acl
from ..jobs.creation import create_job
from ...shared.mappers import app_build_fields

_FIRE_ERRS = (
    OSError,
    RuntimeError,
    ValueError,
    TypeError,
    AttributeError,
    LookupError,
    PermissionError,
    SQLAlchemyError,
)


def schedule_to_out(row: ScheduleRow) -> ScheduleOut:
    snap = app_build_fields(row)
    return ScheduleOut(
        id=row.id,
        name=row.name or "Schedule",
        enabled=bool(row.enabled),
        project_dir=row.project_dir or "",
        artifact_id=row.artifact_id,
        app_build_id=getattr(row, "app_build_id", None),
        app_build_name=snap["app_build_name"],
        app_version_name=snap["app_version_name"],
        app_version_code=int(snap["app_version_code"] or 0),
        app_package_id=snap["app_package_id"],
        project_id=row.project_id or "",
        platform=row.platform or "android",
        device_udids=list(row.device_udids or []),
        parallel=bool(row.parallel),
        parallel_workers=int(row.parallel_workers or 0),
        backend_mode=row.backend_mode or "auto",
        web_engine=getattr(row, "web_engine", None) or "selenium",
        wda_bundle=row.wda_bundle or "",
        preferred_runner_id=row.preferred_runner_id,
        webhook_url=row.webhook_url or "",
        delay_sec=int(row.delay_sec or 0),
        interval_sec=int(row.interval_sec or 0),
        repeat=int(row.repeat or 0),
        stop_on_fail=bool(row.stop_on_fail),
        entry_paths=list(getattr(row, "entry_paths", None) or []),
        runs_done=int(row.runs_done or 0),
        next_run_at=row.next_run_at,
        last_job_id=row.last_job_id,
        last_passed=row.last_passed,
        created_by=row.created_by or "",
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _should_continue(row: ScheduleRow) -> bool:
    """对齐桌面 should_continue 语义。"""
    runs = int(row.runs_done or 0)
    interval = int(row.interval_sec or 0)
    repeat = int(row.repeat or 0)
    if interval <= 0 and runs >= 1:
        return False
    if 0 < repeat <= runs:
        return False
    if row.stop_on_fail and row.last_passed is False:
        return False
    return True


def create_schedule(db: Session, body: ScheduleCreate, auth: AuthContext) -> ScheduleOut:
    pid = (body.project_id or "").strip()
    if body.artifact_id:

        art = db_get(db, ArtifactRow, body.artifact_id.strip())
        if art is None:
            raise LookupError(msg.ARTIFACT_NOT_FOUND_ID.format(artifact_id=body.artifact_id))
        assert_can_access_resource(
            db,
            auth,
            resource_type="artifact",
            resource_id=str(art.id),
            project_id=str(art.project_id or ""),
            owner_username=str(art.uploaded_by or ""),
        )
        if not pid and art.project_id:
            pid = str(art.project_id)

    app_build_id = (body.app_build_id or "").strip() or None
    if app_build_id:

        build = db_get(db, AppBuildRow, app_build_id)
        if build is None:
            raise LookupError(msg.APP_BUILD_NOT_FOUND_ID.format(app_build_id=app_build_id))
        assert_can_access_resource(
            db,
            auth,
            resource_type="app_build",
            resource_id=str(build.id),
            project_id=str(build.project_id or ""),
            owner_username=str(build.uploaded_by or ""),
        )
        if not pid and build.project_id:
            pid = str(build.project_id)

    assert_can_write_project(db, auth, pid)

    now = utcnow()
    delay = max(0, int(body.delay_sec or 0))

    safe_webhook = validate_webhook_url((body.webhook_url or "").strip(), resolve=False)
    row = ScheduleRow(
        id=new_id(),
        name=(body.name or "Schedule").strip() or "Schedule",
        enabled=bool(body.enabled),
        project_dir=(body.project_dir or "").strip(),
        artifact_id=(body.artifact_id or "").strip() or None,
        app_build_id=app_build_id,
        project_id=pid,
        platform=body.platform or "android",
        parallel=bool(body.parallel),
        parallel_workers=int(body.parallel_workers or 0),
        backend_mode=body.backend_mode or "auto",
        web_engine=body.web_engine or "selenium",
        wda_bundle=body.wda_bundle or "",
        preferred_runner_id=body.preferred_runner_id,
        webhook_url=safe_webhook,
        delay_sec=delay,
        interval_sec=max(0, int(body.interval_sec or 0)),
        repeat=max(0, int(body.repeat if body.repeat is not None else 1)),
        stop_on_fail=bool(body.stop_on_fail),
        runs_done=0,
        next_run_at=now + timedelta(seconds=delay) if body.enabled else None,
        created_by=auth.username if auth.kind == "user" else auth.kind,
        created_at=now,
        updated_at=now,
    )
    row.device_udids = list(body.device_udids or [])
    row.entry_paths = list(body.entry_paths or [])
    apply_deviceless_run_target(row)
    db.add(row)
    db.commit()
    db.refresh(row)
    return schedule_to_out(row)


def list_schedules(
    db: Session,
    auth: AuthContext,
    *,
    project_id: str = "",
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[ScheduleOut], int]:

    q = select(ScheduleRow).order_by(ScheduleRow.created_at.desc())
    pid = (project_id or "").strip()
    if pid:
        assert_can_access_project(db, auth, pid)
        q = q.where(ScheduleRow.project_id == pid)
    rows = list(db.scalars(q).all())
    if not pid:
        rows = filter_resources_by_acl(
            db,
            auth,
            rows,
            resource_type="schedule",
            owner_attr="created_by",
        )
    filtered = [schedule_to_out(r) for r in rows]
    size = max(1, min(200, int(page_size)))
    pg = max(1, int(page))
    return slice_page(filtered, page=pg, page_size=size)


def get_schedule(db: Session, schedule_id: str, auth: AuthContext) -> ScheduleOut:
    row = db_get(db, ScheduleRow, schedule_id)
    if row is None:
        raise LookupError(msg.SCHEDULE_NOT_FOUND)
    assert_can_access_resource(
        db,
        auth,
        resource_type="schedule",
        resource_id=str(row.id),
        project_id=str(row.project_id or ""),
        owner_username=str(row.created_by or ""),
    )
    return schedule_to_out(row)


def update_schedule(
    db: Session, schedule_id: str, body: ScheduleUpdate, auth: AuthContext
) -> ScheduleOut:
    row = db_get(db, ScheduleRow, schedule_id)
    if row is None:
        raise LookupError(msg.SCHEDULE_NOT_FOUND)
    assert_can_access_resource(
        db,
        auth,
        resource_type="schedule",
        resource_id=str(row.id),
        project_id=str(row.project_id or ""),
        owner_username=str(row.created_by or ""),
        need_write=True,
    )
    if body.name is not None:
        row.name = body.name.strip() or row.name
    if body.webhook_url is not None:

        row.webhook_url = validate_webhook_url(body.webhook_url.strip(), resolve=False)
    if body.preferred_runner_id is not None:
        row.preferred_runner_id = body.preferred_runner_id or None
    if body.device_udids is not None:
        row.device_udids = list(body.device_udids)
    if body.entry_paths is not None:
        row.entry_paths = list(body.entry_paths)
    if body.delay_sec is not None:
        row.delay_sec = int(body.delay_sec)
    if body.interval_sec is not None:
        row.interval_sec = int(body.interval_sec)
    if body.repeat is not None:
        row.repeat = int(body.repeat)
    if body.stop_on_fail is not None:
        row.stop_on_fail = bool(body.stop_on_fail)
    if body.platform is not None:
        row.platform = (body.platform or "android").strip() or "android"
    if body.parallel is not None:
        row.parallel = bool(body.parallel)
    if body.parallel_workers is not None:
        row.parallel_workers = int(body.parallel_workers or 0)
    if body.backend_mode is not None:
        row.backend_mode = (body.backend_mode or "auto").strip() or "auto"
    if body.web_engine is not None:

        platform = str(row.platform or "android")
        row.web_engine = normalize_web_engine(body.web_engine, platform)
    if body.wda_bundle is not None:
        row.wda_bundle = body.wda_bundle or ""
    if body.project_dir is not None:
        row.project_dir = (body.project_dir or "").strip()

    pid = row.project_id or ""
    if body.project_id is not None:
        pid = (body.project_id or "").strip()
        assert_can_access_project(db, auth, pid)
        row.project_id = pid

    if body.artifact_id is not None:
        aid = (body.artifact_id or "").strip() or None
        if aid:

            art = db_get(db, ArtifactRow, aid)
            if art is None:
                raise LookupError(msg.ARTIFACT_NOT_FOUND_ID.format(artifact_id=aid))
            assert_can_access_resource(
                db,
                auth,
                resource_type="artifact",
                resource_id=str(art.id),
                project_id=str(art.project_id or ""),
                owner_username=str(art.uploaded_by or ""),
            )
            if not pid and art.project_id:
                pid = str(art.project_id)
                row.project_id = pid
        row.artifact_id = aid

    if body.app_build_id is not None:
        bid = (body.app_build_id or "").strip() or None
        if bid:

            build = db_get(db, AppBuildRow, bid)
            if build is None:
                raise LookupError(msg.APP_BUILD_NOT_FOUND_ID.format(app_build_id=bid))
            assert_can_access_resource(
                db,
                auth,
                resource_type="app_build",
                resource_id=str(build.id),
                project_id=str(build.project_id or ""),
                owner_username=str(build.uploaded_by or ""),
            )
            if not pid and build.project_id:
                pid = str(build.project_id)
                row.project_id = pid
        row.app_build_id = bid

    apply_deviceless_run_target(row)

    # 源字段变更后仍须保留可用源
    if not (row.project_dir or "").strip() and not (row.artifact_id or "").strip():
        raise ValueError(msg.SCHEDULE_SOURCE_REQUIRED)

    if body.enabled is not None:
        was = bool(row.enabled)
        row.enabled = bool(body.enabled)
        if row.enabled and not was:
            # 重新启用：从现在 + delay 起算
            row.next_run_at = utcnow() + timedelta(seconds=max(0, int(row.delay_sec or 0)))
            if row.stop_on_fail:
                row.last_passed = None
        if not row.enabled:
            row.next_run_at = None
    row.updated_at = utcnow()
    db.commit()
    db.refresh(row)
    return schedule_to_out(row)


def delete_schedule(db: Session, schedule_id: str, auth: AuthContext) -> None:
    row = db_get(db, ScheduleRow, schedule_id)
    if row is None:
        raise LookupError(msg.SCHEDULE_NOT_FOUND)
    assert_can_access_resource(
        db,
        auth,
        resource_type="schedule",
        resource_id=str(row.id),
        project_id=str(row.project_id or ""),
        owner_username=str(row.created_by or ""),
        need_write=True,
    )
    db.delete(row)
    db.commit()


def _auth_for_schedule_creator(db: Session, row: ScheduleRow) -> AuthContext:
    """用计划创建者身份建 Job，以便校验收录制品/应用 ACL。"""

    created_by = (row.created_by or "").strip()
    if not created_by or created_by in ("schedule", "runner", "system"):
        raise PermissionError(msg.SCHEDULE_CREATOR_UNAVAILABLE)
    user = db.scalars(select(UserRow).where(UserRow.username == created_by)).first()
    if user is None or bool(user.disabled):
        raise PermissionError(msg.SCHEDULE_CREATOR_UNAVAILABLE)
    return AuthContext(
        kind="user",
        username=str(user.username),
        user_id=str(user.id),
        role=str(user.role or "operator"),
    )


def _fire_once(db: Session, row: ScheduleRow) -> str:
    """创建一次 Job 并推进计划状态；返回 job_id。"""
    body = JobCreate(
        name=f"{row.name}#{int(row.runs_done or 0) + 1}",
        project_dir=row.project_dir or "",
        artifact_id=row.artifact_id,
        app_build_id=getattr(row, "app_build_id", None),
        project_id=row.project_id or "",
        platform=row.platform or "android",
        device_udids=list(row.device_udids or []),
        entry_paths=list(getattr(row, "entry_paths", None) or []),
        parallel=bool(row.parallel),
        parallel_workers=int(row.parallel_workers or 0),
        backend_mode=row.backend_mode or "auto",
        web_engine=getattr(row, "web_engine", None) or "selenium",
        wda_bundle=row.wda_bundle or "",
        preferred_runner_id=row.preferred_runner_id,
        webhook_url=row.webhook_url or "",
    )
    auth = _auth_for_schedule_creator(db, row)
    job = create_job(
        db,
        body,
        auth=auth,
        created_by=auth.username,
    )
    row.runs_done = int(row.runs_done or 0) + 1
    row.last_job_id = job.id
    row.last_passed = None
    row.updated_at = utcnow()
    # 次数已达上限则停；周期下一次时间留给「上一拍结束后」或 interval 到期
    repeat_n = int(row.repeat or 0)
    runs_n = int(row.runs_done or 0)
    if 0 < repeat_n <= runs_n:
        row.enabled = False
        row.next_run_at = None
    elif int(row.interval_sec or 0) <= 0:
        row.enabled = False
        row.next_run_at = None
    else:
        row.next_run_at = utcnow() + timedelta(seconds=int(row.interval_sec))
    db.commit()
    return job.id


def run_schedule_now(db: Session, schedule_id: str, auth: AuthContext) -> ScheduleOut:
    row = db_get(db, ScheduleRow, schedule_id)
    if row is None:
        raise LookupError(msg.SCHEDULE_NOT_FOUND)
    assert_can_access_resource(
        db,
        auth,
        resource_type="schedule",
        resource_id=str(row.id),
        project_id=str(row.project_id or ""),
        owner_username=str(row.created_by or ""),
        need_write=True,
    )
    _fire_once(db, row)
    db.refresh(row)
    return schedule_to_out(row)


def _claim_schedule_fire(db: Session, row: ScheduleRow, now) -> bool:
    """用条件 UPDATE 领取本次触发租约，防止多实例同时创建同一拍 Job。"""

    lease_until = now + timedelta(seconds=60)
    result = db.execute(
        update(ScheduleRow)
        .where(
            ScheduleRow.id == row.id,
            ScheduleRow.enabled.is_(True),
            ScheduleRow.next_run_at.is_not(None),
            ScheduleRow.next_run_at <= now,
        )
        .values(next_run_at=lease_until, updated_at=now)
        .execution_options(synchronize_session=False)
    )
    db.commit()
    if int(getattr(result, "rowcount", 0) or 0) != 1:
        return False
    db.refresh(row)
    return True


def tick_due_schedules(db: Session, *, now=None) -> list[str]:
    """扫描到期计划并触发；返回创建的 job_id 列表。"""

    now = now or utcnow()
    rows = list(
        db.scalars(
            select(ScheduleRow).where(
                ScheduleRow.enabled.is_(True),
                ScheduleRow.next_run_at.is_not(None),
                ScheduleRow.next_run_at <= now,
            )
        ).all()
    )
    job_ids: list[str] = []
    for row in rows:
        if not _claim_schedule_fire(db, row, now):
            continue
        if row.last_job_id:
            prev = db_get(db, JobRow, row.last_job_id)
            if prev is not None and prev.status in (
                JobStatus.PENDING.value,
                JobStatus.CLAIMED.value,
                JobStatus.RUNNING.value,
            ):
                # 上一拍未结束：延后，避免重叠
                row.next_run_at = now + timedelta(seconds=max(5, int(row.interval_sec or 5)))
                row.updated_at = now
                db.commit()
                continue
        try:
            jid = _fire_once(db, row)
            job_ids.append(jid)
        except _FIRE_ERRS:
            row.updated_at = utcnow()
            db.commit()
    return job_ids


def on_job_finished(db: Session, job_id: str, *, passed: bool | None) -> None:
    """任务终态回调：更新引用该 job 的计划的 last_passed，并可能停计。"""
    rows = list(
        db.scalars(select(ScheduleRow).where(ScheduleRow.last_job_id == job_id)).all()
    )
    if not rows:
        return
    for row in rows:
        row.last_passed = passed
        row.updated_at = utcnow()
        if row.stop_on_fail and passed is False:
            row.enabled = False
            row.next_run_at = None
        elif row.enabled and not _should_continue(row):
            row.enabled = False
            row.next_run_at = None
    db.commit()
