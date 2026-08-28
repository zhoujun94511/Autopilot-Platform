"""设计域 Chat 实验动作：提议 → 用户确认 → 执行（最小可用子集）。"""
from __future__ import annotations
import re
import threading
import time
import uuid
from typing import Any
from sqlalchemy.orm import Session
from autopilot_platform.platform.auth import AuthContext
from autopilot_platform.platform.ops.runtime_config import cfg_bool
from autopilot_platform.platform.services.design.cases import crud as design_svc
from autopilot_platform.platform.services.design import access as design_access
from autopilot_platform.platform.design.design_schemas import LogicalCaseGenerateIn
_lock = threading.RLock()
_PENDING: dict[str, dict[str, Any]] = {}
_TTL_SEC = 600

def experimental_actions_enabled() -> bool:
    return cfg_bool('AP_ENABLE_EXPERIMENTAL_ACTIONS', '0')

def _purge_expired() -> None:
    now = time.time()
    expired = [k for k, v in _PENDING.items() if now - float(v.get('created_at') or 0) > _TTL_SEC]
    for k in expired:
        _PENDING.pop(k, None)

def propose_from_query(query: str, *, project_id: str='', session_id: str='', force: bool=False, created_by: str='') -> dict[str, Any] | None:
    """启发式识别动作意图；无法识别时返回 None（走普通对话）。

    ``force=True``（Chat mode=action）仅表示主动识别动作；全局开关关闭时仍允许
    显式动作模式，但 pending 会记录提议者，确认阶段必须同人。
    """
    if not force and (not experimental_actions_enabled()):
        return None
    text = (query or '').strip()
    if not text:
        return None
    m_del = re.search('(?:删除|删掉|移除)\\s*(?:逻辑)?用例\\s*[：:\\s]*([A-Za-z0-9_\\-]{6,})', text)
    if m_del:
        case_id = m_del.group(1)
        return _park_plan(intent='delete_logical_case', tool_name='delete_logical_case', risk_level='high', args={'case_id': case_id, 'project_id': project_id}, reason=f'将删除逻辑用例 {case_id}', session_id=session_id, query=text, created_by=created_by, forced=force)
    if re.search('(生成|创建).{0,6}(用例|测试用例)', text) or re.search('(用例|测试用例).{0,6}(生成|创建)', text):
        req = re.sub('^(请)?(帮我)?(根据|基于)?(以下)?(需求)?\\s*', '', text, flags=re.IGNORECASE)
        req = re.sub('(生成|创建)\\s*(逻辑)?(测试)?用例[:：]?\\s*', '', req, flags=re.IGNORECASE).strip()
        if len(req) < 8:
            req = text
        return _park_plan(intent='generate_logical_cases', tool_name='generate_logical_cases', risk_level='medium', args={'project_id': project_id, 'requirement_text': req[:8000], 'max_cases': 3}, reason='将根据对话内容生成逻辑用例草稿', session_id=session_id, query=text, created_by=created_by, forced=force)
    return None

def _park_plan(*, intent: str, tool_name: str, risk_level: str, args: dict[str, Any], reason: str, session_id: str, query: str, created_by: str='', forced: bool=False) -> dict[str, Any]:
    execution_id = uuid.uuid4().hex
    plan = {'intent': intent, 'tool_name': tool_name, 'risk_level': risk_level, 'args': args, 'requires_confirmation': True, 'reason': reason}
    owner = (created_by or '').strip()
    with _lock:
        _purge_expired()
        _PENDING[execution_id] = {'plan': plan, 'session_id': session_id, 'query': query, 'created_at': time.time(), 'status': 'needs_confirmation', 'created_by': owner, 'forced': bool(forced)}
    return {'success': True, 'status': 'needs_confirmation', 'execution_id': execution_id, 'message': '需要确认后才能执行该动作', 'plan': plan, 'action_plan': plan}

def _actor_matches(pending: dict[str, Any], auth: AuthContext) -> bool:
    owner = str(pending.get('created_by') or '').strip()
    if not owner:
        return False
    actors = {(auth.username or '').strip(), (auth.user_id or '').strip()} - {''}
    return owner in actors

