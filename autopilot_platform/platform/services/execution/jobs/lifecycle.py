"""任务领取、完成、日志与回收。"""

from __future__ import annotations

from datetime import timedelta
import json as _json
import time

from ....core import api_messages as msg

from sqlalchemy import or_, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from autopilot_platform.core.webhook_security import validate_webhook_url
from autopilot_platform.core.constants import JobStatus
from autopilot_platform.core.job_platforms import (
    apply_deviceless_run_target,
    is_deviceless_platform,
    is_web_platform,
)
from autopilot_platform.core.schemas import JobCreate, JobOut, JobResultIn

from ....core.models import AppBuildRow, ArtifactRow, DeviceRow, JobRow, ReportRow, RunnerRow, utcnow, db_get, new_id
from ....core.db import session_factory
from ....auth import runner_scope_allows_project
from ....authz.acl import assert_can_access_resource, can_access_resource
from ....core.metrics import note_job_terminal, note_stale_reclaimed
from ....core.settings import (
    alert_on_failed,
    alert_on_stale,
    enforce_runtime_version,
    job_log_retention_days,
    job_logs_root,
    job_stale_sec,
    require_job_devices,
)
from ....tenancy.projects import (
    assert_can_access_project,
    assert_can_write_project,
    is_platform_admin,
)
from ...reports.storage import apply_version_snapshot
from ...shared import BEST_EFFORT_ERRS as _BEST_EFFORT_ERRS, is_online, job_to_out
from ..devices.scheduling import (
    clear_device_busy,
    devices_ready_on_runner,
    occupy_devices,
    runner_has_schedulable_device,
    reconcile_orphan_device_busy,
)
from ..resources.pools import runner_allowed_for_job
from ....core.list_page import slice_page
from ...shared.pagination import paginate

# claim 占用设备失败需回退 pending（含 ORM 层错误）
_CLAIM_ROLLBACK_ERRS = (*_BEST_EFFORT_ERRS, SQLAlchemyError)
_CLAIM_ACTIVE = (JobStatus.CLAIMED.value, JobStatus.RUNNING.value)

_DEP_BAD = frozenset(
    {
        JobStatus.FAILED.value,
        JobStatus.CANCELLED.value,
    }
)


def _normalize_depends_on(raw: list[str] | None) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()
    for x in raw or []:
        s = str(x or "").strip()
        if s and s not in seen:
            seen.add(s)
            ids.append(s)
    return ids


def _job_create_warnings(db: Session, row: JobRow) -> list[str]:
    """移动任务未绑应用资源 / 平台不一致：软提示，不阻断入队。"""
    warns: list[str] = []
    plat = str(row.platform or "").strip().lower()
    if is_deviceless_platform(plat):
        return warns
    bid = str(getattr(row, "app_build_id", None) or "").strip()
    if plat in ("android", "ios") and not bid:
        warns.append(msg.JOB_APP_BUILD_OPTIONAL_WARN)
    if bid:
        build = db_get(db, AppBuildRow, bid)
        bplat = str(getattr(build, "platform", "") or "").strip().lower() if build else ""
        if bplat and plat in ("android", "ios") and bplat != plat:
            warns.append(
                msg.JOB_APP_BUILD_PLATFORM_MISMATCH.format(
                    app_platform=bplat, job_platform=plat
                )
            )
        bpid = str(getattr(build, "project_id", "") or "").strip() if build else ""
        jpid = str(row.project_id or "").strip()
        if bpid and jpid and bpid != jpid:
            warns.append(
                msg.JOB_APP_BUILD_PROJECT_MISMATCH.format(
                    app_project=bpid, job_project=jpid
                )
            )
    return warns


def _deps_claim_gate(
    db: Session, dep_ids: list[str]
) -> tuple[str, str]:
    """依赖门禁：ready | waiting | blocked。

    blocked 时第二项为失败原因文案（含前置 id）。
    """
    for dep_id in dep_ids:
        dep = db_get(db, JobRow, dep_id)
        if dep is None:
            return "blocked", msg.JOB_DEPENDENCY_NOT_FOUND.format(job_id=dep_id)
        st = str(dep.status or "")
        if st in _DEP_BAD:
            return "blocked", msg.JOB_DEPENDENCY_FAILED.format(
                job_id=dep_id, status=st
            )
        if st != JobStatus.SUCCEEDED.value:
            return "waiting", ""
    return "ready", ""


