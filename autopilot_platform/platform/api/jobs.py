"""Jobs lifecycle, logs, reports."""

from __future__ import annotations

from ..core import api_messages as msg

import asyncio
import json

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status as http_status
from fastapi.responses import FileResponse, Response, StreamingResponse
from sqlalchemy.orm import Session

from autopilot_platform.core.schemas import (
    JobCreate,
    JobListPage,
    JobOut,
    JobResultIn,
    ReportIndex,
    ReportListPage,
    ReportPurgeOut,
)

from ..auth import (
    AuthContext,
    assert_runner_id_allowed,
    assert_runner_scope_for_job,
    require_admin,
    require_auth,
    require_runner,
    require_stream_auth,
)
from ..core.db import get_session, session_factory
from ..core.list_page import normalize_page_params
from ..core.security import create_stream_token
from ..core.settings import job_report_max_mb, stream_token_minutes
from ..artifacts.upload_stream import UploadTooLarge, spool_upload
from ..authz import acl as acl_svc
from ..ops import audit as audit_svc
from ..services.execution import jobs as jobs_svc
from ..services import reports as reports_svc
from ..services.shared.mappers import job_to_out
from ..core.models import JobRow, db_get

router = APIRouter(tags=["jobs"])

@router.post("/jobs", response_model=JobOut)
def api_create_job(
    body: JobCreate,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> JobOut:
    try:
        out = jobs_svc.create_job(db, body, auth=auth)
        audit_svc.write_audit_auth(
            db, auth, action="job.create", resource_type="job", resource_id=out.id, detail=out.name
        )
        return out
    except LookupError as exc:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/jobs", response_model=JobListPage)
def api_list_jobs(
    page: int | None = Query(None, ge=1),
    page_size: int | None = Query(None, ge=1, le=200),
    limit: int | None = Query(None, ge=1, le=200),
    offset: int | None = Query(None, ge=0),
    project_id: str = Query(""),
    q: str = Query(""),
    job_status: str = Query("", alias="status"),
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> JobListPage:

    try:
        pg, size = normalize_page_params(
            page=page, page_size=page_size, limit=limit, offset=offset, default_size=50
        )
        items, total = jobs_svc.list_jobs(
            db,
            page=pg,
            page_size=size,
            project_id=project_id,
            q=q,
            status=job_status,
            auth=auth,
        )
        return JobListPage(items=items, total=total, page=pg, page_size=size)
    except PermissionError as exc:
        raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@router.get("/jobs/{job_id}", response_model=JobOut)
def api_get_job(
    job_id: str,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> JobOut:
    j = db_get(db, JobRow, job_id)
    if j is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail=msg.JOB_NOT_FOUND)
    try:
        acl_svc.assert_can_access_resource(
            db,
            auth,
            resource_type="job",
            resource_id=job_id,
            project_id=j.project_id or "",
            owner_username=j.created_by or "",
        )
    except PermissionError as exc:
        raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return job_to_out(j)


@router.post("/jobs/claim", response_model=JobOut | None)
def api_claim_job(
    runner_id: str = Query(..., min_length=1),
    wait_sec: int = Query(
        0,
        ge=0,
        le=30,
        description="长轮询秒数；0=立即返回（默认，兼容旧 Runner）",
    ),
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_runner),
) -> JobOut | None:
    """领取任务。``wait_sec>0`` 时服务端短轮询直到有任务或超时（B1-T）。"""
    assert_runner_id_allowed(auth, runner_id)
    try:
        if wait_sec <= 0:
            return jobs_svc.claim_job(db, runner_id)
        # 长等待用短会话循环，不占用本请求 Session 做 DB 扫描
        return jobs_svc.claim_job_wait(runner_id, wait_sec=wait_sec)
    except PermissionError as exc:
        raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@router.post("/jobs/reclaim", response_model=list[str])
def api_reclaim_stale_jobs(
    older_than_sec: int | None = Query(None, ge=1, le=86400 * 30),
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_admin),
) -> list[str]:
    """回收超时 claimed/running 任务（默认 MC_JOB_STALE_SEC）。"""
    ids = jobs_svc.reclaim_stale_jobs(db, older_than_sec=older_than_sec)
    if ids:
        audit_svc.write_audit_auth(
            db, auth, action="job.reclaim", detail=f"count={len(ids)}"
        )
    return ids


@router.post("/jobs/{job_id}/running", response_model=JobOut)
def api_mark_running(
    job_id: str,
    runner_id: str = Query(..., min_length=1),
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_runner),
) -> JobOut:
    assert_runner_id_allowed(auth, runner_id)
    row = db_get(db, JobRow, job_id)
    if row is not None:
        assert_runner_scope_for_job(db, auth, str(row.project_id or ""))
    try:
        return jobs_svc.mark_job_running(db, job_id, runner_id)
    except LookupError as exc:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=http_status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/jobs/{job_id}/nack", response_model=JobOut)
