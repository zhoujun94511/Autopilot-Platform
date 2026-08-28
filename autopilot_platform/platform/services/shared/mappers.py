"""ORM 行到 API DTO 的稳定映射。"""

from __future__ import annotations

from datetime import datetime

from autopilot_platform.core.constants import JobStatus
from autopilot_platform.core.schemas import JobOut, RunnerOut

from ...core.models import AppBuildRow, JobRow, RunnerRow, db_get
from .status import is_online


def app_build_fields(row) -> dict:
    """从关联 AppBuild 回显名称/版本/包名（任务钉死某一安装包版本）。"""
    empty = {
        "app_build_name": "",
        "app_version_name": "",
        "app_version_code": 0,
        "app_package_id": "",
    }
    bid = str(getattr(row, "app_build_id", None) or "").strip()
    if not bid:
        return empty
    from sqlalchemy.orm import object_session

    sess = object_session(row)
    if sess is None:
        return empty
    build = db_get(sess, AppBuildRow, bid)
    if build is None:
        return empty
    return {
        "app_build_name": str(build.name or build.filename or ""),
        "app_version_name": str(build.version_name or ""),
        "app_version_code": int(build.version_code or 0),
        "app_package_id": str(build.package_id or ""),
    }


def runner_to_out(row: RunnerRow, *, now: datetime | None = None) -> RunnerOut:
    return RunnerOut(
        runner_id=row.runner_id,
        hostname=row.hostname or "",
        version=row.version or "",
        capabilities=row.capabilities,
        last_heartbeat_at=row.last_heartbeat_at,
        online=is_online(row.last_heartbeat_at, now=now),
        has_token=bool((row.token_hash or "").strip()),
        org_id=(getattr(row, "org_id", None) or "").strip(),
        project_ids=list(getattr(row, "project_ids", None) or []),
        owner_user_id=(getattr(row, "owner_user_id", None) or "").strip(),
        registration_source=(
            getattr(row, "registration_source", None) or "platform"
        ).strip(),
        device_selection_mode=(
            getattr(row, "device_selection_mode", None) or "all"
        ).strip(),
        selected_device_udids=list(
            getattr(row, "selected_device_udids", None) or []
        ),
        device_policy_revision=int(
            getattr(row, "device_policy_revision", None) or 0
        ),
    )


def job_to_out(row: JobRow) -> JobOut:
    snap = app_build_fields(row)
    return JobOut(
        id=row.id,
        name=row.name,
        status=JobStatus(row.status),
        project_dir=row.project_dir or "",
        artifact_id=row.artifact_id,
        app_build_id=getattr(row, "app_build_id", None),
        app_build_name=snap["app_build_name"],
        app_version_name=snap["app_version_name"],
        app_version_code=int(snap["app_version_code"] or 0),
        app_package_id=snap["app_package_id"],
        project_id=row.project_id or "",
        platform=row.platform,
        device_udids=row.device_udids,
        entry_paths=list(getattr(row, "entry_paths", None) or []),
        parallel=bool(row.parallel),
        parallel_workers=int(row.parallel_workers or 0),
        backend_mode=row.backend_mode or "auto",
        web_engine=getattr(row, "web_engine", None) or "selenium",
        wda_bundle=row.wda_bundle or "",
        preferred_runner_id=row.preferred_runner_id,
        runner_id=row.runner_id,
        error=row.error,
        webhook_url=row.webhook_url or "",
        parent_job_id=row.parent_job_id,
        depends_on=list(getattr(row, "depends_on", None) or []),
        created_by=row.created_by or "",
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
