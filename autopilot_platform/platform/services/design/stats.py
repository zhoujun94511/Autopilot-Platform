"""设计域统计（仪表盘只读）。"""
from __future__ import annotations
import csv
import io
import json
import zipfile
from datetime import datetime, timezone
from typing import Any
from fastapi.responses import StreamingResponse
from sqlalchemy import false as sql_false, func, select
from sqlalchemy.orm import Session
from autopilot_platform.platform.design.design_models import DesignDocumentRow, KnowledgeItemRow, LogicalCaseRow, RequirementRow
from autopilot_platform.platform.core.models import AuditLogRow
from autopilot_platform.platform.services.design.activity import action_label
from autopilot_platform.platform.services.design.cases import crud as design_svc
from autopilot_platform.platform.services.design.knowledge import crud as knowledge_svc
from autopilot_platform.platform.services.design.requirements import crud as req_svc
from autopilot_platform.platform.ai import ai_usage

def _stamp() -> str:
    return datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')

def design_domain_stats(db: Session, project_id: str | None=None, project_ids: list[str] | None=None) -> dict:
    if project_ids is not None:
        ids: list[str] | None = list(project_ids)
        display = (project_id or '').strip()
        if not display and ids and (len(ids) == 1):
            display = ids[0]
    elif (project_id or '').strip():
        pid = str(project_id).strip()
        ids = [pid]
        display = pid
    else:
        ids = None
        display = ''

    def _scope(q, column):
        if ids is None:
            return q
        if not ids:
            return q.where(sql_false())
        return q.where(column.in_(ids))

    def _count(model) -> int:
        q = select(func.count()).select_from(model)
        q = _scope(q, model.project_id)
        return int(db.scalar(q) or 0)
    auto_q = select(LogicalCaseRow.automation_status, func.count()).group_by(LogicalCaseRow.automation_status)
    review_q = select(LogicalCaseRow.review_status, func.count()).group_by(LogicalCaseRow.review_status)
    auto_q = _scope(auto_q, LogicalCaseRow.project_id)
    review_q = _scope(review_q, LogicalCaseRow.project_id)
    aq = select(AuditLogRow).where(AuditLogRow.action.like('design.%')).order_by(AuditLogRow.created_at.desc()).limit(80 if ids is not None else 30)
    action_counts: dict[str, int] = {}
    for row in db.scalars(aq).all():
        action = row.action or ''
        action_counts[action] = action_counts.get(action, 0) + 1
    try:
        token_summary = ai_usage.usage_summary(project_id=display)
        token_summary['design_audit_events'] = sum(action_counts.values())
        token_summary['top_actions'] = [(action_label(act), n) for act, n in sorted(action_counts.items(), key=lambda x: -x[1])[:8]]
    except Exception as exc:
        token_summary = {'total_tokens': None, 'note': f'usage 汇总不可用: {exc}', 'design_audit_events': sum(action_counts.values()), 'top_actions': [(action_label(act), n) for act, n in sorted(action_counts.items(), key=lambda x: -x[1])[:8]]}
    degraded_info = degraded_case_stats(db, ids)
    return {'project_id': display, 'requirements': _count(RequirementRow), 'documents': _count(DesignDocumentRow), 'knowledge': _count(KnowledgeItemRow), 'logical_cases': _count(LogicalCaseRow), 'by_automation_status': {str(k or ''): int(v) for k, v in db.execute(auto_q).all()}, 'by_review_status': {str(k or ''): int(v) for k, v in db.execute(review_q).all()}, 'ai_degraded': degraded_info, 'usage': {'action_counts': action_counts, 'period_note': 'recent design.* audit events'}, 'tokens': token_summary}

def degraded_case_stats(db: Session, ids: list[str] | None) -> dict[str, Any]:
    """统计 generation_metadata.degraded=true 的逻辑用例。"""
    if ids is not None and (not ids):
        return {'degraded_cases': 0, 'scanned': 0, 'logical_cases': 0, 'ratio': 0.0}
    q = select(LogicalCaseRow.generation_metadata_json)
    if ids is not None:
        q = q.where(LogicalCaseRow.project_id.in_(ids))
    q = q.where(LogicalCaseRow.generation_metadata_json.like('%degraded%'))
    scanned = 0
    degraded = 0
    for raw in db.scalars(q.limit(5000)).all():
        scanned += 1
        try:
            meta = json.loads(raw or '{}')
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(meta, dict) and bool(meta.get('degraded')):
            degraded += 1
    total_q = select(func.count()).select_from(LogicalCaseRow)
    if ids is not None:
        total_q = total_q.where(LogicalCaseRow.project_id.in_(ids))
    total_cases = int(db.scalar(total_q) or 0)
    ratio = round(degraded / total_cases, 4) if total_cases > 0 else 0.0
    return {'degraded_cases': degraded, 'scanned': scanned, 'logical_cases': total_cases, 'ratio': ratio, 'note': 'generation_metadata.degraded=true；启发式回退需人工审阅'}

