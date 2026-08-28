"""AI billing scope helpers."""
from __future__ import annotations
from sqlalchemy.orm import Session
from autopilot_platform.platform.auth import AuthContext
from autopilot_platform.platform.core.models import ProjectRow, db_get
EPHEMERAL_PROJECT_BUCKET = "__ephemeral__"
PLATFORM_ORG_BUCKET = "__platform__"
def project_org_id(db: Session, project_id: str) -> str:
    pid=(project_id or "").strip()
    if not pid: return ""
    try:
        row=db_get(db, ProjectRow, pid)
        return str(getattr(row, "org_id", "") or "").strip() if row is not None else ""
    except (AttributeError, LookupError, RuntimeError, TypeError, ValueError): return ""
def fill_scope(project_id: str, org_id: str) -> tuple[str,str]:
    return (project_id or "").strip() or EPHEMERAL_PROJECT_BUCKET, (org_id or "").strip() or PLATFORM_ORG_BUCKET
def scope_for_session_id(db: Session, session_id: str, auth: AuthContext) -> tuple[str,str]:
    try:
        from autopilot_platform.platform.services.design.chat.sessions import get_session
        pid=(get_session(db, str(session_id or "")).project_id or "").strip()
    except (AttributeError, LookupError, ValueError, TypeError): pid=""
    return fill_scope(pid, project_org_id(db,pid) or (getattr(auth,"org_id","") or ""))
