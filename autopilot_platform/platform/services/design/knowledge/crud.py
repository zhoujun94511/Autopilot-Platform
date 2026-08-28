"""知识条目 CRUD（独立于 logical-case / documents 服务）。"""
from __future__ import annotations
import logging
from autopilot_platform.platform.services.shared.actors import actor as _actor
from sqlalchemy import or_, select
from sqlalchemy.orm import Session
from autopilot_platform.platform.auth import AuthContext
from autopilot_platform.platform.design.design_models import KnowledgeItemRow, new_id
from autopilot_platform.platform.design.design_schemas import (
    KnowledgeItemCreate,
    KnowledgeItemOut,
    KnowledgeItemUpdate,
    KnowledgeSearchHit,
    KnowledgeSearchOut,
)
from autopilot_platform.platform.core.models import db_get
from autopilot_platform.platform.ops.runtime_config import cfg_str
from autopilot_platform.platform.services.shared.pagination import apply_sort, clamp_page, paginate, sort_column
from autopilot_platform.platform.services.design import access as design_access

log = logging.getLogger(__name__)

def _to_out(row: KnowledgeItemRow) -> KnowledgeItemOut:
    return KnowledgeItemOut(id=row.id, project_id=row.project_id, title=row.title, content=row.content, category=row.category, source=row.source, confirmed=row.confirmed, created_by=row.created_by, created_at=row.created_at)

def _touch_index(project_id: str, *, item_id: str='', drop: bool=False) -> None:
    try:
        from autopilot_platform.platform.rag.vector_index_store import invalidate_project_index, remove_index_item  # 延迟：RAG extra
        if drop and item_id:
            remove_index_item(project_id, item_id)
        else:
            invalidate_project_index(project_id)
    except (OSError, RuntimeError, ImportError, KeyError) as exc:
        log.debug('knowledge index touch skipped: %s', exc)

def create_knowledge_item(db: Session, body: KnowledgeItemCreate, auth: AuthContext) -> KnowledgeItemOut:
    row = KnowledgeItemRow(id=new_id(), project_id=body.project_id.strip(), title=body.title.strip(), content=body.content or '', category=body.category or 'other', source=body.source or '', confirmed=bool(body.confirmed), created_by=_actor(auth))
    db.add(row)
    db.commit()
    db.refresh(row)
    _touch_index(str(row.project_id))
    return _to_out(row)
_KNOWLEDGE_SORT = {'created_at': KnowledgeItemRow.created_at, 'title': KnowledgeItemRow.title, 'category': KnowledgeItemRow.category}

def query_knowledge_items(db: Session, *, project_id: str | None=None, project_ids: list[str] | None=None, q: str | None=None, category: str | None=None, confirmed: bool | None=None, sort_by: str | None=None, order: str='desc', page: int | None=None, page_size: int | None=None) -> tuple[list[KnowledgeItemOut], int, int | None, int]:
    page_n, size = clamp_page(page, page_size)
    stmt = select(KnowledgeItemRow)
    if project_ids is not None:
        if not project_ids:
            return [], 0, page_n, size
        stmt = stmt.where(KnowledgeItemRow.project_id.in_(project_ids))
    elif project_id:
        stmt = stmt.where(KnowledgeItemRow.project_id == project_id.strip())
    if category and category.strip():
        stmt = stmt.where(KnowledgeItemRow.category == category.strip())
    if confirmed is not None:
        stmt = stmt.where(KnowledgeItemRow.confirmed.is_(bool(confirmed)))
    term = (q or '').strip()
    if term:
        like = f'%{term}%'
        stmt = stmt.where(or_(KnowledgeItemRow.title.ilike(like), KnowledgeItemRow.content.ilike(like)))
    col = sort_column(_KNOWLEDGE_SORT, sort_by, 'created_at')
    stmt = apply_sort(stmt, col, order=order)
    rows, total = paginate(db, stmt, page=page_n, page_size=size)
    return [_to_out(r) for r in rows], total, page_n, size

def list_knowledge_items(db: Session, project_id: str | None=None, project_ids: list[str] | None=None) -> list[KnowledgeItemOut]:
    items, _, _, _ = query_knowledge_items(db, project_id=project_id, project_ids=project_ids, page=None)
    return items

def get_knowledge_item(db: Session, item_id: str) -> KnowledgeItemOut:
    row = db_get(db, KnowledgeItemRow, (item_id or '').strip())
    if row is None:
        raise LookupError(f'知识条目不存在：{item_id}')
    return _to_out(row)

def update_knowledge_item(db: Session, item_id: str, body: KnowledgeItemUpdate, auth: AuthContext) -> KnowledgeItemOut:
    _ = auth
    row = db_get(db, KnowledgeItemRow, (item_id or '').strip())
    if row is None:
        raise LookupError(f'知识条目不存在：{item_id}')
    data = body.model_dump(exclude_unset=True)
    if 'title' in data and data['title'] is not None:
        title = str(data['title']).strip()
        if not title:
            raise ValueError('title 不能为空')
        row.title = title
    if 'content' in data and data['content'] is not None:
        row.content = str(data['content'])
    if 'category' in data and data['category'] is not None:
        row.category = str(data['category']) or 'other'
    if 'source' in data and data['source'] is not None:
        row.source = str(data['source'])
    if 'confirmed' in data and data['confirmed'] is not None:
        row.confirmed = bool(data['confirmed'])
    db.add(row)
    db.commit()
    db.refresh(row)
    _touch_index(str(row.project_id))
    return _to_out(row)