def _fail_pending_dependents(db: Session, terminal_job_id: str) -> None:
    """前置失败/取消时，将仍 pending 且依赖它的任务级联标失败。"""
    queue = [str(terminal_job_id)]
    seen: set[str] = set()
    while queue:
        cur = queue.pop(0)
        if cur in seen:
            continue
        seen.add(cur)
        cur_row = db_get(db, JobRow, cur)
        cur_status = str(getattr(cur_row, "status", None) or JobStatus.FAILED.value)
        pending = list(
            db.scalars(
                select(JobRow).where(JobRow.status == JobStatus.PENDING.value)
            ).all()
        )
        for j in pending:
            deps = list(getattr(j, "depends_on", None) or [])
            if cur not in deps:
                continue
            j.status = JobStatus.FAILED.value
            j.error = msg.JOB_DEPENDENCY_FAILED.format(
                job_id=cur, status=cur_status
            )
            j.updated_at = utcnow()
            queue.append(str(j.id))


def create_job(
    db: Session,
    body: JobCreate,
    auth=None,
    *,
    created_by: str | None = None,
) -> JobOut:
    # 执行节点只领任务，不创建任务（运维 Token / 用户 JWT 可创建）
    if auth is not None and getattr(auth, "kind", "") == "runner":
        if not is_platform_admin(auth):
            raise PermissionError(msg.JOB_RUNNER_TOKEN_CANNOT_CREATE)

    artifact_id = (body.artifact_id or "").strip() or None
    app_build_id = (body.app_build_id or "").strip() or None
    project_dir = (body.project_dir or "").strip()
    project_id = (body.project_id or "").strip()

    plat = (body.platform or "").strip().lower()

    # web / http 没有 UDID 概念；强制设备仅约束 android/ios
    if require_job_devices() and not is_deviceless_platform(plat) and not list(body.device_udids or []):
        raise ValueError(msg.JOB_DEVICES_REQUIRED)
    if auth is not None and getattr(auth, "kind", "") == "user":
        # 延迟：仅用户 JWT 绑设备时校验远程设备 ACL
        from ...remote.policy import can_user_use_device

        for uid in set(body.device_udids or []):
            known = list(
                db.scalars(select(DeviceRow).where(DeviceRow.udid == uid)).all()
            )
            if known and not any(can_user_use_device(db, auth, d) for d in known):
                raise PermissionError(f"无权使用设备: {uid}")
    if artifact_id:

        art = db_get(db, ArtifactRow, artifact_id)
        if art is None:
            raise LookupError(msg.ARTIFACT_NOT_FOUND_ID.format(artifact_id=artifact_id))
        if auth is not None:
            assert_can_access_resource(
                db,
                auth,
                resource_type="artifact",
                resource_id=str(art.id),
                project_id=str(art.project_id or ""),
                owner_username=str(art.uploaded_by or ""),
            )
        if not project_dir and art.extract_path:
            project_dir = str(art.extract_path)
        if not project_id and art.project_id:
            project_id = str(art.project_id)
        # 执行核版本契约：manifest.required_runtime_version vs ap.__version__
        try:
            # 延迟：制品运行时契约只在有 artifact 时校验
            from ....ops.runtime_compat import check_artifact_runtime

            notes_raw = getattr(art, "manifest_notes_json", None) or ""
            notes = _json.loads(notes_raw) if notes_raw else {}
            required = ""
            if isinstance(notes, dict):
                required = str(notes.get("required_runtime_version") or "").strip()
            if required:
                check_artifact_runtime(
                    required_runtime_version=required,
                    enforce=enforce_runtime_version(),
                )
        except ValueError:
            raise
        except (OSError, RuntimeError, TypeError, AttributeError, ImportError):
            pass

    if app_build_id:
        build = db_get(db, AppBuildRow, app_build_id)
        if build is None:
            raise LookupError(msg.APP_BUILD_NOT_FOUND_ID.format(app_build_id=app_build_id))
        if auth is not None:
            assert_can_access_resource(
                db,
                auth,
                resource_type="app_build",
                resource_id=str(build.id),
                project_id=str(build.project_id or ""),
                owner_username=str(build.uploaded_by or ""),
            )
        if not project_id and build.project_id:
            project_id = str(build.project_id)

    # 解析完制品/安装包归属后再校验写权限；空 project_id 一律拒绝（含平台管理员）
    if auth is not None:
        assert_can_write_project(db, auth, project_id)

    if created_by is not None:
        creator = (created_by or "").strip()
    elif auth is not None and getattr(auth, "kind", "") == "user":
        creator = auth.username or ""
    else:
        creator = ""

    depends_on = _normalize_depends_on(list(body.depends_on or []))
    for dep_id in depends_on:
        dep = db_get(db, JobRow, dep_id)
        if dep is None:
            raise LookupError(msg.JOB_DEPENDENCY_NOT_FOUND.format(job_id=dep_id))


    # 纵深防御：即便绕过 JobCreate 校验，落库前再拦不安全 URL
    safe_webhook = validate_webhook_url((body.webhook_url or "").strip(), resolve=False)

    row = JobRow(
        id=new_id(),
        name=body.name or "Suite",
        status=JobStatus.PENDING.value,
        project_dir=project_dir,
        artifact_id=artifact_id,
        app_build_id=app_build_id,
        project_id=project_id,
        platform=body.platform,
        parallel=bool(body.parallel),
        parallel_workers=int(body.parallel_workers or 0),
        backend_mode=body.backend_mode or "auto",
        web_engine=getattr(body, "web_engine", None) or "selenium",
        wda_bundle=body.wda_bundle or "",
        preferred_runner_id=body.preferred_runner_id,
        webhook_url=safe_webhook,
        created_by=creator,
    )
    if str(row.id) in depends_on:
        raise ValueError(msg.JOB_DEPENDENCY_SELF)
    row.device_udids = list(body.device_udids or [])
    row.entry_paths = list(body.entry_paths or [])
    apply_deviceless_run_target(row)
    row.depends_on = depends_on
    db.add(row)
    db.commit()
    db.refresh(row)
    out = job_to_out(row)
    warns = _job_create_warnings(db, row)
    if warns:
        try:
            return out.model_copy(update={"warnings": warns})
        except AttributeError:
            data = out.model_dump()
            data["warnings"] = warns
            return JobOut(**data)
    return out


