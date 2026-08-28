"""设计域审计 → 仪表盘「近期活动」可读条目。"""
from __future__ import annotations
import re
from datetime import datetime, timezone
from typing import Any
from sqlalchemy import select
from sqlalchemy.orm import Session
from autopilot_platform.platform.core.models import AuditLogRow
from autopilot_platform.platform.design.design_models import DesignDocumentRow, KnowledgeItemRow, LogicalCaseRow, RequirementRow
_ACTION_LABELS: dict[str, str] = {'design.logical_case.create': '创建意图用例', 'design.logical_case.update': '更新意图用例', 'design.logical_case.delete': '删除意图用例', 'design.logical_case.generate': 'AI 生成用例', 'design.logical_case.batch_generate': '批量生成用例', 'design.logical_case.batch_delete': '批量删除用例', 'design.logical_case.regenerate': '重新生成用例', 'design.logical_case.enqueue_job': '提交远程批跑', 'design.requirement.create': '创建需求', 'design.requirement.update': '更新需求', 'design.requirement.delete': '删除需求', 'design.requirement.import': '导入需求', 'design.requirement.batch_delete': '批量删除需求', 'design.knowledge.create': '创建知识条目', 'design.knowledge.update': '更新知识条目', 'design.knowledge.delete': '删除知识条目', 'design.knowledge.import': '导入知识库', 'design.knowledge.rebuild': '重建知识索引', 'design.knowledge.batch_delete': '批量删除知识', 'design.document.upload': '上传需求文档', 'design.document.import': '导入文档', 'design.document.delete': '删除文档', 'design.document.batch_delete': '批量删除文档', 'design.document.analyze': '解析需求文档', 'design.batch_export': '导出设计域数据', 'design.config_update': '更新设计配置', 'design.config_import': '导入设计配置', 'design.experimental_action.confirm': '确认实验操作'}
_ACTION_CATEGORY: dict[str, str] = {'design.logical_case.generate': 'generate', 'design.logical_case.batch_generate': 'generate', 'design.logical_case.regenerate': 'generate', 'design.logical_case.enqueue_job': 'run', 'design.logical_case.delete': 'delete', 'design.logical_case.batch_delete': 'delete', 'design.requirement.delete': 'delete', 'design.requirement.batch_delete': 'delete', 'design.knowledge.delete': 'delete', 'design.knowledge.batch_delete': 'delete', 'design.document.delete': 'delete', 'design.document.batch_delete': 'delete', 'design.requirement.import': 'import', 'design.knowledge.import': 'import', 'design.document.import': 'import', 'design.document.upload': 'import', 'design.config_import': 'import', 'design.batch_export': 'export'}
_RESOURCE_LABELS: dict[str, str] = {'logical_case': '用例', 'requirement': '需求', 'knowledge': '知识', 'document': '文档', 'project': '项目', 'job': '任务'}
_KV_RE = re.compile('(\\w+)=([^\\s]+)')

def _short_id(value: str, *, head: int=8, tail: int=4) -> str:
    text = (value or '').strip()
    if not text:
        return ''
    if len(text) <= head + tail + 1:
        return text
    return f'{text[:head]}…{text[-tail:]}'

def _parse_detail_kv(detail: str) -> dict[str, str]:
    return {m.group(1): m.group(2) for m in _KV_RE.finditer(detail or '')}