def export_stats_csv(db: Session, *, project_id: str | None=None, project_ids: list[str] | None=None, include_token_metrics: bool=True) -> StreamingResponse:
    stats = design_domain_stats(db, project_id=project_id, project_ids=project_ids)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(['metric', 'value'])
    writer.writerow(['project_id', stats.get('project_id') or ''])
    writer.writerow(['requirements', stats.get('requirements', 0)])
    writer.writerow(['documents', stats.get('documents', 0)])
    writer.writerow(['knowledge', stats.get('knowledge', 0)])
    writer.writerow(['logical_cases', stats.get('logical_cases', 0)])
    for k, v in (stats.get('by_review_status') or {}).items():
        writer.writerow([f'review_status.{k}', v])
    for k, v in (stats.get('by_automation_status') or {}).items():
        writer.writerow([f'automation_status.{k}', v])
    for k, v in ((stats.get('usage') or {}).get('action_counts') or {}).items():
        writer.writerow([f'audit.{k}', v])
    if include_token_metrics:
        tokens = stats.get('tokens') or {}
        for key in ('day', 'calls', 'prompt_tokens', 'completion_tokens', 'cached_tokens', 'cache_miss_tokens', 'cache_write_tokens', 'cache_hit_rate', 'total_tokens', 'daily_budget', 'budget_remaining'):
            if key in tokens and tokens.get(key) is not None:
                writer.writerow([f'tokens.{key}', tokens.get(key)])
    data = ('\ufeff' + buf.getvalue()).encode('utf-8')
    return StreamingResponse(io.BytesIO(data), media_type='text/csv; charset=utf-8', headers={'Content-Disposition': f'attachment; filename="design_stats_{_stamp()}.csv"'})

def export_design_batch_zip(db: Session, *, project_id: str | None, project_ids: list[str] | None, config: dict[str, Any] | None=None) -> StreamingResponse:
    """打包导出用例/需求/知识（JSON），对齐 TP batch ZIP 语义的最小子集。"""
    cfg = config if isinstance(config, dict) else {}
    export_cases = bool(cfg.get('export_cases', True))
    export_requirements = bool(cfg.get('export_requirements', True))
    export_knowledge = bool(cfg.get('export_knowledge', True))
    export_documents = bool(cfg.get('export_documents', False))
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        meta = {'exported_at': datetime.now(timezone.utc).isoformat(), 'project_id': project_id or '', 'config': {'export_cases': export_cases, 'export_requirements': export_requirements, 'export_knowledge': export_knowledge, 'export_documents': export_documents}}
        zf.writestr('manifest.json', json.dumps(meta, ensure_ascii=False, indent=2))
        if export_cases:
            cases = design_svc.list_logical_cases(db, project_id=project_id, project_ids=project_ids)
            payload = [c.model_dump(mode='json') for c in cases]
            zf.writestr('logical_cases.json', json.dumps(payload, ensure_ascii=False, indent=2))
        if export_requirements:
            reqs = req_svc.list_requirements(db, project_id=project_id, project_ids=project_ids)
            payload = [r.model_dump(mode='json') for r in reqs]
            zf.writestr('requirements.json', json.dumps(payload, ensure_ascii=False, indent=2))
        if export_knowledge:
            items = knowledge_svc.list_knowledge_items(db, project_id=project_id, project_ids=project_ids)
            payload = [i.model_dump(mode='json') for i in items]
            zf.writestr('knowledge.json', json.dumps(payload, ensure_ascii=False, indent=2))
        if export_documents:
            # 延迟：默认关闭的 documents 导出才拉文档 CRUD
            from autopilot_platform.platform.services.design.documents import crud as doc_svc
            docs = doc_svc.list_documents(db, project_id=project_id, project_ids=project_ids)
            payload = [d.model_dump(mode='json') for d in docs]
            zf.writestr('documents.json', json.dumps(payload, ensure_ascii=False, indent=2))
    bio.seek(0)
    return StreamingResponse(bio, media_type='application/zip', headers={'Content-Disposition': f'attachment; filename="design_batch_{_stamp()}.zip"'})