def api_nack_job(
    job_id: str,
    runner_id: str = Query(..., min_length=1),
    reason: str = Query("", description="退回原因（写入任务日志，不标失败）"),
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_runner),
) -> JobOut:
    """资源暂不可用：将 CLAIMED 任务退回 pending，并释放设备占用。"""
    assert_runner_id_allowed(auth, runner_id)
    row = db_get(db, JobRow, job_id)
    if row is not None:
        assert_runner_scope_for_job(db, auth, str(row.project_id or ""))
    try:
        return jobs_svc.nack_job(db, job_id, runner_id, reason=reason)
    except LookupError as exc:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=http_status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/jobs/{job_id}/complete", response_model=JobOut)
def api_complete(
    job_id: str,
    body: JobResultIn,
    runner_id: str = Query(..., min_length=1),
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_runner),
) -> JobOut:
    assert_runner_id_allowed(auth, runner_id)
    row = db_get(db, JobRow, job_id)
    if row is not None:
        assert_runner_scope_for_job(db, auth, str(row.project_id or ""))
    try:
        return jobs_svc.complete_job(db, job_id, runner_id, body)
    except LookupError as exc:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/jobs/{job_id}/report", response_model=ReportIndex)
async def api_upload_job_report(
    job_id: str,
    file: UploadFile = File(...),
    runner_id: str = Query(""),
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_runner),
) -> ReportIndex:
    temp_path = None
    try:
        j = db_get(db, JobRow, job_id)
        if j is None:
            raise LookupError(msg.JOB_NOT_FOUND)
        rid = (runner_id or "").strip()
        if not rid:
            raise PermissionError(msg.JOB_RUNNER_ID_REQUIRED_REPORT)
        assert_runner_id_allowed(auth, rid)
        assert_runner_scope_for_job(db, auth, str(j.project_id or ""))
        if j.runner_id and j.runner_id != rid:
            raise PermissionError(msg.JOB_NOT_OWNED_BY_RUNNER)
        max_mb = job_report_max_mb()
        temp_path, _ = await spool_upload(
            file, max_bytes=max_mb * 1024 * 1024 if max_mb > 0 else 0
        )
        return reports_svc.store_job_report(
            db,
            job_id,
            source_path=temp_path,
            filename=file.filename or "report.html",
            runner_id=rid,
        )
    except LookupError as exc:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except UploadTooLarge as exc:
        raise HTTPException(status_code=http_status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


@router.get("/jobs/{job_id}/report")
def api_get_job_report(
    job_id: str,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> FileResponse:
    j = db_get(db, JobRow, job_id)
    if j is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail=msg.JOB_NOT_FOUND)
    try:
        acl_svc.assert_can_access_resource(
            db,
            auth,
            resource_type="job",
            resource_id=job_id,
            project_id=j.project_id or "",
            owner_username=j.created_by or "",
        )
        path = reports_svc.resolve_job_report_path(db, job_id)
    except PermissionError as exc:
        raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return FileResponse(path, filename="report.html", media_type="text/html; charset=utf-8")


@router.get("/jobs/{job_id}/result")
def api_get_job_result_json(
    job_id: str,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> FileResponse:
    """返回结构化 result.json（平台解析真源）。"""
    j = db_get(db, JobRow, job_id)
    if j is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail=msg.JOB_NOT_FOUND)
    try:
        acl_svc.assert_can_access_resource(
            db,
            auth,
            resource_type="job",
            resource_id=job_id,
            project_id=j.project_id or "",
            owner_username=j.created_by or "",
        )
        path = reports_svc.resolve_job_result_json_path(db, job_id)
    except PermissionError as exc:
        raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return FileResponse(path, filename="result.json", media_type="application/json")


@router.get("/jobs/{job_id}/evidence")
def api_list_job_evidence(
    job_id: str,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> dict:
    """列举已解压 evidence（含录像 mp4）；无目录时 files=[]。"""
    j = db_get(db, JobRow, job_id)
    if j is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail=msg.JOB_NOT_FOUND)
    try:
        acl_svc.assert_can_access_resource(
            db,
            auth,
            resource_type="job",
            resource_id=job_id,
            project_id=j.project_id or "",
            owner_username=j.created_by or "",
        )
        files = reports_svc.list_job_evidence_files(db, job_id)
    except PermissionError as exc:
        raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return {"job_id": job_id, "files": files}


@router.get("/jobs/{job_id}/evidence/{rel_path:path}")
def api_get_job_evidence_file(
    job_id: str,
    rel_path: str,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> FileResponse:
    """返回已上传的 D3 证据文件（截图/DOM/录像）。"""
    j = db_get(db, JobRow, job_id)
    if j is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail=msg.JOB_NOT_FOUND)
    try:
        acl_svc.assert_can_access_resource(
            db,
            auth,
            resource_type="job",
            resource_id=job_id,
            project_id=j.project_id or "",
            owner_username=j.created_by or "",
        )
        path = reports_svc.resolve_job_evidence_file(db, job_id, rel_path)
    except PermissionError as exc:
        raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    media = "application/octet-stream"
    low = str(path).lower()
    if low.endswith(".png"):
        media = "image/png"
    elif low.endswith((".jpg", ".jpeg")):
        media = "image/jpeg"
    elif low.endswith(".gif"):
        media = "image/gif"
    elif low.endswith(".webp"):
        media = "image/webp"
    elif low.endswith(".mp4"):
        media = "video/mp4"
    elif low.endswith((".xml", ".html", ".htm", ".txt")):
        media = "text/plain; charset=utf-8"
    return FileResponse(path, filename=path.name, media_type=media)


@router.post("/jobs/{job_id}/logs")
async def api_upload_job_logs(
    job_id: str,
    request: Request,
    runner_id: str = Query(""),
    replace: bool = Query(False),
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_runner),
) -> dict:
    """Runner 追加/覆盖任务执行日志（text/plain 或 JSON {\"text\":...}）。"""
    j = db_get(db, JobRow, job_id)
    if j is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail=msg.JOB_NOT_FOUND)
    try:
        rid = runner_id or (j.runner_id or "")
        assert_runner_id_allowed(auth, rid)
        assert_runner_scope_for_job(db, auth, str(j.project_id or ""))
        if runner_id and j.runner_id and j.runner_id != runner_id:
            raise PermissionError(msg.JOB_NOT_OWNED_BY_RUNNER)
        ctype = (request.headers.get("content-type") or "").lower()
        if "application/json" in ctype:
            body = await request.json()
            text = str((body or {}).get("text") or "")
        else:
            raw = await request.body()
            text = raw.decode("utf-8", errors="replace")
        return jobs_svc.append_job_log(job_id, text, replace=replace)
    except PermissionError as exc:
        raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/jobs/{job_id}/logs")
