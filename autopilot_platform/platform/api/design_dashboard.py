"""设计域仪表盘 API：stats / export / batch export。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..auth import AuthContext, require_auth
from ..core.db import get_session
from ..ops import audit as audit_svc
from ..services.design import access as design_access
from ..services.design import stats as stats_svc
from ..tenancy.rbac_response import can_view_ops_budget, sanitize_design_stats

router = APIRouter(tags=["design"])


@router.get("/design/stats")
def api_design_stats(
    project_id: str | None = Query(default=None),
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
) -> dict:
    """设计域计数（仪表盘）；按可见项目过滤。"""
    scope = design_access.resolve_list_scope(db, auth, project_id)
    raw = stats_svc.design_domain_stats(db, project_id=project_id, project_ids=scope)
    return sanitize_design_stats(raw, auth)


@router.get("/design/stats/export")
def api_design_stats_export(
    project_id: str | None = Query(default=None),
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
):
    """设计域统计 CSV 导出。"""
    scope = design_access.resolve_list_scope(db, auth, project_id)
    return stats_svc.export_stats_csv(
        db,
        project_id=project_id,
        project_ids=scope,
        include_token_metrics=can_view_ops_budget(auth),
    )


@router.post("/design/export/batch")
def api_design_batch_export(
    body: dict | None = None,
    project_id: str | None = Query(default=None),
    db: Session = Depends(get_session),
    auth: AuthContext = Depends(require_auth),
):
    """设计域批量 ZIP 导出（用例/需求/知识等）。"""
    payload = body if isinstance(body, dict) else {}
    pid = (payload.get("project_id") or project_id or "").strip() or None
    config = payload.get("config") if isinstance(payload.get("config"), dict) else payload
    scope = design_access.resolve_list_scope(db, auth, pid)
    audit_svc.write_audit_auth(
        db,
        auth,
        action="design.batch_export",
        resource_type="project",
        resource_id=str(pid or ""),
    )
    return stats_svc.export_design_batch_zip(
        db, project_id=pid, project_ids=scope, config=config if isinstance(config, dict) else {}
    )
