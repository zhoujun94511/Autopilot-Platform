"""TR device pool + board + release."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from autopilot_platform.core.schemas import (
    DeviceListPage,
    DeviceMaintenanceIn,
    DeviceReservationCreate,
    DeviceReservationListPage,
    DeviceReservationOut,
)

from ..auth import AuthContext, require_auth
from ..core.db import get_session
from ..core.list_page import normalize_page_params
from ..core.models import DeviceRow
from ..ops import audit as audit_svc
from ..services.execution import devices as services
from ..services.remote import reservations

router = APIRouter(tags=["devices"])


def _device_org_id(db: Session, device_id: str) -> str:
    row = db.get(DeviceRow, device_id)
    return (
        str(getattr(getattr(row, "runner", None), "org_id", "") or "").strip()
        if row is not None
        else ""
    )


def _assert_manage_udid(
    db: Session, auth: AuthContext, udid: str
) -> list[DeviceRow]:
    rows = list(db.scalars(select(DeviceRow).where(DeviceRow.udid == udid)).all())
    if not rows:
        raise LookupError("设备不存在")
    if not all(reservations.can_user_manage_device(db, auth, row) for row in rows):
        raise PermissionError("无权管理该设备")
    return rows


@router.get("/devices", response_model=DeviceListPage)
def api_list_devices(
    project_id: str = Query(""),
    page: int | None = Query(None, ge=1),
    page_size: int | None = Query(None, ge=1, le=200),
    limit: int | None = Query(None, ge=1, le=200),
    offset: int | None = Query(None, ge=0),
    q: str = Query(""),
    platform: str = Query(""),
    busy: str = Query(""),
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> DeviceListPage:
    """TR 设备池：仅在线 Runner 上报的设备（按 auth 过滤组织可见性）。"""
    try:
        pg, size = normalize_page_params(
            page=page, page_size=page_size, limit=limit, offset=offset, default_size=50
        )
        items, total = services.list_tr_devices(
            db,
            auth=auth,
            project_id=project_id,
            page=pg,
            page_size=size,
            q=q,
            platform=platform,
            busy=busy,
        )
        return DeviceListPage(items=items, total=total, page=pg, page_size=size)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@router.get("/devices/board")
def api_device_board(
    project_id: str = Query(""),
    page: int | None = Query(None, ge=1),
    page_size: int | None = Query(None, ge=1, le=200),
    limit: int | None = Query(None, ge=1, le=200),
    offset: int | None = Query(None, ge=0),
    summary_only: bool = Query(False),
    q: str = Query(""),
    platform: str = Query(""),
    busy: str = Query(""),
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> dict:
    """设备占用看板：在线/空闲/占用汇总 + 明细。"""
    try:
        pg, size = normalize_page_params(
            page=page, page_size=page_size, limit=limit, offset=offset, default_size=50
        )
        return services.device_board(
            db,
            auth=auth,
            project_id=project_id,
            page=pg,
            page_size=size,
            summary_only=summary_only,
            q=q,
            platform=platform,
            busy=busy,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@router.post("/devices/{udid}/release")
def api_release_device(
    udid: str,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> dict:
    """强制释放设备占用（僵死占用运维手段）。"""
    try:
        rows = _assert_manage_udid(db, auth, udid)
        out = services.release_device(db, udid)
        audit_svc.write_audit_auth(
            db,
            auth,
            action="device.release",
            resource_type="device",
            resource_id=udid,
            detail=f"released_job_id={out.get('released_job_id') or ''}",
            org_id=str(getattr(rows[0].runner, "org_id", "") or "").strip(),
        )
        return out
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/devices/{udid}/maintenance")
def api_set_device_maintenance(
    udid: str,
    body: DeviceMaintenanceIn,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> dict:
    """设置/解除设备维护态（admin 运维）：停用后该设备不参与调度。"""
    try:
        rows = _assert_manage_udid(db, auth, udid)
        out = services.set_device_maintenance(db, udid, body.disabled, release=body.release)
        audit_svc.write_audit_auth(
            db,
            auth,
            action="device.maintenance",
            resource_type="device",
            resource_id=udid,
            detail=f"admin_disabled={out.get('admin_disabled')} released={bool(out.get('released'))}",
            org_id=str(getattr(rows[0].runner, "org_id", "") or "").strip(),
        )
        return out
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/device-reservations", response_model=DeviceReservationListPage)
def api_list_device_reservations(
    page: int | None = Query(None, ge=1),
    page_size: int | None = Query(None, ge=1, le=200),
    limit: int | None = Query(None, ge=1, le=200),
    offset: int | None = Query(None, ge=0),
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> DeviceReservationListPage:
    pg, size = normalize_page_params(
        page=page, page_size=page_size, limit=limit, offset=offset, default_size=50
    )
    items, total = reservations.active_reservations_for_auth(
        db, auth, page=pg, page_size=size
    )
    return DeviceReservationListPage(items=items, total=total, page=pg, page_size=size)


@router.post(
    "/devices/{device_id}/reservations",
    response_model=DeviceReservationOut,
    status_code=status.HTTP_201_CREATED,
)
def api_create_device_reservation(
    device_id: str,
    body: DeviceReservationCreate,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> DeviceReservationOut:
    try:
        out = reservations.create_reservation(db, device_id, body, auth)
        audit_svc.write_audit_auth(
            db,
            auth,
            action="device.reserve",
            resource_type="device",
            resource_id=device_id,
            detail=(
                f"reservation_id={out.id} "
                f"expires_at={out.expires_at.isoformat()} "
                f"reason={(out.reason or '')[:120]}"
            ),
            org_id=_device_org_id(db, device_id),
        )
        return out
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.delete(
    "/device-reservations/{reservation_id}",
    response_model=DeviceReservationOut,
)
def api_release_device_reservation(
    reservation_id: str,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> DeviceReservationOut:
    try:
        out = reservations.release_reservation(db, reservation_id, auth)
        audit_svc.write_audit_auth(
            db,
            auth,
            action="device.reservation_release",
            resource_type="device",
            resource_id=out.device_id,
            detail=f"reservation_id={out.id} status={out.status}",
            org_id=_device_org_id(db, out.device_id),
        )
        return out
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
