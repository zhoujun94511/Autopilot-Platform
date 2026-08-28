"""Schedules + tick."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from autopilot_platform.core.schemas import ScheduleCreate, ScheduleListPage, ScheduleOut, ScheduleUpdate

from ..auth import AuthContext, require_admin, require_auth
from ..core.db import get_session
from ..core.list_page import normalize_page_params
from ..ops import audit as audit_svc
from ..services.execution import schedules as sched_svc

router = APIRouter(tags=["schedules"])

@router.post("/schedules", response_model=ScheduleOut)
def api_create_schedule(
    body: ScheduleCreate,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> ScheduleOut:
    try:
        out = sched_svc.create_schedule(db, body, auth)
        audit_svc.write_audit_auth(
            db, auth, action="schedule.create", resource_type="schedule", resource_id=out.id
        )
        return out
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/schedules", response_model=ScheduleListPage)
def api_list_schedules(
    project_id: str = Query(""),
    page: int | None = Query(None, ge=1),
    page_size: int | None = Query(None, ge=1, le=200),
    limit: int | None = Query(None, ge=1, le=200),
    offset: int | None = Query(None, ge=0),
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> ScheduleListPage:

    try:
        pg, size = normalize_page_params(
            page=page, page_size=page_size, limit=limit, offset=offset, default_size=50
        )
        items, total = sched_svc.list_schedules(
            db, auth, project_id=project_id, page=pg, page_size=size
        )
        return ScheduleListPage(items=items, total=total, page=pg, page_size=size)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@router.get("/schedules/{schedule_id}", response_model=ScheduleOut)
def api_get_schedule(
    schedule_id: str,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> ScheduleOut:
    try:
        return sched_svc.get_schedule(db, schedule_id, auth)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@router.patch("/schedules/{schedule_id}", response_model=ScheduleOut)
def api_update_schedule(
    schedule_id: str,
    body: ScheduleUpdate,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> ScheduleOut:
    try:
        return sched_svc.update_schedule(db, schedule_id, body, auth)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@router.delete(
    "/schedules/{schedule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
def api_delete_schedule(
    schedule_id: str,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> None:
    try:
        sched_svc.delete_schedule(db, schedule_id, auth)
        audit_svc.write_audit_auth(
            db, auth, action="schedule.delete", resource_type="schedule", resource_id=schedule_id
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@router.post("/schedules/{schedule_id}/run-now", response_model=ScheduleOut)
def api_run_schedule_now(
    schedule_id: str,
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> ScheduleOut:
    try:
        return sched_svc.run_schedule_now(db, schedule_id, auth)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/schedules-tick", response_model=list[str])
def api_schedules_tick(
    db: Session = Depends(get_session),
    _auth: AuthContext = Depends(require_admin),
) -> list[str]:
    """手动触发扫描（联调/运维）；正常由后台线程周期执行。"""
    return sched_svc.tick_due_schedules(db)