def api_get_job_logs(
    job_id: str,
    tail: int = Query(0, ge=0, le=5_000_000),
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> Response:
    j = db_get(db, JobRow, job_id)
    if j is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail=msg.JOB_NOT_FOUND)
    try:
        if auth.stream_job_id and auth.stream_job_id != job_id:
            raise PermissionError(msg.JOB_STREAM_TOKEN_SCOPED)
        if auth.kind == "user":
            acl_svc.assert_can_access_resource(
                db,
                auth,
                resource_type="job",
                resource_id=job_id,
                project_id=j.project_id or "",
                owner_username=j.created_by or "",
            )
        text, meta = jobs_svc.read_job_log(job_id, tail=tail)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return Response(
        content=text,
        media_type="text/plain; charset=utf-8",
        headers={"X-MC-Log-Bytes": str(meta.get("bytes", 0))},
    )


@router.post("/jobs/{job_id}/logs/stream-token")
def api_create_job_log_stream_token(
    job_id: str,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> dict:
    if auth.kind != "user":
        raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail=msg.AUTH_USER_LOGIN_REQUIRED)
    j = db_get(db, JobRow, job_id)
    if j is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail=msg.JOB_NOT_FOUND)
    try:
        acl_svc.assert_can_access_resource(
            db,
            auth,
            resource_type="job",
            resource_id=job_id,
            project_id=j.project_id or "",
            owner_username=j.created_by or "",
        )
    except PermissionError as exc:
        raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    ttl_min = stream_token_minutes()
    return {
        "access_token": create_stream_token(
            sub=auth.user_id,
            role=auth.role,
            username=auth.username,
            job_id=job_id,
            minutes=ttl_min,
        ),
        "expires_in": ttl_min * 60,
        "token_type": "job_log_stream",
    }


