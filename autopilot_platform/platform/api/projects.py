"""Project CRUD + members."""

from __future__ import annotations

from ..core import api_messages as msg

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from autopilot_platform.core.schemas import (
    ProjectCreate,
    ProjectListPage,
    ProjectMemberIn,
    ProjectMemberListPage,
    ProjectMemberOut,
    ProjectOut,
)

from ..auth import AuthContext, require_auth
from ..core.db import get_session
from ..core.list_page import normalize_page_params
from ..ops import audit as audit_svc
from ..tenancy import projects as proj_svc

router = APIRouter(tags=["projects"])

@router.post("/projects", response_model=ProjectOut)
def api_create_project(
    body: ProjectCreate,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> ProjectOut:
    if auth.kind != "user":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg.AUTH_USER_LOGIN_REQUIRED)
    try:
        out = proj_svc.create_project(db, body, auth)
        audit_svc.write_audit_auth(
            db, auth, action="project.create", resource_type="project", resource_id=out.id
        )
        return out
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/projects", response_model=ProjectListPage)
def api_list_projects(
    org_id: str | None = Query(default=None),
    q: str | None = Query(default=None, description="项目 ID / 名称关键词"),
    page: int | None = Query(None, ge=1),
    page_size: int | None = Query(None, ge=1, le=200),
    limit: int | None = Query(None, ge=1, le=200),
    offset: int | None = Query(None, ge=0),
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> ProjectListPage:

    pg, size = normalize_page_params(
        page=page, page_size=page_size, limit=limit, offset=offset, default_size=50
    )
    items, total = proj_svc.list_projects(
        db, auth, org_id=org_id, q=q, page=pg, page_size=size
    )
    return ProjectListPage(items=items, total=total, page=pg, page_size=size)


@router.post("/projects/{project_id}/members", response_model=ProjectMemberOut)
def api_add_member(
    project_id: str,
    body: ProjectMemberIn,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> ProjectMemberOut:
    try:
        return proj_svc.add_member(db, project_id, body, auth)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.delete(
    "/projects/{project_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
def api_remove_member(
    project_id: str,
    user_id: str,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> None:
    try:
        proj_svc.remove_member(db, project_id, user_id, auth)
        audit_svc.write_audit_auth(
            db,
            auth,
            action="project.member_remove",
            resource_type="project",
            resource_id=project_id,
            detail=user_id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/projects/{project_id}/members", response_model=ProjectMemberListPage)
def api_list_members(
    project_id: str,
    page: int | None = Query(None, ge=1),
    page_size: int | None = Query(None, ge=1, le=200),
    limit: int | None = Query(None, ge=1, le=200),
    offset: int | None = Query(None, ge=0),
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> ProjectMemberListPage:

    try:
        pg, size = normalize_page_params(
            page=page, page_size=page_size, limit=limit, offset=offset, default_size=50
        )
        items, total = proj_svc.list_members(
            db, project_id, auth, page=pg, page_size=size
        )
        return ProjectMemberListPage(items=items, total=total, page=pg, page_size=size)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


