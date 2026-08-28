"""资源池 CRUD、成员与项目授权 API。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from autopilot_platform.core.schemas import (
    ResourcePoolCreate,
    ResourcePoolListPage,
    ResourcePoolMemberIn,
    ResourcePoolOut,
    ResourcePoolProjectIn,
    ResourcePoolUpdate,
)

from ..ops import audit as audit_svc
from ..auth import AuthContext, require_auth
from ..core.db import get_session
from ..core.list_page import normalize_page_params
from ..core.models import DeviceRow, ProjectRow, ResourcePoolRow, RunnerRow, db_get
from ..services.execution.resources import pools

router = APIRouter(tags=["resource-pools"])


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, LookupError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


def _audit(
    db: Session,
    auth: AuthContext,
    *,
    action: str,
    pool_id: str,
    org_id: str,
    detail: str = "",
) -> None:
    audit_svc.write_audit(
        db,
        action=action,
        actor=auth.username or "",
        actor_kind=auth.kind or "",
        resource_type="resource_pool",
        resource_id=pool_id,
        org_id=org_id,
        detail=detail,
    )


@router.get("/orgs/{org_id}/resource-pools", response_model=ResourcePoolListPage)
def api_list_resource_pools(
    org_id: str,
    project_id: str = Query(""),
    page: int | None = Query(None, ge=1),
    page_size: int | None = Query(None, ge=1, le=200),
    limit: int | None = Query(None, ge=1, le=200),
    offset: int | None = Query(None, ge=0),
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> ResourcePoolListPage:

    try:
        pg, size = normalize_page_params(
            page=page, page_size=page_size, limit=limit, offset=offset, default_size=50
        )
        items, total = pools.list_resource_pools(
            db, org_id, auth, project_id=project_id, page=pg, page_size=size
        )
        return ResourcePoolListPage(items=items, total=total, page=pg, page_size=size)
    except (PermissionError, LookupError, ValueError) as exc:
        raise _error(exc) from exc


@router.get("/orgs/{org_id}/resource-pools/candidates")
def api_resource_pool_candidates(
    org_id: str,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> dict:
    """管理弹窗候选项；仅组织 owner/admin 或 platform admin。"""
    try:
        if not pools.can_manage_org_resources(db, auth, org_id):
            raise PermissionError("仅组织所有者或管理员可查看资源池候选资源")
        runners = list(
            db.scalars(
                select(RunnerRow)
                .where(RunnerRow.org_id == org_id)
                .order_by(RunnerRow.runner_id)
            ).all()
        )
        runner_ids = {row.runner_id for row in runners}
        devices = (
            list(
                db.scalars(
                    select(DeviceRow)
                    .where(DeviceRow.runner_id.in_(runner_ids))
                    .order_by(DeviceRow.udid)
                ).all()
            )
            if runner_ids
            else []
        )
        projects = list(
            db.scalars(
                select(ProjectRow)
                .where(ProjectRow.org_id == org_id)
                .order_by(ProjectRow.name, ProjectRow.id)
            ).all()
        )
        return {
            "runners": [
                {
                    "runner_id": row.runner_id,
                    "hostname": row.hostname or "",
                    "online": bool(row.last_heartbeat_at),
                }
                for row in runners
            ],
            "devices": [
                {
                    "id": row.id,
                    "udid": row.udid,
                    "name": row.name or row.model or "",
                    "platform": row.platform or "",
                    "runner_id": row.runner_id,
                    "busy": bool(row.busy_job_id),
                }
                for row in devices
            ],
            "projects": [
                {"id": row.id, "name": row.name or row.id} for row in projects
            ],
        }
    except (PermissionError, LookupError, ValueError) as exc:
        raise _error(exc) from exc


@router.post(
    "/orgs/{org_id}/resource-pools",
    response_model=ResourcePoolOut,
    status_code=status.HTTP_201_CREATED,
)
def api_create_resource_pool(
    org_id: str,
    body: ResourcePoolCreate,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> ResourcePoolOut:
    try:
        out = pools.create_resource_pool(db, org_id, body, auth)
        _audit(
            db,
            auth,
            action="resource_pool.create",
            pool_id=out.id,
            org_id=out.org_id,
            detail=out.name,
        )
        return out
    except (PermissionError, LookupError, ValueError) as exc:
        raise _error(exc) from exc


@router.get("/resource-pools/{pool_id}", response_model=ResourcePoolOut)
def api_get_resource_pool(
    pool_id: str,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> ResourcePoolOut:

    row = db_get(db, ResourcePoolRow, pool_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="资源池不存在")
    try:
        visible, _ = pools.list_resource_pools(db, row.org_id, auth, page=1, page_size=500)
        hit = next((item for item in visible if item.id == pool_id), None)
        if hit is None:
            raise PermissionError("无权查看该资源池")
        return hit
    except (PermissionError, LookupError, ValueError) as exc:
        raise _error(exc) from exc


@router.patch("/resource-pools/{pool_id}", response_model=ResourcePoolOut)
def api_update_resource_pool(
    pool_id: str,
    body: ResourcePoolUpdate,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> ResourcePoolOut:
    try:
        out = pools.update_resource_pool(db, pool_id, body, auth)
        _audit(
            db,
            auth,
            action="resource_pool.update",
            pool_id=out.id,
            org_id=out.org_id,
            detail=out.name,
        )
        return out
    except (PermissionError, LookupError, ValueError) as exc:
        raise _error(exc) from exc


@router.delete("/resource-pools/{pool_id}")
def api_delete_resource_pool(
    pool_id: str,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> dict:

    row = db_get(db, ResourcePoolRow, pool_id)
    org_id = row.org_id if row is not None else ""
    try:
        pools.delete_resource_pool(db, pool_id, auth)
        _audit(
            db,
            auth,
            action="resource_pool.delete",
            pool_id=pool_id,
            org_id=org_id,
        )
        return {"deleted": True, "id": pool_id}
    except (PermissionError, LookupError, ValueError) as exc:
        raise _error(exc) from exc


def _member_change(
    db: Session,
    auth: AuthContext,
    pool_id: str,
    kind: str,
    resource_id: str,
    *,
    remove: bool,
) -> ResourcePoolOut:
    if kind == "runner":
        out = (
            pools.remove_runner(db, pool_id, resource_id, auth)
            if remove
            else pools.add_runner(db, pool_id, resource_id, auth)
        )
    else:
        out = (
            pools.remove_device(db, pool_id, resource_id, auth)
            if remove
            else pools.add_device(db, pool_id, resource_id, auth)
        )
    _audit(
        db,
        auth,
        action=f"resource_pool.{kind}_{'remove' if remove else 'add'}",
        pool_id=out.id,
        org_id=out.org_id,
        detail=resource_id,
    )
    return out


@router.post("/resource-pools/{pool_id}/runners", response_model=ResourcePoolOut)
def api_add_pool_runner(
    pool_id: str,
    body: ResourcePoolMemberIn,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> ResourcePoolOut:
    try:
        return _member_change(
            db, auth, pool_id, "runner", body.resource_id, remove=False
        )
    except (PermissionError, LookupError, ValueError) as exc:
        raise _error(exc) from exc


@router.delete(
    "/resource-pools/{pool_id}/runners/{runner_id}", response_model=ResourcePoolOut
)
def api_remove_pool_runner(
    pool_id: str,
    runner_id: str,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> ResourcePoolOut:
    try:
        return _member_change(db, auth, pool_id, "runner", runner_id, remove=True)
    except (PermissionError, LookupError, ValueError) as exc:
        raise _error(exc) from exc


@router.post("/resource-pools/{pool_id}/devices", response_model=ResourcePoolOut)
def api_add_pool_device(
    pool_id: str,
    body: ResourcePoolMemberIn,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> ResourcePoolOut:
    try:
        return _member_change(
            db, auth, pool_id, "device", body.resource_id, remove=False
        )
    except (PermissionError, LookupError, ValueError) as exc:
        raise _error(exc) from exc


@router.delete(
    "/resource-pools/{pool_id}/devices/{device_id}", response_model=ResourcePoolOut
)
def api_remove_pool_device(
    pool_id: str,
    device_id: str,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> ResourcePoolOut:
    try:
        return _member_change(db, auth, pool_id, "device", device_id, remove=True)
    except (PermissionError, LookupError, ValueError) as exc:
        raise _error(exc) from exc


@router.post("/resource-pools/{pool_id}/projects", response_model=ResourcePoolOut)
def api_grant_pool_project(
    pool_id: str,
    body: ResourcePoolProjectIn,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> ResourcePoolOut:
    try:
        out = pools.grant_project(db, pool_id, body.project_id, auth)
        _audit(
            db,
            auth,
            action="resource_pool.project_grant",
            pool_id=out.id,
            org_id=out.org_id,
            detail=body.project_id,
        )
        return out
    except (PermissionError, LookupError, ValueError) as exc:
        raise _error(exc) from exc


@router.delete(
    "/resource-pools/{pool_id}/projects/{project_id}",
    response_model=ResourcePoolOut,
)
def api_revoke_pool_project(
    pool_id: str,
    project_id: str,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> ResourcePoolOut:
    try:
        out = pools.revoke_project(db, pool_id, project_id, auth)
        _audit(
            db,
            auth,
            action="resource_pool.project_revoke",
            pool_id=out.id,
            org_id=out.org_id,
            detail=project_id,
        )
        return out
    except (PermissionError, LookupError, ValueError) as exc:
        raise _error(exc) from exc

