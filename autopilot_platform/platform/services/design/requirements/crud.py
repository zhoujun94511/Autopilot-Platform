"""需求条目 CRUD（从 design.py 拆出）。"""
from __future__ import annotations
from autopilot_platform.platform.services.shared.actors import actor as _actor
import uuid
from sqlalchemy import or_, select
from sqlalchemy.orm import Session
from autopilot_platform.platform.auth import AuthContext
from autopilot_platform.platform.design.design_models import RequirementRow, new_id
from autopilot_platform.platform.design.design_schemas import RequirementCreate, RequirementOut, RequirementUpdate
from autopilot_platform.platform.core.models import db_get
from autopilot_platform.platform.services.shared.pagination import apply_sort, clamp_page, paginate, sort_column
from autopilot_platform.platform.services.design import access as design_access

def to_out(row: RequirementRow) -> RequirementOut:
    return RequirementOut(id=row.id, project_id=row.project_id, req_key=row.req_key, title=row.title, content=row.content, req_type=row.req_type, priority=row.priority, status=row.status, source_document_id=row.source_document_id, source_excerpt=row.source_excerpt, created_by=row.created_by, created_at=row.created_at, updated_at=row.updated_at)

def create_requirement(db: Session, body: RequirementCreate, auth: AuthContext) -> RequirementOut:
    row = RequirementRow(id=new_id(), project_id=body.project_id.strip(), req_key=(body.req_key or f'REQ-{uuid.uuid4().hex[:8]}').strip(), title=body.title.strip(), content=body.content or '', req_type=body.req_type or 'functional', priority=body.priority or 'medium', source_document_id=body.source_document_id, source_excerpt=body.source_excerpt or '', created_by=_actor(auth))
    db.add(row)
    db.commit()
    db.refresh(row)
    return to_out(row)
_REQ_SORT = {'created_at': RequirementRow.created_at, 'title': RequirementRow.title, 'req_key': RequirementRow.req_key, 'priority': RequirementRow.priority}

def query_requirements(db: Session, *, project_id: str | None=None, project_ids: list[str] | None=None, source_document_id: str | None=None, q: str | None=None, priority: str | None=None, sort_by: str | None=None, order: str='desc', page: int | None=None, page_size: int | None=None) -> tuple[list[RequirementOut], int, int | None, int]:
    """返回 (items, total, page, page_size)。page=None 时返回全量过滤结果。"""
    page_n, size = clamp_page(page, page_size)
    stmt = select(RequirementRow)
    if project_ids is not None:
        if not project_ids:
            return [], 0, page_n, size
        stmt = stmt.where(RequirementRow.project_id.in_(project_ids))
    elif project_id:
        stmt = stmt.where(RequirementRow.project_id == project_id.strip())
    if source_document_id:
        stmt = stmt.where(RequirementRow.source_document_id == source_document_id.strip())
    if priority and priority.strip():
        stmt = stmt.where(RequirementRow.priority == priority.strip())
    term = (q or '').strip()
    if term:
        like = f'%{term}%'
        stmt = stmt.where(or_(RequirementRow.title.ilike(like), RequirementRow.req_key.ilike(like), RequirementRow.content.ilike(like)))
    col = sort_column(_REQ_SORT, sort_by, 'created_at')
    stmt = apply_sort(stmt, col, order=order)
    rows, total = paginate(db, stmt, page=page_n, page_size=size)
    return [to_out(r) for r in rows], total, page_n, size

def list_requirements(db: Session, project_id: str | None=None, project_ids: list[str] | None=None, source_document_id: str | None=None) -> list[RequirementOut]:
    items, _, _, _ = query_requirements(db, project_id=project_id, project_ids=project_ids, source_document_id=source_document_id, page=None)
    return items

def get_requirement(db: Session, req_id: str) -> RequirementOut:
    row = db_get(db, RequirementRow, (req_id or '').strip())
    if row is None:
        raise LookupError(f'需求不存在：{req_id}')
    return to_out(row)

def update_requirement(db: Session, req_id: str, body: RequirementUpdate, auth: AuthContext) -> RequirementOut:
    _ = auth
    row = db_get(db, RequirementRow, (req_id or '').strip())
    if row is None:
        raise LookupError(f'需求不存在：{req_id}')
    data = body.model_dump(exclude_unset=True)
    if 'title' in data and data['title'] is not None:
        title = str(data['title']).strip()
        if not title:
            raise ValueError('title 不能为空')
        row.title = title
    if 'content' in data and data['content'] is not None:
        row.content = str(data['content'])
    if 'req_key' in data and data['req_key'] is not None:
        key = str(data['req_key']).strip()
        if key:
            row.req_key = key
    if 'req_type' in data and data['req_type'] is not None:
        row.req_type = str(data['req_type']) or 'functional'
    if 'priority' in data and data['priority'] is not None:
        row.priority = str(data['priority']) or 'medium'
    if 'status' in data and data['status'] is not None:
        row.status = str(data['status']) or 'draft'
    db.add(row)
    db.commit()
    db.refresh(row)
    return to_out(row)

def delete_requirement(db: Session, req_id: str, auth: AuthContext) -> None:
    row = db_get(db, RequirementRow, (req_id or '').strip())
    if row is None:
        raise LookupError(f'需求不存在：{req_id}')
    design_access.ensure_row_project_write(db, auth, row.project_id)
    db.delete(row)
    db.commit()

def batch_delete_requirements(db: Session, item_ids: list[str], auth: AuthContext) -> dict:
    for iid in item_ids or []:
        rid = (iid or '').strip()
        if not rid:
            continue
        row = db_get(db, RequirementRow, rid)
        if row is None:
            continue
        design_access.ensure_row_project_write(db, auth, row.project_id)
    deleted = 0
    failed = 0
    errors: list[str] = []
    for iid in item_ids or []:
        try:
            delete_requirement(db, iid, auth)
            deleted += 1
        except LookupError as exc:
            failed += 1
            errors.append(str(exc))
        except Exception as exc:
            failed += 1
            errors.append(f'{iid}: {exc}')
    return {'success': failed == 0 and deleted > 0, 'deleted_count': deleted, 'failed_count': failed, 'message': f'已删除 {deleted} 条，失败 {failed} 条', 'errors': errors[:20]}