def delete_knowledge_item(db: Session, item_id: str, auth: AuthContext) -> None:
    row = db_get(db, KnowledgeItemRow, (item_id or '').strip())
    if row is None:
        raise LookupError(f'知识条目不存在：{item_id}')
    design_access.ensure_row_project_write(db, auth, row.project_id)
    pid = str(row.project_id)
    rid = str(row.id)
    db.delete(row)
    db.commit()
    _touch_index(pid, item_id=rid, drop=True)

def batch_delete_knowledge_items(db: Session, item_ids: list[str], auth: AuthContext) -> dict:
    for iid in item_ids or []:
        rid = (iid or '').strip()
        if not rid:
            continue
        row = db_get(db, KnowledgeItemRow, rid)
        if row is None:
            continue
        design_access.ensure_row_project_write(db, auth, row.project_id)
    deleted = 0
    failed = 0
    errors: list[str] = []
    for iid in item_ids or []:
        try:
            delete_knowledge_item(db, iid, auth)
            deleted += 1
        except LookupError as exc:
            failed += 1
            errors.append(str(exc))
        except Exception as exc:
            failed += 1
            errors.append(f'{iid}: {exc}')
    return {'success': failed == 0 and deleted > 0, 'deleted_count': deleted, 'failed_count': failed, 'message': f'已删除 {deleted} 条，失败 {failed} 条', 'errors': errors[:20]}

def search_knowledge(db: Session, *, project_id: str, query: str, top_k: int=10, score_threshold: float=0.3, confirmed_only: bool=False) -> dict:
    # 延迟：知识检索走 RAG extra
    from autopilot_platform.platform.rag.service import retrieve_knowledge_context
    q = (query or '').strip()
    if not q:
        raise ValueError('query 不能为空')
    pid = (project_id or '').strip()
    if not pid:
        raise ValueError('project_id 不能为空')
    try:
        if score_threshold is None or score_threshold <= 0:
            score_threshold = float(cfg_str('AP_RAG_SCORE_THRESHOLD', '0.3') or 0.3)
        if not top_k:
            top_k = int(cfg_str('AP_RAG_TOP_K', '10') or 10)
    except (ValueError, TypeError, AttributeError, ImportError):
        pass
    rag = retrieve_knowledge_context(db, project_id=pid, query=q, top_k=max(1, min(int(top_k), 50)), confirmed_only=confirmed_only)
    hits_raw = list(rag.get('hits') or [])
    docs: list[KnowledgeSearchHit] = []
    for h in hits_raw:
        score = float(getattr(h, 'score', 0) if not isinstance(h, dict) else h.get('score') or 0)
        if score < float(score_threshold):
            continue
        hid = str(getattr(h, 'id', '') if not isinstance(h, dict) else h.get('id') or '')
        row = db_get(db, KnowledgeItemRow, hid) if hid else None
        if row is None:
            title = str(getattr(h, 'title', '') if not isinstance(h, dict) else h.get('title') or '')
            content = str(getattr(h, 'snippet', '') if not isinstance(h, dict) else h.get('snippet') or '')
            docs.append(KnowledgeSearchHit(id=hid or f'hit-{len(docs)}', title=title or '命中片段', content=content, score=score))
            continue
        docs.append(KnowledgeSearchHit(id=row.id, title=row.title, content=row.content, score=score, category=row.category, source=row.source, confirmed=bool(row.confirmed)))
    out = KnowledgeSearchOut(query=q, engine=str(rag.get('engine') or ''), total=len(docs), documents=docs)
    return out.model_dump(mode='json')

def rebuild_knowledge_index(db: Session, *, project_id: str, clear_all: bool=True) -> dict:
    """显式重建向量索引：清空后在下次检索时由 ensure_index_vectors 重建。"""
    # 延迟：重建索引走 RAG extra
    from autopilot_platform.platform.rag.service import retrieve_knowledge_context
    from autopilot_platform.platform.rag.vector_index_store import invalidate_project_index
    pid = (project_id or '').strip()
    if not pid:
        raise ValueError('project_id 不能为空')
    if clear_all:
        invalidate_project_index(pid)
    items = list_knowledge_items(db, project_id=pid)
    warm = retrieve_knowledge_context(db, project_id=pid, query=items[0].title if items else 'index', top_k=3)
    return {'success': True, 'message': f'已重建项目 {pid} 的知识索引', 'rebuild_info': {'project_id': pid, 'item_count': len(items), 'engine': warm.get('engine'), 'cleared': bool(clear_all)}}
