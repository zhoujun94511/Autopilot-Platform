"""Logical case services."""
from __future__ import annotations
import uuid
from datetime import datetime, timezone
from typing import Any
from sqlalchemy import or_, select
from sqlalchemy.orm import Session
from autopilot_platform.platform.auth import AuthContext
from autopilot_platform.platform.design.design_models import LogicalCaseRow, new_id
from autopilot_platform.platform.design.design_schemas import LogicalCaseCreate, LogicalCaseOut, LogicalCaseUpdate
from autopilot_platform.platform.core.models import db_get
from autopilot_platform.platform.services.shared.pagination import apply_sort, clamp_page, paginate, sort_column
_CASE_SORT = {'updated_at': LogicalCaseRow.updated_at, 'created_at': LogicalCaseRow.created_at, 'title': LogicalCaseRow.title, 'priority': LogicalCaseRow.priority}
from autopilot_platform.platform.services.shared.actors import actor as _actor
from autopilot_platform.platform.services.design.cases.mapping import _case_out, _ensure_intent_steps
from autopilot_platform.platform.services.design.cases.webhooks import _fire_approved_webhook
from autopilot_platform.platform.services.design import access as design_access

def create_logical_case(db: Session, body: LogicalCaseCreate, auth: AuthContext) -> LogicalCaseOut:
    if not body.logical_steps and (not body.intent_steps):
        raise ValueError('logical_steps / intent_steps 不能同时为空')
    intents = _ensure_intent_steps(body)
    if not body.logical_steps:
        body.logical_steps = [str(s.get('text') or s.get('target') or '') for s in intents]
    row = LogicalCaseRow(id=new_id(), project_id=body.project_id.strip(), case_key=(body.case_key or f'LC-{uuid.uuid4().hex[:8]}').strip(), revision_id=uuid.uuid4().hex, title=body.title.strip(), description=body.description or '', priority=body.priority or 'P2', test_type=body.test_type or '', module=body.module or '', review_status=body.review_status, automatability=body.automatability, automation_status=body.automation_status if body.automation_status else 'INTENT_READY' if intents else 'LOGICAL_ONLY', created_by=_actor(auth))
    row.preconditions = body.preconditions
    row.logical_steps = body.logical_steps
    row.intent_steps = intents
    row.expected_results = body.expected_results
    row.tags = body.tags
    row.source_requirement_ids = body.source_requirement_ids
    row.generation_metadata = body.generation_metadata
    db.add(row)
    db.commit()
    db.refresh(row)
    out = _case_out(row)
    if str(row.review_status or '') == 'APPROVED':
        _fire_approved_webhook(out)
    return out

def query_logical_cases(db: Session, *, project_id: str | None=None, project_ids: list[str] | None=None, review_status: str | None=None, automation_status: str | None=None, q: str | None=None, sort_by: str | None=None, order: str='desc', page: int | None=None, page_size: int | None=None) -> tuple[list[LogicalCaseOut], int, int | None, int]:
    """返回 (items, total, page, page_size)。page=None 时返回全量过滤结果。"""
    page_n, size = clamp_page(page, page_size)
    stmt = select(LogicalCaseRow)
    if project_ids is not None:
        if not project_ids:
            return [], 0, page_n, size
        stmt = stmt.where(LogicalCaseRow.project_id.in_(project_ids))
    elif project_id:
        stmt = stmt.where(LogicalCaseRow.project_id == project_id.strip())
    if review_status:
        stmt = stmt.where(LogicalCaseRow.review_status == review_status.strip())
    if automation_status:
        stmt = stmt.where(LogicalCaseRow.automation_status == automation_status.strip())
    term = (q or '').strip()
    if term:
        like = f'%{term}%'
        stmt = stmt.where(or_(LogicalCaseRow.title.ilike(like), LogicalCaseRow.case_key.ilike(like), LogicalCaseRow.description.ilike(like)))
    col = sort_column(_CASE_SORT, sort_by, 'updated_at')
    stmt = apply_sort(stmt, col, order=order)
    rows, total = paginate(db, stmt, page=page_n, page_size=size)
    return [_case_out(r) for r in rows], total, page_n, size

