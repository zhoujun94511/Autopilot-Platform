"""Design document services."""
from __future__ import annotations
import logging
import re
from pathlib import Path
from sqlalchemy import or_, select
from sqlalchemy.orm import Session
from autopilot_platform.platform.auth import AuthContext
from autopilot_platform.platform.design.design_models import DesignDocumentRow, new_id
from autopilot_platform.platform.design.design_schemas import DesignDocumentOut, DocumentPreviewOut
from autopilot_platform.platform.core.models import db_get
from autopilot_platform.platform.services.shared.pagination import apply_sort, clamp_page, paginate, sort_column
logger = logging.getLogger(__name__)
ALLOWED_DOC_EXT = {'.txt', '.md', '.csv', '.json', '.yaml', '.yml', '.docx', '.pdf', '.xlsx', '.xls'}
_DOC_SORT = {'created_at': DesignDocumentRow.created_at, 'filename': DesignDocumentRow.filename, 'title': DesignDocumentRow.filename, 'file_type': DesignDocumentRow.file_type, 'size_bytes': DesignDocumentRow.size_bytes}
from autopilot_platform.platform.services.shared.actors import actor as _actor
from autopilot_platform.platform.services.design.documents.text_extract import uploads_root, extract_text_from_bytes
from autopilot_platform.platform.services.design import access as design_access
from autopilot_platform.platform.ops.runtime_config import design_max_memory_mb

def _doc_out(row: DesignDocumentRow, *, with_preview: bool=True) -> DesignDocumentOut:
    preview = ''
    if with_preview:
        preview = (row.content_text or '')[:400]
    return DesignDocumentOut(id=row.id, project_id=row.project_id, filename=row.filename, file_type=row.file_type, size_bytes=row.size_bytes, uploaded_by=row.uploaded_by, created_at=row.created_at, content_preview=preview)

def save_document(db: Session, *, project_id: str, filename: str, data: bytes, auth: AuthContext) -> DesignDocumentOut:
    if not data:
        raise ValueError('空文件')
    limit_mb = design_max_memory_mb()
    limit_bytes = max(1, limit_mb) * 1024 * 1024
    if len(data) > limit_bytes:
        raise ValueError(f'文件过大：{len(data)} 字节，超过 AP_MAX_MEMORY_MB={limit_mb}MB 上限')
    text = extract_text_from_bytes(filename, data)
    ext = Path(filename).suffix.lower().lstrip('.')
    doc_id = new_id()
    dest_dir = uploads_root() / project_id.strip()
    dest_dir.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub('[^\\w.\\-]+', '_', Path(filename).name) or 'upload.bin'
    stored = dest_dir / f'{doc_id}_{safe_name}'
    stored.write_bytes(data)
    row = DesignDocumentRow(id=doc_id, project_id=project_id.strip(), filename=Path(filename).name, stored_path=str(stored.resolve()), content_text=text, file_type=ext, size_bytes=len(data), uploaded_by=_actor(auth))
    db.add(row)
    db.commit()
    db.refresh(row)
    return _doc_out(row)

def query_documents(db: Session, *, project_id: str | None=None, project_ids: list[str] | None=None, q: str | None=None, file_type: str | None=None, sort_by: str | None=None, order: str='desc', page: int | None=None, page_size: int | None=None) -> tuple[list[DesignDocumentOut], int, int | None, int]:
    page_n, size = clamp_page(page, page_size)
    stmt = select(DesignDocumentRow)
    if project_ids is not None:
        if not project_ids:
            return [], 0, page_n, size
        stmt = stmt.where(DesignDocumentRow.project_id.in_(project_ids))
    elif project_id:
        stmt = stmt.where(DesignDocumentRow.project_id == project_id.strip())
    if file_type and file_type.strip():
        ft = file_type.strip().lstrip('.').lower()
        stmt = stmt.where(DesignDocumentRow.file_type == ft)
    term = (q or '').strip()
    if term:
        like = f'%{term}%'
        stmt = stmt.where(or_(DesignDocumentRow.filename.ilike(like), DesignDocumentRow.content_text.ilike(like)))
    col = sort_column(_DOC_SORT, sort_by, 'created_at')
    stmt = apply_sort(stmt, col, order=order)
    rows, total = paginate(db, stmt, page=page_n, page_size=size)
    return [_doc_out(r) for r in rows], total, page_n, size

def list_documents(db: Session, project_id: str | None=None, project_ids: list[str] | None=None) -> list[DesignDocumentOut]:
    items, _, _, _ = query_documents(db, project_id=project_id, project_ids=project_ids, page=None)
    return items

def batch_delete_documents(db: Session, item_ids: list[str], auth: AuthContext) -> dict:
    for iid in item_ids or []:
        rid = (iid or '').strip()
        if not rid:
            continue
        try:
            row = get_document(db, rid)
        except LookupError:
            continue
        else:
            design_access.ensure_row_project_write(db, auth, row.project_id)
    deleted = 0
    failed = 0
    errors: list[str] = []
    for iid in item_ids or []:
        try:
            delete_document(db, iid, auth)
            deleted += 1
        except LookupError as exc:
            failed += 1
            errors.append(str(exc))
        except Exception as exc:
            failed += 1
            errors.append(f'{iid}: {exc}')
    return {'success': failed == 0 and deleted > 0, 'deleted_count': deleted, 'failed_count': failed, 'message': f'已删除 {deleted} 条，失败 {failed} 条', 'errors': errors[:20]}

def get_document(db: Session, document_id: str) -> DesignDocumentRow:
    row = db_get(db, DesignDocumentRow, document_id)
    if row is None:
        raise LookupError('文档不存在')
    return row

def preview_document(db: Session, document_id: str, *, max_chars: int=200000) -> DocumentPreviewOut:
    row = get_document(db, document_id)
    text = row.content_text or ''
    truncated = len(text) > max_chars
    if truncated:
        text = text[:max_chars]
    return DocumentPreviewOut(id=row.id, project_id=row.project_id, filename=row.filename, file_type=row.file_type, size_bytes=row.size_bytes, content=text, content_type='text', is_truncated=truncated)

def delete_document(db: Session, document_id: str, auth: AuthContext) -> None:
    """删除文档记录与落盘文件（不级联删除已生成的需求）。"""
    row = get_document(db, document_id)
    design_access.ensure_row_project_write(db, auth, row.project_id)
    stored = (row.stored_path or '').strip()
    db.delete(row)
    db.commit()
    if stored:
        try:
            Path(stored).unlink(missing_ok=True)
        except OSError:
            pass
