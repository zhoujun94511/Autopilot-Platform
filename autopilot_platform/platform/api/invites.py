"""Project invites: create/list/revoke + public preview/register + accept."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from autopilot_platform.core.schemas import (
    InviteRegisterIn,
    ProjectInviteCreate,
    ProjectInviteListPage,
    ProjectInviteOut,
    ProjectInvitePreview,
    ProjectMemberOut,
    TokenOut,
)

from ..core import api_messages as msg
from ..ops import audit as audit_svc
from ..auth import AuthContext, require_auth
from ..core.db import get_session
from ..core.list_page import normalize_page_params
from ..tenancy import project_invites as invite_svc

# 需登录
router = APIRouter(tags=["invites"])
# 公开预览 / 自助注册
public_router = APIRouter(tags=["invites"])


@router.post("/projects/{project_id}/invites", response_model=ProjectInviteOut)
def api_create_invite(
    project_id: str,
    body: ProjectInviteCreate,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> ProjectInviteOut:
    if auth.kind != "user":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg.AUTH_USER_LOGIN_REQUIRED)
    try:
        out = invite_svc.create_invite(db, project_id, body, auth)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    audit_svc.write_audit_auth(
        db, auth, action="project.invite.create", resource_type="project", resource_id=project_id
    )
    return out


@router.get("/projects/{project_id}/invites", response_model=ProjectInviteListPage)
def api_list_invites(
    project_id: str,
    page: int | None = Query(None, ge=1),
    page_size: int | None = Query(None, ge=1, le=200),
    limit: int | None = Query(None, ge=1, le=200),
    offset: int | None = Query(None, ge=0),
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> ProjectInviteListPage:

    pg, size = normalize_page_params(
        page=page, page_size=page_size, limit=limit, offset=offset, default_size=50
    )
    try:
        items, total = invite_svc.list_invites(
            db, project_id, auth, page=pg, page_size=size
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return ProjectInviteListPage(items=items, total=total, page=pg, page_size=size)

@router.delete(
    "/projects/{project_id}/invites/{invite_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
def api_revoke_invite(
    project_id: str,
    invite_id: str,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> None:
    try:
        invite_svc.revoke_invite(db, project_id, invite_id, auth)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    audit_svc.write_audit_auth(
        db,
        auth,
        action="project.invite.revoke",
        resource_type="project",
        resource_id=project_id,
        detail=invite_id,
    )


@router.post("/invites/{token}/accept", response_model=ProjectMemberOut)
def api_accept_invite(
    token: str,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> ProjectMemberOut:
    try:
        out = invite_svc.accept_invite(db, token, auth)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    audit_svc.write_audit_auth(
        db,
        auth,
        action="project.invite.accept",
        resource_type="project",
        resource_id=out.project_id,
        detail=out.role,
    )
    return out


@public_router.get("/invites/{token}", response_model=ProjectInvitePreview)
def api_preview_invite(
    token: str,
    db: Session = Depends(get_session),
) -> ProjectInvitePreview:
    return invite_svc.preview_invite(db, token)


@public_router.post("/invites/{token}/register", response_model=TokenOut)
def api_register_via_invite(
    token: str,
    body: InviteRegisterIn,
    db: Session = Depends(get_session),
) -> TokenOut:
    try:
        out = invite_svc.register_via_invite(db, token, body)
    except LookupError as exc:
        # username exists → 409; invite missing → 404
        detail = str(exc)
        code = (
            status.HTTP_409_CONFLICT
            if "已存在" in detail or "exists" in detail.lower()
            else status.HTTP_404_NOT_FOUND
        )
        raise HTTPException(status_code=code, detail=detail) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    audit_svc.write_audit(
        db,
        action="project.invite.register",
        actor=out.user.username,
        actor_kind="user",
        resource_type="invite",
        resource_id=token[:16],
    )
    return out