def list_logical_cases(db: Session, *, project_id: str | None=None, project_ids: list[str] | None=None, review_status: str | None=None, automation_status: str | None=None) -> list[LogicalCaseOut]:
    items, _, _, _ = query_logical_cases(db, project_id=project_id, project_ids=project_ids, review_status=review_status, automation_status=automation_status, page=None)
    return items

def get_logical_case(db: Session, case_id: str) -> LogicalCaseOut:
    row = db_get(db, LogicalCaseRow, case_id)
    if row is None:
        raise LookupError('逻辑用例不存在')
    return _case_out(row)

def update_logical_case(db: Session, case_id: str, body: LogicalCaseUpdate, auth: AuthContext) -> LogicalCaseOut:
    row = db_get(db, LogicalCaseRow, case_id)
    if row is None:
        raise LookupError('逻辑用例不存在')
    prev_review = str(row.review_status or '')
    data = body.model_dump(exclude_unset=True)
    for key in ('title', 'description', 'priority', 'test_type', 'module', 'review_status', 'automatability', 'automation_status'):
        if key in data and data[key] is not None:
            setattr(row, key, data[key])
    if 'preconditions' in data and data['preconditions'] is not None:
        row.preconditions = data['preconditions']
    if 'logical_steps' in data and data['logical_steps'] is not None:
        if not data['logical_steps'] and 'intent_steps' not in data:
            raise ValueError('logical_steps 不能为空')
        row.logical_steps = data['logical_steps']
    if 'intent_steps' in data and data['intent_steps'] is not None:
        raw = data['intent_steps']
        row.intent_steps = [s if isinstance(s, dict) else s.model_dump() if hasattr(s, 'model_dump') else dict(s) for s in raw]
        if row.intent_steps and row.automation_status in ('LOGICAL_ONLY', ''):
            row.automation_status = 'INTENT_READY'
    if 'expected_results' in data and data['expected_results'] is not None:
        row.expected_results = data['expected_results']
    if 'tags' in data and data['tags'] is not None:
        row.tags = data['tags']
    if 'source_requirement_ids' in data and data['source_requirement_ids'] is not None:
        row.source_requirement_ids = data['source_requirement_ids']
    if 'generation_metadata' in data and data['generation_metadata'] is not None:
        row.generation_metadata = data['generation_metadata']
    row.revision_id = uuid.uuid4().hex
    row.updated_at = datetime.now(timezone.utc)
    _ = auth
    db.commit()
    db.refresh(row)
    out = _case_out(row)
    if str(row.review_status or '') == 'APPROVED' and prev_review != 'APPROVED':
        _fire_approved_webhook(out)
    return out

def delete_logical_case(db: Session, case_id: str, auth: AuthContext) -> None:
    row = db_get(db, LogicalCaseRow, (case_id or '').strip())
    if row is None:
        raise LookupError('逻辑用例不存在')
    design_access.ensure_row_project_write(db, auth, row.project_id)
    db.delete(row)
    db.commit()

def batch_delete_logical_cases(db: Session, case_ids: list[str], auth: AuthContext) -> dict[str, Any]:
    """批量删除逻辑用例；逐条尽力删除。"""
    ids = [str(x).strip() for x in case_ids or [] if str(x).strip()]
    if not ids:
        raise ValueError('case_ids 不能为空')
    for cid in ids:
        row = db_get(db, LogicalCaseRow, cid)
        if row is None:
            continue
        design_access.ensure_row_project_write(db, auth, row.project_id)
    deleted: list[str] = []
    failed: list[dict[str, str]] = []
    for cid in ids:
        try:
            delete_logical_case(db, cid, auth)
            deleted.append(cid)
        except LookupError as exc:
            failed.append({'id': cid, 'error': str(exc)})
        except Exception as exc:
            failed.append({'id': cid, 'error': str(exc)})
    return {'success': len(failed) == 0, 'deleted_count': len(deleted), 'failed_count': len(failed), 'deleted': deleted, 'failed': failed}
