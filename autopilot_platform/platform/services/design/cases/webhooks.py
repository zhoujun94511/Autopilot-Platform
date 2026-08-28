"""Logical case services."""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from autopilot_platform.platform.design.design_schemas import LogicalCaseExportBundle, LogicalCaseOut

log = logging.getLogger(__name__)

def _fire_approved_webhook(case: LogicalCaseOut) -> None:
    try:
        from autopilot_platform.platform.ops.notify import notify_design_event  # 延迟：可选通知
        notify_design_event('logical_case.approved', project_id=case.project_id, case=case.model_dump(mode='json'))
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        log.warning('logical_case.approved webhook failed: %s', exc)

def export_approved_cases(db: Session, project_id: str) -> LogicalCaseExportBundle:
    pid = project_id.strip()
    # 延迟：拆环 crud ↔ webhooks
    from autopilot_platform.platform.services.design.cases.crud import list_logical_cases
    cases = list_logical_cases(db, project_id=pid, review_status='APPROVED')
    return LogicalCaseExportBundle(project_id=pid, exported_at=datetime.now(timezone.utc), cases=cases)