def get_job(db: Session, job_id: str) -> JobOut | None:
    row = db_get(db, JobRow, job_id)
    return job_to_out(row) if row else None


def list_jobs(
    db: Session,
    *,
    page: int = 1,
    page_size: int = 50,
    project_id: str = "",
    q: str = "",
    status: str = "",
    auth=None,
) -> tuple[list[JobOut], int]:
    pid = (project_id or "").strip()
    term = (q or "").strip()
    st = (status or "").strip()
    stmt = select(JobRow).order_by(JobRow.created_at.desc())
    if pid:
        if auth is not None:
            assert_can_access_project(db, auth, pid)
        stmt = stmt.where(JobRow.project_id == pid)
    if st:
        stmt = stmt.where(JobRow.status == st)
    if term:
        like = f"%{term}%"
        stmt = stmt.where(
            or_(
                JobRow.id.ilike(like),
                JobRow.name.ilike(like),
                JobRow.runner_id.ilike(like),
                JobRow.project_dir.ilike(like),
            )
        )
    size = max(1, min(200, int(page_size)))
    pg = max(1, int(page))
    if pid or auth is None:
        rows, total = paginate(db, stmt, page=pg, page_size=size)
        return [job_to_out(r) for r in rows], total
    rows = list(db.scalars(stmt).all())
    filtered = [
        job_to_out(r)
        for r in rows
        if can_access_resource(
            db,
            auth,
            resource_type="job",
            resource_id=str(r.id),
            project_id=str(r.project_id or ""),
            owner_username=str(r.created_by or ""),
        )
    ]
    return slice_page(filtered, page=pg, page_size=size)