def confirm_action(db: Session, auth: AuthContext, *, execution_id: str, metadata: dict[str, Any] | None=None) -> dict[str, Any]:
    eid = (execution_id or '').strip()
    with _lock:
        _purge_expired()
        pending = _PENDING.get(eid)
        if pending is None:
            pending = None
        elif not _actor_matches(pending, auth):
            return {'success': False, 'status': 'failed', 'message': '只能由提议该动作的用户确认', 'error': 'forbidden'}
        else:
            pending = _PENDING.pop(eid, None)
    if not pending:
        return {'success': False, 'status': 'failed', 'message': '确认已过期或不存在', 'error': 'not_found'}
    plan = pending.get('plan') or {}
    tool = plan.get('tool_name') or ''
    args = dict(plan.get('args') or {})
    if isinstance(metadata, dict):
        if metadata.get('project_id'):
            args['project_id'] = metadata['project_id']
    try:
        output = _execute_tool(db, auth, tool, args)
    except Exception as exc:
        return {'success': False, 'status': 'failed', 'execution_id': eid, 'message': str(exc), 'error': 'execution_failed', 'plan': plan}
    return {'success': True, 'status': 'completed', 'execution_id': eid, 'message': '动作已执行', 'plan': plan, 'tool_output': output}

def cancel_action(execution_id: str, *, reason: str='', auth: AuthContext | None=None) -> dict[str, Any]:
    eid = (execution_id or '').strip()
    with _lock:
        pending = _PENDING.get(eid)
        if pending is None:
            return {'success': False, 'status': 'failed', 'message': '无可取消的动作'}
        if auth is not None and (not _actor_matches(pending, auth)):
            return {'success': False, 'status': 'failed', 'message': '只能由提议该动作的用户取消', 'error': 'forbidden'}
        pending = _PENDING.pop(eid, None)
    if not pending:
        return {'success': False, 'status': 'failed', 'message': '无可取消的动作'}
    return {'success': True, 'status': 'cancelled', 'execution_id': eid, 'message': reason or '已取消', 'plan': pending.get('plan')}

def _execute_tool(db: Session, auth: AuthContext, tool: str, args: dict[str, Any]) -> Any:
    if tool == 'delete_logical_case':
        case_id = str(args.get('case_id') or '').strip()
        if not case_id:
            raise ValueError('缺少 case_id')
        existing = design_svc.get_logical_case(db, case_id)
        design_access.ensure_row_project_write(db, auth, existing.project_id)
        design_svc.delete_logical_case(db, case_id, auth)
        return {'deleted': case_id, 'title': existing.title}
    if tool == 'generate_logical_cases':
        project_id = str(args.get('project_id') or '').strip()
        if not project_id:
            raise ValueError('缺少 project_id，请先选择项目后再确认')
        design_access.ensure_project_write(db, auth, project_id)
        text = str(args.get('requirement_text') or '').strip()
        if not text:
            raise ValueError('缺少 requirement_text')
        # 延迟：LLM 生成栈仅「生成用例」动作需要
        from autopilot_platform.platform.services.design.cases import generation as generation_svc
        body = LogicalCaseGenerateIn(project_id=project_id, requirement_text=text, max_cases=int(args.get('max_cases') or 3), use_rag=bool(args.get('use_rag', True)))
        created = generation_svc.generate_logical_cases(db, body, auth)
        dumps = [c.model_dump(mode='json') for c in created]
        degraded = any((bool((c.get('generation_metadata') or {}).get('degraded')) or str((c.get('generation_metadata') or {}).get('generator') or '').startswith('heuristic') for c in dumps))
        dedup_dropped = sum((int(((c.get('generation_metadata') or {}).get('content_dedup') or {}).get('dropped') or 0) for c in dumps))
        return {'count': len(created), 'case_ids': [c.logical_case_id for c in created], 'titles': [c.title for c in created], 'degraded': degraded, 'dedup_dropped': dedup_dropped, 'generator': 'heuristic' if degraded else 'llm_v1'}
    raise ValueError(f'未知工具: {tool}')
