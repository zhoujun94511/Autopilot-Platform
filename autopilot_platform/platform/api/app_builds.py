"""应用资源（apk/ipa）HTTP API。"""

from __future__ import annotations

from ..core import api_messages as msg

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from autopilot_platform.core.schemas import AppBuildListPage, AppBuildOut, AppBuildPurgeOut, AppBuildUpdate

from ..authz import acl as acl_svc
from ..artifacts import app_builds as ab
from ..ops import audit as audit_svc
from ..artifacts.app_build_storage import get_app_build_store
from ..auth import AuthContext, require_auth, require_admin
from ..core.db import get_session
from ..core.list_page import normalize_page_params
from ..core.settings import app_build_max_mb
from ..artifacts.upload_stream import UploadTooLarge, spool_upload

router = APIRouter(tags=["app-builds"])


@router.post("/app-builds", response_model=AppBuildOut)
async def api_upload_app_build(
    file: UploadFile = File(...),
    name: str = Form(""),
    project_id: str = Form(""),
    platform: str = Form(""),
    version_name: str = Form(""),
    version_code: int = Form(0),
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> AppBuildOut:
    max_mb = app_build_max_mb()
    try:
        temp_path, _ = await spool_upload(
            file, max_bytes=max_mb * 1024 * 1024 if max_mb > 0 else 0
        )
    except UploadTooLarge as exc:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    try:
        out = ab.save_app_build_file(
            db,
            upload_name=file.filename or "app.bin",
            source_path=temp_path,
            display_name=name,
            platform=platform,
            version_name=version_name,
            version_code=int(version_code or 0),
            uploaded_by=auth.username,
            project_id=project_id,
            auth=auth,
        )
        audit_svc.write_audit_auth(
            db,
            auth,
            action="app_build.reuse" if out.reused else "app_build.upload",
            resource_type="app_build",
            resource_id=out.id,
            detail=out.name,
        )
        return out
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    finally:
        temp_path.unlink(missing_ok=True)


@router.get("/app-builds", response_model=AppBuildListPage)
def api_list_app_builds(
    page: int | None = Query(None, ge=1),
    page_size: int | None = Query(None, ge=1, le=200),
    limit: int | None = Query(None, ge=1, le=200),
    offset: int | None = Query(None, ge=0),
    project_id: str = Query(""),
    platform: str = Query(""),
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> AppBuildListPage:

    try:
        pg, size = normalize_page_params(
            page=page, page_size=page_size, limit=limit, offset=offset, default_size=50
        )
        items, total = ab.list_app_builds(
            db,
            page=pg,
            page_size=size,
            project_id=project_id,
            platform=platform,
            auth=auth,
        )
        return AppBuildListPage(items=items, total=total, page=pg, page_size=size)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@router.get("/app-builds/{build_id}", response_model=AppBuildOut)
def api_get_app_build(
    build_id: str,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> AppBuildOut:
    row = ab.get_app_build(db, build_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=msg.APP_BUILD_NOT_FOUND)
    try:
        acl_svc.assert_can_access_resource(
            db,
            auth,
            resource_type="app_build",
            resource_id=row.id,
            project_id=row.project_id or "",
            owner_username=row.uploaded_by or "",
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return ab.app_build_to_out(row)


@router.patch("/app-builds/{build_id}", response_model=AppBuildOut)
def api_patch_app_build(
    build_id: str,
    body: AppBuildUpdate,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> AppBuildOut:
    try:
        out = ab.update_app_build(db, build_id, body, auth=auth)
        audit_svc.write_audit_auth(
            db,
            auth,
            action="app_build.update",
            resource_type="app_build",
            resource_id=build_id,
            detail=out.name,
        )
        return out
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/app-builds/{build_id}/download")
def api_download_app_build(
    build_id: str,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> FileResponse:
    row = ab.get_app_build(db, build_id)
    if row is None or not row.stored_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=msg.APP_BUILD_NOT_FOUND)
    try:
        acl_svc.assert_can_access_resource(
            db,
            auth,
            resource_type="app_build",
            resource_id=row.id,
            project_id=row.project_id or "",
            owner_username=row.uploaded_by or "",
        )
        path = get_app_build_store().resolve_path(row.stored_path)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    media = "application/octet-stream"
    low = (row.filename or "").lower()
    if low.endswith(".apk"):
        media = "application/vnd.android.package-archive"
    elif low.endswith(".xapk"):
        media = "application/zip"
    elif low.endswith(".ipa"):
        media = "application/octet-stream"
    return FileResponse(path, filename=row.filename or "app.bin", media_type=media)


@router.delete(
    "/app-builds/{build_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
def api_delete_app_build(
    build_id: str,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> None:
    try:
        ab.delete_app_build(db, build_id, auth=auth)
        audit_svc.write_audit_auth(
            db,
            auth,
            action="app_build.delete",
            resource_type="app_build",
            resource_id=build_id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/app-builds/purge", response_model=AppBuildPurgeOut)
def api_purge_app_builds(
    older_than_days: int | None = Query(
        None, ge=1, le=3650, description="缺省用 MC_APP_BUILD_RETENTION_DAYS"
    ),
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_admin),
) -> AppBuildPurgeOut:
    deleted, days = ab.purge_app_builds(db, older_than_days=older_than_days)
    audit_svc.write_audit_auth(
        db,
        auth,
        action="app_build.purge",
        detail=f"deleted={deleted} days={days}",
    )
    return AppBuildPurgeOut(deleted=deleted, older_than_days=days)
