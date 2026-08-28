"""Artifact upload / list / download / purge."""

from __future__ import annotations

from ..core import api_messages as msg

# noinspection PyPackageRequirements
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
# noinspection PyPackageRequirements
from fastapi.responses import FileResponse
# noinspection PyPackageRequirements
from sqlalchemy.orm import Session

from autopilot_platform.core.schemas import ArtifactEntryOut, ArtifactListPage, ArtifactOut, ArtifactPurgeOut

from ..auth import AuthContext, require_admin, require_auth
from ..core.db import get_session
from ..core.list_page import normalize_page_params
from ..core.settings import artifact_max_mb
from ..authz import acl as acl_svc
from ..ops import audit as audit_svc
from ..artifacts import users_artifacts as ua
from ..artifacts.storage import get_artifact_store
from ..artifacts.upload_stream import UploadTooLarge, spool_upload

router = APIRouter(tags=["artifacts"])


@router.get("/artifacts/{artifact_id}/entries", response_model=list[ArtifactEntryOut])
def api_list_artifact_entries(
    artifact_id: str,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> list[ArtifactEntryOut]:
    """列出制品内可勾选的用例/套件/计划（非整目录树）。"""
    row = ua.get_artifact(db, artifact_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=msg.ARTIFACT_NOT_FOUND)
    try:
        acl_svc.assert_can_access_resource(
            db,
            auth,
            resource_type="artifact",
            resource_id=row.id,
            project_id=row.project_id or "",
            owner_username=row.uploaded_by or "",
        )
        entries = ua.list_artifact_entries(row)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return [ArtifactEntryOut(**e) for e in entries]

@router.post("/artifacts", response_model=ArtifactOut)
async def api_upload_artifact(
    file: UploadFile = File(...),
    name: str = Form(""),
    project_id: str = Form(""),
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> ArtifactOut:
    max_mb = artifact_max_mb()
    try:
        temp_path, _ = await spool_upload(
            file, max_bytes=max_mb * 1024 * 1024 if max_mb > 0 else 0
        )
    except UploadTooLarge as exc:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    try:
        out = ua.save_artifact_zip(
            db,
            upload_name=file.filename or "project.zip",
            source_path=temp_path,
            display_name=name,
            uploaded_by=auth.username,
            project_id=project_id,
            auth=auth,
        )
        audit_svc.write_audit_auth(
            db,
            auth,
            action="artifact.upload",
            resource_type="artifact",
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


@router.get("/artifacts", response_model=ArtifactListPage)
def api_list_artifacts(
    page: int | None = Query(None, ge=1),
    page_size: int | None = Query(None, ge=1, le=200),
    limit: int | None = Query(None, ge=1, le=200),
    offset: int | None = Query(None, ge=0),
    project_id: str = Query(""),
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> ArtifactListPage:

    try:
        pg, size = normalize_page_params(
            page=page, page_size=page_size, limit=limit, offset=offset, default_size=50
        )
        items, total = ua.list_artifacts(
            db, page=pg, page_size=size, project_id=project_id, auth=auth
        )
        return ArtifactListPage(items=items, total=total, page=pg, page_size=size)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@router.get("/artifacts/{artifact_id}", response_model=ArtifactOut)
def api_get_artifact(
    artifact_id: str,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> ArtifactOut:
    row = ua.get_artifact(db, artifact_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=msg.ARTIFACT_NOT_FOUND)
    try:
        acl_svc.assert_can_access_resource(
            db,
            auth,
            resource_type="artifact",
            resource_id=row.id,
            project_id=row.project_id or "",
            owner_username=row.uploaded_by or "",
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return ua.artifact_to_out(row)


@router.get("/artifacts/{artifact_id}/download")
def api_download_artifact(
    artifact_id: str,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> FileResponse:
    row = ua.get_artifact(db, artifact_id)
    if row is None or not row.stored_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=msg.ARTIFACT_NOT_FOUND)
    try:
        acl_svc.assert_can_access_resource(
            db,
            auth,
            resource_type="artifact",
            resource_id=row.id,
            project_id=row.project_id or "",
            owner_username=row.uploaded_by or "",
        )
        path = get_artifact_store().resolve_zip_path(row.stored_path)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return FileResponse(
        path,
        filename=row.filename or "project.zip",
        media_type="application/zip",
    )


@router.delete(
    "/artifacts/{artifact_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
def api_delete_artifact(
    artifact_id: str,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> None:
    try:
        ua.delete_artifact(db, artifact_id, auth=auth)
        audit_svc.write_audit_auth(
            db, auth, action="artifact.delete", resource_type="artifact", resource_id=artifact_id
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/artifacts/purge", response_model=ArtifactPurgeOut)
def api_purge_artifacts(
    older_than_days: int | None = Query(
        None, ge=1, le=3650, description="缺省用 MC_ARTIFACT_RETENTION_DAYS"
    ),
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_admin),
) -> ArtifactPurgeOut:
    deleted, days = ua.purge_artifacts(db, older_than_days=older_than_days)
    audit_svc.write_audit_auth(
        db,
        auth,
        action="artifact.purge",
        detail=f"deleted={deleted} days={days}",
    )
    return ArtifactPurgeOut(deleted=deleted, older_than_days=days)


