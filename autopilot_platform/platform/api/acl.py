"""ACL grant / list / revoke."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from autopilot_platform.core.schemas import AclGrantIn, AclGrantListPage, AclGrantOut

from ..auth import AuthContext, require_auth
from ..core.db import get_session
from ..core.list_page import normalize_page_params
from ..authz import acl as acl_svc
from ..ops import audit as audit_svc

router = APIRouter(tags=["acl"])

@router.post("/acl", response_model=AclGrantOut)
def api_grant_acl(
    body: AclGrantIn,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> AclGrantOut:
    try:
        out = acl_svc.grant_acl(db, body, auth)
        audit_svc.write_audit_auth(
            db,
            auth,
            action="acl.grant",
            resource_type=out.resource_type,
            resource_id=out.resource_id,
            detail=f"{out.username}:{out.permission}",
        )
        return out
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/acl", response_model=AclGrantListPage)
def api_list_acl(
    resource_type: str = Query(...),
    resource_id: str = Query(...),
    page: int | None = Query(None, ge=1),
    page_size: int | None = Query(None, ge=1, le=200),
    limit: int | None = Query(None, ge=1, le=200),
    offset: int | None = Query(None, ge=0),
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> AclGrantListPage:

    pg, size = normalize_page_params(
        page=page, page_size=page_size, limit=limit, offset=offset, default_size=50
    )
    try:
        items, total = acl_svc.list_acl(
            db,
            auth,
            resource_type=resource_type,
            resource_id=resource_id,
            page=pg,
            page_size=size,
        )
        return AclGrantListPage(items=items, total=total, page=pg, page_size=size)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.delete(
    "/acl/{acl_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
def api_revoke_acl(
    acl_id: str,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> None:
    try:
        snap = acl_svc.revoke_acl(db, acl_id, auth)
        audit_svc.write_audit_auth(
            db,
            auth,
            action="acl.revoke",
            resource_type=snap.resource_type,
            resource_id=snap.resource_id,
            detail=f"{snap.username}:{snap.permission}",
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


