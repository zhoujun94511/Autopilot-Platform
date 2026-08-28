"""Organization CRUD + members."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from autopilot_platform.core.schemas import (
    OrganizationCreate,
    OrganizationListPage,
    OrganizationMemberIn,
    OrganizationMemberListPage,
    OrganizationMemberOut,
    OrganizationOut,
    OrganizationPoliciesPatch,
)

from ..core import api_messages as msg
from ..ops import audit as audit_svc
from ..auth import AuthContext, require_auth
from ..core.db import get_session
from ..core.list_page import normalize_page_params
from ..tenancy import organizations as org_svc

router = APIRouter(tags=["organizations"])


@router.post("/orgs", response_model=OrganizationOut)
def api_create_org(
    body: OrganizationCreate,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> OrganizationOut:
    if auth.kind != "user":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg.AUTH_USER_LOGIN_REQUIRED)
    try:
        out = org_svc.create_organization(db, body, auth)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except (PermissionError, ValueError) as exc:
        code = (
            status.HTTP_403_FORBIDDEN
            if isinstance(exc, PermissionError)
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=code, detail=str(exc)) from exc
    audit_svc.write_audit_auth(
        db, auth, action="org.create", resource_type="organization", resource_id=out.id
    )
    return out


@router.get("/orgs", response_model=OrganizationListPage)
def api_list_orgs(
    page: int | None = Query(None, ge=1),
    page_size: int | None = Query(None, ge=1, le=200),
    limit: int | None = Query(None, ge=1, le=200),
    offset: int | None = Query(None, ge=0),
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> OrganizationListPage:

    pg, size = normalize_page_params(
        page=page, page_size=page_size, limit=limit, offset=offset, default_size=50
    )
    items, total = org_svc.list_organizations(db, auth, page=pg, page_size=size)
    return OrganizationListPage(items=items, total=total, page=pg, page_size=size)


@router.get("/orgs/{org_id}", response_model=OrganizationOut)
def api_get_org(
    org_id: str,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> OrganizationOut:
    try:
        return org_svc.get_organization(db, org_id, auth)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@router.patch("/orgs/{org_id}/policies", response_model=OrganizationOut)
def api_patch_org_policies(
    org_id: str,
    body: OrganizationPoliciesPatch,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> OrganizationOut:
    try:
        out = org_svc.update_org_policies(db, org_id, body, auth)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    audit_svc.write_audit_auth(
        db,
        auth,
        action="org.policies_update",
        resource_type="organization",
        resource_id=org_id,
    )
    return out


@router.post("/orgs/{org_id}/members", response_model=OrganizationMemberOut)
def api_add_org_member(
    org_id: str,
    body: OrganizationMemberIn,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> OrganizationMemberOut:
    try:
        return org_svc.add_org_member(db, org_id, body, auth)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/orgs/{org_id}/members", response_model=OrganizationMemberListPage)
def api_list_org_members(
    org_id: str,
    page: int | None = Query(None, ge=1),
    page_size: int | None = Query(None, ge=1, le=200),
    limit: int | None = Query(None, ge=1, le=200),
    offset: int | None = Query(None, ge=0),
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> OrganizationMemberListPage:

    try:
        pg, size = normalize_page_params(
            page=page, page_size=page_size, limit=limit, offset=offset, default_size=50
        )
        items, total = org_svc.list_org_members(
            db, org_id, auth, page=pg, page_size=size
        )
        return OrganizationMemberListPage(
            items=items, total=total, page=pg, page_size=size
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@router.delete(
    "/orgs/{org_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
def api_remove_org_member(
    org_id: str,
    user_id: str,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> None:
    try:
        org_svc.remove_org_member(db, org_id, user_id, auth)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    audit_svc.write_audit_auth(
        db,
        auth,
        action="org.member_remove",
        resource_type="organization",
        resource_id=org_id,
        detail=user_id,
    )