def _normalized_udids(raw: list[str] | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for x in raw or []:
        s = str(x or "").strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _is_host_exclusive(job: JobRow) -> bool:
    """无 UDID 的 Job（web / 未指定设备）在同一 Runner 上互斥。"""
    return not _normalized_udids(list(job.device_udids or []))


def _runner_has_host_exclusive_job(db: Session, runner_id: str) -> bool:
    rows = list(
        db.scalars(
            select(JobRow).where(
                JobRow.runner_id == runner_id,
                JobRow.status.in_(_CLAIM_ACTIVE),
            )
        ).all()
    )
    return any(_is_host_exclusive(r) for r in rows)


def _requested_udids_busy_on_runner(
    db: Session, runner_id: str, udids: list[str]
) -> bool:
    want = _normalized_udids(udids)
    if not want:
        return False
    rows = list(
        db.scalars(
            select(DeviceRow).where(
                DeviceRow.runner_id == runner_id,
                DeviceRow.udid.in_(want),
            )
        ).all()
    )
    return any(bool(str(getattr(d, "busy_job_id", None) or "").strip()) for d in rows)


def claim_job_wait(runner_id: str, *, wait_sec: int = 0) -> JobOut | None:
    """长轮询领取：短会话反复 ``claim_job``，避免长持请求 Session。

    ``wait_sec=0`` 时等价单次 claim。上限 30s，为心跳（90s）留余量。
    """
    sec = max(0, min(30, int(wait_sec or 0)))
    factory = session_factory()
    if factory is None:
        return None

    def _once() -> JobOut | None:
        db = factory()
        try:
            return claim_job(db, runner_id)
        finally:
            db.close()

    if sec <= 0:
        return _once()

    deadline = time.monotonic() + sec
    interval = 0.5
    while True:
        job = _once()
        if job is not None:
            return job
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        time.sleep(min(interval, remaining))


def claim_job(db: Session, runner_id: str) -> JobOut | None:
    runner = db_get(db, RunnerRow, runner_id)
    if runner is None or not is_online(runner.last_heartbeat_at):
        raise PermissionError(msg.JOB_RUNNER_OFFLINE)

    scope_org = (getattr(runner, "org_id", None) or "").strip()
    scope_projects = tuple(getattr(runner, "project_ids", None) or ())

    q = (
        select(JobRow)
        .where(JobRow.status == JobStatus.PENDING.value)
        .order_by(JobRow.created_at.asc())
    )
    candidates = list(db.scalars(q).all())
    now = utcnow()
    for job in candidates:
        pref = (job.preferred_runner_id or "").strip()
        if pref and pref != runner_id:
            continue

        # Runner Token / 节点作用域：越权项目的任务直接跳过（不领取）
        if not runner_scope_allows_project(
            db,
            org_id=scope_org,
            project_ids=scope_projects,
            job_project_id=str(job.project_id or ""),
        ):
            continue

        job_plat = str(job.platform or "").strip().lower()
        runner_caps = {str(c).strip().lower() for c in (runner.capabilities or [])}
        udids = list(job.device_udids or [])
        if not runner_allowed_for_job(
            db,
            runner_id,
            str(job.project_id or ""),
            device_udids=udids,
            is_deviceless=is_deviceless_platform(job_plat),
            job_username=str(job.created_by or ""),
        ):
            continue

        if is_deviceless_platform(job_plat):
            # web / http：按 Runner 能力路由，不绑移动设备
            if job_plat not in runner_caps:
                continue
            if is_web_platform(job_plat):
                job_eng = str(getattr(job, "web_engine", None) or "selenium").strip().lower()
                if job_eng == "playwright" and "web-playwright" not in runner_caps:
                    continue
        else:
            # 移动：Runner 若声明了能力集，须包含该平台（堵纯 web Runner 误抢移动任务）
            if job_plat and runner_caps and job_plat not in runner_caps:
                continue
            # 有指定设备时：必须全在本 Runner、可调度且后端匹配（防止错节点领取）
            if udids:
                if not devices_ready_on_runner(
                    db,
                    runner_id,
                    udids,
                    platform=job_plat,
                    backend_mode=str(job.backend_mode or "auto"),
                    project_id=str(job.project_id or ""),
                    job_username=str(job.created_by or ""),
                ):
                    continue
            elif list(
                db.scalars(select(DeviceRow).where(DeviceRow.runner_id == runner_id)).all()
            ) and not runner_has_schedulable_device(
                db,
                runner_id,
                platform=job_plat,
                backend_mode=str(job.backend_mode or "auto"),
                project_id=str(job.project_id or ""),
                job_username=str(job.created_by or ""),
            ):
                # 无指定 UDID 但本机已上报设备：须至少一台匹配平台/后端的可调度设备
                continue

        # 任务池：本 Runner 已有 host-exclusive（web/无 UDID）占用时跳过，留 pending
        if _is_host_exclusive(job) and _runner_has_host_exclusive_job(db, runner_id):
            continue
        # 设备已占用：跳过本条试下一条，避免先 claim 再 rollback
        if udids and _requested_udids_busy_on_runner(db, runner_id, udids):
            continue

        # E2：depends_on 门禁（未就绪则跳过；前置失败则本任务失败）
        dep_ids = list(getattr(job, "depends_on", None) or [])
        if dep_ids:
            gate, reason = _deps_claim_gate(db, dep_ids)
            if gate == "waiting":
                continue
            if gate == "blocked":
                blocked = db_get(db, JobRow, job.id)
                if blocked is not None and blocked.status == JobStatus.PENDING.value:
                    blocked.status = JobStatus.FAILED.value
                    blocked.error = reason or msg.JOB_DEPENDENCY_FAILED.format(
                        job_id=dep_ids[0], status=JobStatus.FAILED.value
                    )
                    blocked.updated_at = now
                    _fail_pending_dependents(db, blocked.id)
                    db.commit()
                continue

        # 条件更新：仅当仍为 pending 时抢占，避免 TOCTOU 双 claim
        result = db.execute(
            update(JobRow)
            .where(
                JobRow.id == job.id,
                JobRow.status == JobStatus.PENDING.value,
            )
            .values(
                status=JobStatus.CLAIMED.value,
                runner_id=runner_id,
                claimed_at=now,
                updated_at=now,
            )
        )
        if int(getattr(result, "rowcount", 0) or 0) != 1:
            continue
        # 重新加载并占用设备（仍在同一事务意图下；失败则回退 pending）
        chosen = db_get(db, JobRow, job.id)
        if chosen is None or chosen.status != JobStatus.CLAIMED.value:
            db.rollback()
            continue
        try:
            occupy_devices(
                db,
                runner_id,
                list(chosen.device_udids or []),
                chosen.id,
                project_id=str(chosen.project_id or ""),
                job_username=str(chosen.created_by or ""),
            )
            db.commit()
            db.refresh(chosen)
            return job_to_out(chosen)
        except _CLAIM_ROLLBACK_ERRS:
            db.rollback()
            # 尽力把误抢的任务放回 pending
            row = db_get(db, JobRow, job.id)
            if row is not None and row.status == JobStatus.CLAIMED.value and row.runner_id == runner_id:
                row.status = JobStatus.PENDING.value
                row.runner_id = None
                row.claimed_at = None
                row.updated_at = utcnow()
                clear_device_busy(db, job.id)
                db.commit()
            continue
    return None


def mark_job_running(db: Session, job_id: str, runner_id: str) -> JobOut:
    row = db_get(db, JobRow, job_id)
    if row is None:
        raise LookupError(msg.JOB_NOT_FOUND)
    if row.runner_id != runner_id:
        raise PermissionError(msg.JOB_NOT_CLAIMED_BY_RUNNER)
    if row.status == JobStatus.CANCELLED.value:
        raise ValueError(msg.JOB_CANCELLED)
    if row.status not in (JobStatus.CLAIMED.value, JobStatus.RUNNING.value):
        raise ValueError(msg.JOB_INVALID_STATUS_TRANSITION.format(status=row.status))
    row.status = JobStatus.RUNNING.value
    row.updated_at = utcnow()
    db.commit()
    db.refresh(row)
    return job_to_out(row)


def nack_job(
    db: Session, job_id: str, runner_id: str, *, reason: str = ""
) -> JobOut:
    """槽位冲突等资源暂不可用：CLAIMED → pending，清设备占用。不是业务失败。"""
    row = db_get(db, JobRow, job_id)
    if row is None:
        raise LookupError(msg.JOB_NOT_FOUND)
    if row.runner_id != runner_id:
        raise PermissionError(msg.JOB_NOT_CLAIMED_BY_RUNNER)
    if row.status == JobStatus.CANCELLED.value:
        raise ValueError(msg.JOB_CANCELLED)
    if row.status != JobStatus.CLAIMED.value:
        raise ValueError(msg.JOB_INVALID_STATUS_TRANSITION.format(status=row.status))
    row.status = JobStatus.PENDING.value
    row.runner_id = None
    row.claimed_at = None
    row.updated_at = utcnow()
    clear_device_busy(db, job_id)
    db.commit()
    db.refresh(row)
    note = (reason or "").strip()
    if note:
        try:
            append_job_log(job_id, f"[runner] nack: {note}\n")
        except _BEST_EFFORT_ERRS:
            pass
    return job_to_out(row)


def complete_job(db: Session, job_id: str, runner_id: str, body: JobResultIn) -> JobOut:
    row = db_get(db, JobRow, job_id)
    if row is None:
        raise LookupError(msg.JOB_NOT_FOUND)
    if row.runner_id != runner_id:
        raise PermissionError(msg.JOB_NOT_CLAIMED_BY_RUNNER)
    if row.status == JobStatus.CANCELLED.value:
        # 已取消：仍允许 Runner 回传结果，但保持 cancelled，并释放设备
        clear_device_busy(db, job_id)
        row.updated_at = utcnow()
        if body.error:
            row.error = (row.error or "") + f"; runner: {body.error}"
        db.commit()
        db.refresh(row)
        if (body.log or "").strip():
            try:
                append_job_log(job_id, body.log or "", replace=True)
            except _BEST_EFFORT_ERRS:
                pass
        return job_to_out(row)
    # reclaim / 其它终态：不再被 late complete 覆盖为 succeeded
    if row.status not in (JobStatus.CLAIMED.value, JobStatus.RUNNING.value):
        clear_device_busy(db, job_id)
        row.updated_at = utcnow()
        if body.error:
            row.error = (row.error or "") + f"; late-complete: {body.error}"
        db.commit()
        db.refresh(row)
        if (body.log or "").strip():
            try:
                append_job_log(job_id, body.log or "", replace=True)
            except _BEST_EFFORT_ERRS:
                pass
        return job_to_out(row)
    if body.status not in (JobStatus.SUCCEEDED, JobStatus.FAILED):
        raise ValueError(msg.JOB_INVALID_RESULT_STATUS)

    status_val = str(body.status.value)
    row.status = status_val
    row.error = body.error or ""
    row.updated_at = utcnow()
    clear_device_busy(db, job_id)

    report_payload = None
    if body.report is not None:
        rep = row.report
        if rep is None:
            rep = ReportRow(id=new_id(), job_id=row.id)
            db.add(rep)
            row.report = rep
        rep.report_path = body.report.report_path or ""
        rep.passed = int(body.report.passed or 0)
        rep.failed = int(body.report.failed or 0)
        rep.total = int(body.report.total or 0)
        rep.duration_ms = int(body.report.duration_ms or 0)
        rep.summary = body.report.summary or ""
        apply_version_snapshot(db, rep, row)
        report_payload = body.report.model_dump()

    if body.status == JobStatus.FAILED:
        _fail_pending_dependents(db, row.id)
    db.commit()
    db.refresh(row)
    if (body.log or "").strip():
        try:
            append_job_log(job_id, body.log or "", replace=True)
        except _BEST_EFFORT_ERRS:
            pass
    out = job_to_out(row)
    event = "job.succeeded" if body.status == JobStatus.SUCCEEDED else "job.failed"
    _fire_job_webhook(event, out, row, report=report_payload)
    try:
        note_job_terminal(status_val)
    except _BEST_EFFORT_ERRS:
        pass
    if body.status == JobStatus.FAILED:
        try:
            # 延迟：可选告警通道（SMTP/webhook），失败任务才触发
            from ....ops.notify import notify_alert

            if alert_on_failed():
                notify_alert(
                    "job.failed",
                    summary=f"任务失败: {out.name or out.id}",
                    detail={"job": out.model_dump(mode="json"), "report": report_payload},
                )
        except _BEST_EFFORT_ERRS:
            pass
    try:
        # 延迟：schedules.crud → jobs.creation → lifecycle 成环
        from ..schedules.callbacks import on_job_finished

        on_job_finished(
            db, row.id, passed=(body.status == JobStatus.SUCCEEDED)
        )
    except _BEST_EFFORT_ERRS:
        pass
    return out


def cancel_job(db: Session, job_id: str) -> JobOut:
    row = db_get(db, JobRow, job_id)
    if row is None:
        raise LookupError(msg.JOB_NOT_FOUND)
    if row.status in (
        JobStatus.SUCCEEDED.value,
        JobStatus.FAILED.value,
        JobStatus.CANCELLED.value,
    ):
        raise ValueError(msg.JOB_CANNOT_CANCEL_STATUS.format(status=row.status))
    row.status = JobStatus.CANCELLED.value
    row.error = (row.error or "") or "cancelled by user"
    row.updated_at = utcnow()
    # claimed/running 的设备占用保留到 Runner complete ACK，避免旧进程尚未退出时
    # 同一物理设备被新任务并发领取。pending 任务本身没有设备占用。
    _fail_pending_dependents(db, row.id)
    db.commit()
    db.refresh(row)
    out = job_to_out(row)
    _fire_job_webhook("job.cancelled", out, row)
    try:
        note_job_terminal(JobStatus.CANCELLED.value)
    except _BEST_EFFORT_ERRS:
        pass
    try:
        # 延迟：schedules.crud → jobs.creation → lifecycle 成环
        from ..schedules.callbacks import on_job_finished

        on_job_finished(db, row.id, passed=False)
    except _BEST_EFFORT_ERRS:
        pass
    return out


def retry_job(db: Session, job_id: str, auth=None) -> JobOut:
    """从终态任务克隆新 pending 任务（同制品/设备等）。"""
    row = db_get(db, JobRow, job_id)
    if row is None:
        raise LookupError(msg.JOB_NOT_FOUND)
    if row.status not in (
        JobStatus.SUCCEEDED.value,
        JobStatus.FAILED.value,
        JobStatus.CANCELLED.value,
    ):
        raise ValueError(msg.JOB_CANNOT_RETRY_STATUS.format(status=row.status))
    if auth is not None:
        assert_can_access_resource(
            db,
            auth,
            resource_type="job",
            resource_id=row.id,
            project_id=row.project_id or "",
            owner_username=row.created_by or "",
            need_write=True,
        )
    body = JobCreate(
        name=row.name or "Suite",
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
        depends_on=list(getattr(row, "depends_on", None) or []),
    )
    # create_job 会再校验 artifact；这里直接落库以保留 parent
    out = create_job(db, body, auth=auth)
    child = db_get(db, JobRow, out.id)
    if child is not None:
        child.parent_job_id = row.id
        db.commit()
        db.refresh(child)
        return job_to_out(child)
    return out


def _fire_job_webhook(
    event: str,
    out: JobOut,
    row: JobRow,
    *,
    report: dict | None = None,
) -> None:
    # 延迟：可选通知通道，避免生命周期模块急切拉 SMTP/webhook
    from ....ops.notify import notify_job_event

    notify_job_event(
        event,
        out.model_dump(mode="json"),
        report=report,
        override_url=row.webhook_url or "",
    )


def _job_log_path(job_id: str):
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in (job_id or ""))[:80]
    if not safe:
        raise ValueError(msg.JOB_INVALID_ID)
    return job_logs_root() / f"{safe}.log"


