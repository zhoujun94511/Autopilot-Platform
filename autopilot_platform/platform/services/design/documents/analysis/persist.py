"""Document analysis services."""
from __future__ import annotations
import logging
from typing import Any
from sqlalchemy import select
from sqlalchemy.orm import Session
from autopilot_platform.platform.auth import AuthContext
from autopilot_platform.platform.design.design_models import DesignAnalysisHistoryRow, DesignDocumentRow, TestPointRow, new_id
from autopilot_platform.platform.design.design_schemas import AnalysisHistoryOut, KnowledgeItemCreate, RequirementCreate, RequirementOut
from autopilot_platform.platform.services.shared.pagination import paginate
from autopilot_platform.platform.services.design.requirements.crud import create_requirement
logger = logging.getLogger(__name__)
from autopilot_platform.platform.services.shared.actors import actor as _actor
from autopilot_platform.platform.services.design.knowledge import crud as knowledge_svc

def list_analysis_history(db: Session, *, project_id: str | None=None, project_ids: list[str] | None=None, document_id: str | None=None, page: int=1, page_size: int=50) -> tuple[list[AnalysisHistoryOut], int]:
    q = select(DesignAnalysisHistoryRow).order_by(DesignAnalysisHistoryRow.created_at.desc())
    if project_ids is not None:
        if not project_ids:
            return [], 0
        q = q.where(DesignAnalysisHistoryRow.project_id.in_(project_ids))
    elif project_id:
        q = q.where(DesignAnalysisHistoryRow.project_id == project_id.strip())
    if document_id:
        q = q.where(DesignAnalysisHistoryRow.document_id == document_id.strip())
    size = max(1, min(200, int(page_size or 50)))
    pg = max(1, int(page or 1))
    rows, total = paginate(db, q, page=pg, page_size=size)
    out: list[AnalysisHistoryOut] = [AnalysisHistoryOut(id=r.id, project_id=r.project_id, document_id=r.document_id, analysis_type=r.analysis_type, requirement_count=int(r.requirement_count or 0), mode=r.mode, created_by=r.created_by, created_at=r.created_at, detail=r.detail) for r in rows]
    return out, total

def _record_analysis(db: Session, *, project_id: str, document_id: str, analysis_type: str, requirement_count: int, mode: str, auth: AuthContext, requirement_ids: list[str] | None=None, detail: dict[str, Any] | None=None) -> None:
    row = DesignAnalysisHistoryRow(id=new_id(), project_id=project_id, document_id=document_id, analysis_type=analysis_type or 'requirements', requirement_count=int(requirement_count or 0), mode=mode or 'heuristic', created_by=_actor(auth))
    payload = dict(detail or {})
    if requirement_ids is not None:
        payload.setdefault('requirement_ids', list(requirement_ids))
    row.detail = payload
    db.add(row)
    db.commit()

def _persist_business_rules(db: Session, *, project_id: str, drafts: list[dict[str, str]], auth: AuthContext, document_id: str='') -> list[dict[str, Any]]:
    """业务规则落知识库（category=business_rules），便于 RAG / 列表查询。"""
    saved: list[dict[str, Any]] = []
    for d in drafts:
        title = (d.get('name') or d.get('title') or '业务规则')[:512]
        condition = (d.get('condition') or '').strip()
        description = (d.get('description') or '').strip()
        content_parts = [p for p in (condition and f'条件：{condition}', description) if p]
        content = '\n'.join(content_parts) or title
        body = KnowledgeItemCreate(project_id=project_id, title=title, content=content[:8000], category='business_rules', source=f'document:{document_id}' if document_id else 'document_analyze', confirmed=False)
        out = knowledge_svc.create_knowledge_item(db, body, auth)
        saved.append({'id': out.id, 'name': out.title, 'title': out.title, 'description': out.content, 'type': d.get('type') or 'validation', 'condition': condition or '文档分析提取', 'priority': d.get('priority') or 'P2', 'knowledge_id': out.id})
    return saved

def _persist_test_points(db: Session, *, project_id: str, drafts: list[dict[str, str]]) -> list[dict[str, Any]]:
    saved: list[dict[str, Any]] = []
    for d in drafts:
        row = TestPointRow(id=new_id(), project_id=project_id, title=(d.get('name') or d.get('title') or '')[:512], description=(d.get('description') or '')[:8000], risk=(d.get('priority') or 'P2')[:32])
        db.add(row)
        saved.append({'id': row.id, 'name': row.title, 'description': row.description, 'type': d.get('type') or 'functional', 'priority': d.get('priority') or 'P2'})
    db.commit()
    return saved

def _create_requirements_from_drafts(db: Session, *, row: DesignDocumentRow, drafts: list[dict[str, str]], auth: AuthContext, max_requirements: int) -> list[RequirementOut]:
    created: list[RequirementOut] = []
    for i, d in enumerate(drafts[:max(1, max_requirements)], start=1):
        body = RequirementCreate(project_id=row.project_id, title=(d.get('title') or f'需求#{i}')[:200], content=(d.get('content') or '')[:8000], req_key=f'REQ-{row.id[:6]}-{i:02d}', req_type=d.get('req_type') or 'functional', priority=d.get('priority') or 'P2', source_document_id=row.id, source_excerpt=(d.get('content') or '')[:500])
        created.append(create_requirement(db, body, auth))
    return created