@router.get("/jobs/{job_id}/logs/stream")
async def api_stream_job_logs(
    job_id: str,
    request: Request,
    auth: AuthContext = Depends(require_stream_auth),
    since: int = Query(0, ge=0, description="从该字节偏移起推送，避免与历史 GET 重叠"),
) -> StreamingResponse:
    """任务日志 SSE：约每秒检查文件增量；终态且连续 2 次无新增后结束。

    鉴权用短 Session，流式循环不再占用请求级 ``Depends(get_session)``，
    避免 SQLite 读事务挡住 claim/heartbeat。
    """
    factory = session_factory()
    if factory is None:
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=msg.JOB_NOT_FOUND,
        )
    db = factory()
    try:
        j = db_get(db, JobRow, job_id)
        if j is None:
            raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail=msg.JOB_NOT_FOUND)
        try:
            if auth.stream_job_id != job_id or auth.stream_session_id:
                raise PermissionError(msg.JOB_STREAM_TOKEN_SCOPED)
            if auth.kind == "user":
                acl_svc.assert_can_access_resource(
                    db,
                    auth,
                    resource_type="job",
                    resource_id=job_id,
                    project_id=j.project_id or "",
                    owner_username=j.created_by or "",
                )
        except PermissionError as exc:
            raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    finally:
        db.close()

    start_offset = int(since or 0)

    async def _events():
        offset = start_offset
        idle_no_new = 0
        while True:
            if await request.is_disconnected():
                return
            text, offset = await asyncio.to_thread(jobs_svc.read_job_log_since, job_id, offset)
            if text:
                idle_no_new = 0
                payload = json.dumps({"offset": offset, "text": text}, ensure_ascii=False)
                yield f"data: {payload}\n\n"
            else:
                terminal = await asyncio.to_thread(jobs_svc.job_is_terminal, job_id)
                if terminal:
                    idle_no_new += 1
                    if idle_no_new >= 2:
                        yield "event: end\ndata: {}\n\n"
                        return
                else:
                    idle_no_new = 0
            await asyncio.sleep(1.0)

    return StreamingResponse(
        _events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            # 降低带 ?access_token= 的 SSE URL 经 Referer 外泄的概率
            "Referrer-Policy": "no-referrer",
        },
    )


@router.post("/jobs/{job_id}/cancel", response_model=JobOut)
def api_cancel_job(
    job_id: str,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> JobOut:
    try:
        j = db_get(db, JobRow, job_id)
        if j is None:
            raise LookupError(msg.JOB_NOT_FOUND)
        acl_svc.assert_can_access_resource(
            db,
            auth,
            resource_type="job",
            resource_id=job_id,
            project_id=j.project_id or "",
            owner_username=j.created_by or "",
            need_write=True,
        )
        out = jobs_svc.cancel_job(db, job_id)
        audit_svc.write_audit_auth(
            db, auth, action="job.cancel", resource_type="job", resource_id=job_id
        )
        return out
    except LookupError as exc:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=http_status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/jobs/{job_id}/retry", response_model=JobOut)
def api_retry_job(
    job_id: str,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> JobOut:
    try:
        out = jobs_svc.retry_job(db, job_id, auth=auth)
        audit_svc.write_audit_auth(
            db,
            auth,
            action="job.retry",
            resource_type="job",
            resource_id=out.id,
            detail=f"from={job_id}",
        )
        return out
    except LookupError as exc:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=http_status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/reports/purge", response_model=ReportPurgeOut)
def api_purge_job_reports(
    older_than_days: int | None = Query(
        None, ge=1, le=3650, description="缺省用 MC_JOB_REPORT_RETENTION_DAYS"
    ),
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_admin),
) -> ReportPurgeOut:
    """清理过期终态 Job 的报告目录与索引（不删 Job 本身）。"""
    deleted, days = reports_svc.purge_job_reports(db, older_than_days=older_than_days)
    audit_svc.write_audit_auth(
        db,
        auth,
        action="report.purge",
        detail=f"deleted={deleted} days={days}",
    )
    return ReportPurgeOut(deleted=deleted, older_than_days=days)


@router.get("/reports", response_model=ReportListPage)
def api_list_reports(
    page: int | None = Query(None, ge=1),
    page_size: int | None = Query(None, ge=1, le=200),
    limit: int | None = Query(None, ge=1, le=200),
    offset: int | None = Query(None, ge=0),
    project_id: str = Query(""),
    artifact_id: str = Query(""),
    app_build_id: str = Query(""),
    platform: str = Query(""),
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> ReportListPage:

    try:
        pg, size = normalize_page_params(
            page=page, page_size=page_size, limit=limit, offset=offset, default_size=50
        )
        items, total = reports_svc.list_reports(
            db,
            page=pg,
            page_size=size,
            project_id=project_id,
            artifact_id=artifact_id,
            app_build_id=app_build_id,
            platform=platform,
            auth=auth,
        )
        return ReportListPage(items=items, total=total, page=pg, page_size=size)
    except PermissionError as exc:
        raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@router.get("/reports/compare")
def api_compare_reports(
    left: str = Query(..., min_length=1, description="基准任务 job_id"),
    right: str = Query(..., min_length=1, description="对比任务 job_id"),
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> dict:
    """对比两份任务报告指标（delta = right - left）。"""
    try:
        return reports_svc.compare_reports(db, left, right, auth=auth)
    except LookupError as exc:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