def _format_time_display(when: datetime | None) -> str:
    if when is None:
        return ''
    try:
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        local = when.astimezone()
        now = datetime.now(local.tzinfo)
        delta = now - local
        if delta.total_seconds() < 60:
            return '刚刚'
        if delta.total_seconds() < 3600:
            mins = int(delta.total_seconds() // 60)
            return f'{mins} 分钟前'
        if delta.days == 0:
            return local.strftime('%H:%M')
        if delta.days == 1:
            return f"昨天 {local.strftime('%H:%M')}"
        if delta.days < 7:
            return f'{delta.days} 天前'
        return local.strftime('%Y-%m-%d %H:%M')
    except (TypeError, ValueError, OSError):
        return ''

def _resource_summary(resource_type: str, resource_id: str) -> str:
    rt = (resource_type or '').strip()
    rid = (resource_id or '').strip()
    if not rid:
        return ''
    label = _RESOURCE_LABELS.get(rt, rt or '资源')
    return f'{label} {_short_id(rid)}'

def _detail_summary(action: str, detail: str, resource_type: str, resource_id: str) -> str:
    raw = (detail or '').strip()
    if raw and raw != action:
        kv = _parse_detail_kv(raw)
        if 'count' in kv:
            n = kv['count']
            return f'生成 {n} 条用例' if action.endswith('.generate') or 'generate' in action else f'共 {n} 条'
        if 'deleted' in kv or 'failed' in kv:
            parts = []
            if 'deleted' in kv:
                parts.append(f"删除 {kv['deleted']} 条")
            if 'failed' in kv and kv['failed'] not in ('0', ''):
                parts.append(f"失败 {kv['failed']} 条")
            if parts:
                return ' · '.join(parts)
        if 'project' in kv and 'artifact' in kv:
            return f"项目 {kv['project']} · 制品 {_short_id(kv['artifact'])}"
        if 'project' in kv:
            return f"项目 {kv['project']}"
        if len(raw) <= 120 and (not raw.startswith('design.')):
            return raw
    return _resource_summary(resource_type, resource_id)

def format_design_activity(row: AuditLogRow) -> dict[str, Any]:
    action = (row.action or '').strip()
    detail = (row.detail or '').strip()
    resource_type = (row.resource_type or '').strip()
    resource_id = (row.resource_id or '').strip()
    label = _ACTION_LABELS.get(action, action.replace('design.', '').replace('_', ' ').replace('.', ' · '))
    summary = _detail_summary(action, detail, resource_type, resource_id)
    if not summary:
        summary = '设计域操作'
    when = row.created_at
    return {'id': row.id, 'type': action, 'label': label, 'summary': summary, 'message': summary, 'category': _ACTION_CATEGORY.get(action, 'edit'), 'actor': (row.actor or '').strip(), 'resource_type': resource_type, 'resource_id': resource_id, 'time': when.isoformat() if when else '', 'time_display': _format_time_display(when)}

def _project_from_row(row: AuditLogRow, resource_projects: dict[tuple[str, str], str]) -> str:
    rt = (row.resource_type or '').strip()
    rid = (row.resource_id or '').strip()
    if rt == 'project' and rid:
        return rid
    if rt and rid:
        pid = resource_projects.get((rt, rid), '')
        if pid:
            return pid
    detail = (row.detail or '').strip()
    kv = _parse_detail_kv(detail)
    return (kv.get('project') or '').strip()

def _load_resource_projects(db: Session, rows: list[AuditLogRow]) -> dict[tuple[str, str], str]:
    by_type: dict[str, set[str]] = {}
    for row in rows:
        rt = (row.resource_type or '').strip()
        rid = (row.resource_id or '').strip()
        if rt and rid:
            by_type.setdefault(rt, set()).add(rid)
    out: dict[tuple[str, str], str] = {}
    case_ids = by_type.get('logical_case') or set()
    if case_ids:
        q = select(LogicalCaseRow.id, LogicalCaseRow.project_id).where(LogicalCaseRow.id.in_(case_ids))
        for cid, pid in db.execute(q).all():
            out['logical_case', str(cid)] = str(pid or '')
    req_ids = by_type.get('requirement') or set()
    if req_ids:
        q = select(RequirementRow.id, RequirementRow.project_id).where(RequirementRow.id.in_(req_ids))
        for rid, pid in db.execute(q).all():
            out['requirement', str(rid)] = str(pid or '')
    know_ids = by_type.get('knowledge') or set()
    if know_ids:
        q = select(KnowledgeItemRow.id, KnowledgeItemRow.project_id).where(KnowledgeItemRow.id.in_(know_ids))
        for kid, pid in db.execute(q).all():
            out['knowledge', str(kid)] = str(pid or '')
    doc_ids = by_type.get('document') or set()
    if doc_ids:
        q = select(DesignDocumentRow.id, DesignDocumentRow.project_id).where(DesignDocumentRow.id.in_(doc_ids))
        for did, pid in db.execute(q).all():
            out['document', str(did)] = str(pid or '')
    return out

def recent_design_activities(db: Session, *, project_ids: list[str] | None=None, limit: int=4) -> tuple[list[dict[str, Any]], bool]:
    """拉取近期设计域活动预览（仪表盘用，非完整审计列表）。"""
    fetch_limit = 80 if project_ids is not None else max(limit * 3, 20)
    aq = select(AuditLogRow).where(AuditLogRow.action.like('design.%')).order_by(AuditLogRow.created_at.desc()).limit(fetch_limit)
    rows = list(db.scalars(aq).all())
    if project_ids is not None:
        allowed = {p.strip() for p in project_ids if (p or '').strip()}
        resource_projects = _load_resource_projects(db, rows)
        scoped: list[AuditLogRow] = []
        for row in rows:
            pid = _project_from_row(row, resource_projects)
            if pid and pid in allowed:
                scoped.append(row)
            elif not pid and (not allowed):
                scoped.append(row)
        rows = scoped
    has_more = len(rows) > limit
    return [format_design_activity(row) for row in rows[:limit]], has_more

def action_label(action: str) -> str:
    return _ACTION_LABELS.get((action or '').strip(), action)
