"""设计域项目作用域门禁（与制品/Job 共用 projects 软多租户）。"""
from __future__ import annotations
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from autopilot_platform.platform.auth import AuthContext
from autopilot_platform.platform.tenancy.projects import assert_can_access_project, assert_can_write_project, visible_project_filter

def require_design_user(auth: AuthContext) -> None:
    if auth.kind != 'user':
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='需要用户登录')

def ensure_project_access(db: Session, auth: AuthContext, project_id: str) -> str:
    """读指定项目：必须非空且为成员（或平台 admin）。"""
    pid = (project_id or '').strip()
    if not pid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='需要 project_id')
    try:
        assert_can_access_project(db, auth, pid)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return pid

def ensure_project_write(db: Session, auth: AuthContext, project_id: str) -> str:
    """写指定项目：owner/member（viewer 拒绝）。"""
    pid = (project_id or '').strip()
    if not pid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='需要 project_id')
    try:
        assert_can_write_project(db, auth, pid)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return pid

def ensure_row_project_access(db: Session, auth: AuthContext, project_id: str | None) -> str:
    """按资源已有 project_id 校验读权限；无项目归属直接拒绝。"""
    pid = (project_id or '').strip()
    if not pid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='需要 project_id')
    return ensure_project_access(db, auth, pid)

def ensure_row_project_write(db: Session, auth: AuthContext, project_id: str | None) -> str:
    pid = (project_id or '').strip()
    if not pid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='需要 project_id')
    return ensure_project_write(db, auth, pid)

def resolve_list_scope(db: Session, auth: AuthContext, project_id: str | None) -> list[str] | None:
    """列表作用域。

    返回:
      - None：不过滤（仅平台 admin）
      - []：无可见项目
      - [id, ...]：仅这些项目
    """
    pid = (project_id or '').strip()
    if pid:
        ensure_project_access(db, auth, pid)
        return [pid]
    visible = visible_project_filter(db, auth)
    if visible is None:
        return None
    return sorted(visible)