def append_job_log(job_id: str, text: str, *, replace: bool = False, max_bytes: int = 2_000_000) -> dict:
    """写入任务日志文件；超长截断尾部保留。"""
    raw = text if isinstance(text, str) else str(text)
    if not raw and not replace:
        return {"job_id": job_id, "bytes": 0, "stored": False}
    path = _job_log_path(job_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = raw.encode("utf-8", errors="replace")
    if replace:
        if len(data) > max_bytes:
            data = data[-max_bytes:]
        path.write_bytes(data)
    else:
        existing = path.read_bytes() if path.is_file() else b""
        merged = existing + data
        if len(merged) > max_bytes:
            merged = merged[-max_bytes:]
        path.write_bytes(merged)
    return {"job_id": job_id, "bytes": path.stat().st_size, "stored": True}


def read_job_log(job_id: str, *, tail: int = 0) -> tuple[str, dict]:
    """返回 (text, meta)。tail>0 时只返回末尾 N 字节。"""
    path = _job_log_path(job_id)
    if not path.is_file():
        raise FileNotFoundError("job log not found")
    data = path.read_bytes()
    meta = {"job_id": job_id, "bytes": len(data), "path": str(path)}
    if 0 < tail < len(data):
        data = data[-tail:]
        meta["tailed"] = True
    return data.decode("utf-8", errors="replace"), meta


def job_log_exists(job_id: str) -> bool:
    try:
        return _job_log_path(job_id).is_file()
    except ValueError:
        return False


_TERMINAL_JOB_STATUSES = frozenset(
    {
        JobStatus.SUCCEEDED.value,
        JobStatus.FAILED.value,
        JobStatus.CANCELLED.value,
    }
)


def read_job_log_since(job_id: str, offset: int) -> tuple[str, int]:
    """从字节 offset 起读新增日志；返回 (text, new_offset)。文件不存在则 ("", offset)。"""
    path = _job_log_path(job_id)
    if not path.is_file():
        return "", max(0, int(offset or 0))
    size = path.stat().st_size
    pos = max(0, int(offset or 0))
    if pos > size:
        # 日志被 replace/截断后从头读
        pos = 0
    if pos >= size:
        return "", pos
    with path.open("rb") as f:
        f.seek(pos)
        data = f.read()
    return data.decode("utf-8", errors="replace"), pos + len(data)


def purge_job_logs(
    db: Session,
    *,
    older_than_days: int | None = None,
) -> tuple[int, int]:
    """删除早于 N 天的终态 Job 日志文件；不删 JobRow。返回 (deleted, days_used)。"""
    days = (
        job_log_retention_days()
        if older_than_days is None
        else max(0, int(older_than_days))
    )
    if days <= 0:
        return 0, days
    cutoff = utcnow() - timedelta(days=days)
    rows = list(
        db.scalars(
            select(JobRow).where(
                JobRow.status.in_(tuple(_TERMINAL_JOB_STATUSES)),
                JobRow.updated_at < cutoff,
            )
        ).all()
    )
    deleted = 0
    for row in rows:
        try:
            path = _job_log_path(row.id)
        except ValueError:
            continue
        if path.is_file():
            path.unlink(missing_ok=True)
            deleted += 1
    return deleted, days


def job_is_terminal(job_id: str) -> bool:
    """短生命周期会话查询任务是否已终态（供 SSE 轮询，避免长持请求 Session）。"""
    factory = session_factory()
    if factory is None:
        return False
    db = factory()
    try:
        row = db_get(db, JobRow, job_id)
        if row is None:
            return True
        return (row.status or "") in _TERMINAL_JOB_STATUSES
    finally:
        db.close()


def reclaim_stale_jobs(db: Session, *, older_than_sec: int | None = None) -> list[str]:
    """将超时的 claimed/running 标为 failed 并释放设备；返回 job_id 列表。

    若绑定 Runner 仍在线：仅刷新 updated_at（长任务靠执行期心跳续命），不误杀。
    条件 UPDATE 领取，避免多实例重复回收与重复告警。
    """
    sec = job_stale_sec() if older_than_sec is None else max(0, int(older_than_sec))
    if sec <= 0:
        return []
    cutoff = utcnow() - timedelta(seconds=sec)
    rows = list(
        db.scalars(
            select(JobRow).where(
                JobRow.status.in_([JobStatus.CLAIMED.value, JobStatus.RUNNING.value]),
                JobRow.updated_at < cutoff,
            )
        ).all()
    )
    ids: list[str] = []
    touched = False
    now = utcnow()
    for row in rows:
        rid = (row.runner_id or "").strip()
        if rid:
            runner = db_get(db, RunnerRow, rid)
            if runner is not None and is_online(runner.last_heartbeat_at):
                row.updated_at = now
                touched = True
                continue
        err = (row.error or "") or f"reclaimed: stale >{sec}s"
        result = db.execute(
            update(JobRow)
            .where(
                JobRow.id == row.id,
                JobRow.status.in_(
                    [JobStatus.CLAIMED.value, JobStatus.RUNNING.value]
                ),
                JobRow.updated_at < cutoff,
            )
            .values(
                status=JobStatus.FAILED.value,
                error=err,
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
        )
        if int(getattr(result, "rowcount", 0) or 0) != 1:
            continue
        clear_device_busy(db, row.id)
        ids.append(row.id)
    if ids or touched:
        db.commit()
    if ids:
        try:
            note_stale_reclaimed(len(ids))
        except _BEST_EFFORT_ERRS:
            pass
        try:
            # 延迟：可选告警通道（SMTP/webhook），过期回收才触发
            from ....ops.notify import notify_alert

            if alert_on_stale():
                notify_alert(
                    "jobs.stale_reclaimed",
                    summary=f"回收僵死任务 {len(ids)} 个",
                    detail={"job_ids": ids, "older_than_sec": sec},
                )
        except _BEST_EFFORT_ERRS:
            pass
    # 顺带回收终态/缺失 Job 留下的孤儿占用（与心跳保 busy 正交）
    try:
        reconcile_orphan_device_busy(db)
    except _BEST_EFFORT_ERRS:
        pass
    return ids
