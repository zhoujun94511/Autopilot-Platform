"""Logical case services."""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor, as_completed
from autopilot_platform.platform.services.shared.billing_scope import project_org_id
import re
import uuid
from typing import Any
from sqlalchemy import select
from sqlalchemy.orm import Session
from autopilot_platform.platform.auth import AuthContext
from autopilot_platform.platform.ai import ai_usage
from autopilot_platform.platform.artifacts.quality_check import assess_logical_case
from autopilot_platform.platform.design.design_schemas import (
    IntentStep,
    LogicalCaseCreate,
    LogicalCaseGenerateIn,
    LogicalCaseOut,
)
from autopilot_platform.platform.design.design_models import TestPointRow
from autopilot_platform.platform.design.intent_normalize import texts_to_intent_steps
from autopilot_platform.platform.ops.runtime_config import (
    cfg_bool,
    cfg_int,
    design_max_workers,
    parallel_processing_enabled,
)
from autopilot_platform.platform.core.settings import database_url
from autopilot_platform.platform.services.design.cases.crud import create_logical_case, get_logical_case
from autopilot_platform.platform.services.design.cases.dedup import filter_duplicate_drafts

def _heuristic_generate(text: str, max_cases: int, module: str) -> list[LogicalCaseCreate]:
    """无 LLM 时的启发式草稿：按段落/编号拆分场景（仅逻辑步骤）。"""
    chunks = [c.strip() for c in re.split('\\n{2,}|\\r\\n{2,}', text or '') if c.strip()]
    if not chunks:
        chunks = [text.strip()] if text.strip() else ['未提供需求正文']
    out: list[LogicalCaseCreate] = []
    for i, chunk in enumerate(chunks[:max_cases], start=1):
        title_line = chunk.splitlines()[0][:80]
        steps = ['准备测试前置条件与测试数据', f'按需求执行：{title_line}', '观察系统反馈并记录结果']
        expected = ['行为符合需求描述', '无未处理异常或错误提示（除非负向场景）']
        intents = [IntentStep(**s) for s in texts_to_intent_steps(steps, expected)]
        out.append(LogicalCaseCreate(project_id='', title=f'场景{i}: {title_line}', case_key=f'GEN-{uuid.uuid4().hex[:8]}', description=chunk[:2000], preconditions=['环境可用', '测试账号就绪'], logical_steps=steps, intent_steps=intents, expected_results=expected, priority='P2', module=module, review_status='AI_DRAFT', automatability='NEEDS_DESIGN', generation_metadata={'generator': 'heuristic', 'degraded': True, 'note': '未调用 LLM；接入 design.ai 后可替换为模型生成'}))
    return out

def generate_logical_cases(db: Session, body: LogicalCaseGenerateIn, auth: AuthContext) -> list[LogicalCaseOut]:
    scope_token = ai_usage.set_ai_billing_scope(project_id=body.project_id, org_id=project_org_id(db, body.project_id))
    try:
        return _generate_logical_cases_inner(db, body, auth)
    finally:
        ai_usage.reset_ai_billing_scope(scope_token)

def _generate_logical_cases_inner(db: Session, body: LogicalCaseGenerateIn, auth: AuthContext) -> list[LogicalCaseOut]:
    rag_info: dict = {'context_text': '', 'hits': [], 'engine': 'none'}
    requirement_for_model = body.requirement_text
    if body.use_rag:
        # 延迟：RAG/embedding 为可选 design extra，仅 use_rag 时加载
        from autopilot_platform.platform.rag.service import retrieve_for_generation  # 延迟：RAG extra
        rag_info = retrieve_for_generation(db, project_id=body.project_id, query=body.requirement_text, confirmed_only=bool(getattr(body, 'confirmed_only', False)), score_threshold=getattr(body, 'score_threshold', None))
        tp_ctx = _test_points_context(db, body.project_id)
        parts = [p for p in (rag_info.get('context_text'), tp_ctx) if p]
        if parts:
            requirement_for_model = f'{body.requirement_text}\n\n' + '\n\n'.join(parts)
    db.commit()
    drafts: list[LogicalCaseCreate]
    degraded = False
    try:
        # 延迟：LLM 生成器仅走模型路径时加载
        from autopilot_platform.platform.ai.ai_case_generator import generate_logical_case_drafts  # 延迟：LLM
        drafts = generate_logical_case_drafts(requirement_for_model, max_cases=body.max_cases, module=body.module, rag_context='')
        generator = 'llm_v1'
    except Exception as exc:
        # 延迟：拒绝降级与 HTTP 错误仅失败分支需要
        from autopilot_platform.platform.ai.ai_config import ai_reject_degraded
        if ai_reject_degraded():
            from fastapi import HTTPException
            raise HTTPException(status_code=503, detail=f'AI 不可用且已启用 AP_AI_REJECT_DEGRADED，拒绝启发式假通草稿: {str(exc)[:300]}') from exc
        drafts = _heuristic_generate(body.requirement_text, body.max_cases, body.module)
        generator = 'heuristic'
        degraded = True
        for d in drafts:
            fb_meta: dict[str, Any] = dict(d.generation_metadata or {})
            fb_meta['llm_fallback_reason'] = str(exc)[:500]
            fb_meta['degraded'] = True
            fb_meta['generator'] = 'heuristic'
            d.generation_metadata = fb_meta
    drafts, dedup_meta = filter_duplicate_drafts(db, project_id=body.project_id, drafts=drafts)
    created: list[LogicalCaseOut] = []
    for draft in drafts:
        draft.project_id = body.project_id
        draft.source_requirement_ids = list(body.requirement_ids or [])
        meta: dict[str, Any] = dict(draft.generation_metadata or {})
        meta['generator'] = generator
        meta['degraded'] = bool(degraded)
        meta['content_dedup'] = dedup_meta
        if body.use_rag:
            meta['use_rag'] = True
            meta['rag'] = {'engine': rag_info.get('engine'), 'hit_count': len(rag_info.get('hits') or []), 'hits': rag_info.get('hits') or [], 'score_threshold': getattr(body, 'score_threshold', None), 'confirmed_only': bool(getattr(body, 'confirmed_only', False))}
        else:
            meta['use_rag'] = False
        quality: dict[str, Any] = assess_logical_case(title=draft.title, logical_steps=draft.logical_steps, expected_results=draft.expected_results, requirement_text=body.requirement_text, intent_steps=[s.model_dump() if hasattr(s, 'model_dump') else dict(s) for s in draft.intent_steps or []] or None)
        meta['quality'] = quality
        if quality.get('risk') == 'high' and draft.automatability == 'AUTOMATABLE':
            draft.automatability = 'NEEDS_DESIGN'
        if body.auto_approve:
            score = float(quality.get('score') or 0.0)
            risk = str(quality.get('risk') or '').lower()
            bucket = str(quality.get('review_bucket') or '')
            min_q = float(body.auto_approve_min_quality)
            if bucket == 'auto_approvable' and score >= min_q and (risk != 'high'):
                draft.review_status = 'APPROVED'
                draft.automation_status = 'PENDING_VERIFY'
                meta['auto_approved'] = True
                meta['auto_approve_min_quality'] = min_q
                meta['pending_first_run'] = True
            else:
                meta['auto_approved'] = False
                meta['auto_approve_skip_reason'] = f"bucket={bucket or 'n/a'} score={score} risk={risk or 'n/a'} min={min_q}"
        draft.generation_metadata = meta
        created.append(create_logical_case(db, draft, auth))
    return created

def _test_points_context(db: Session, project_id: str, *, limit: int=20) -> str:
    """把项目内测试点拼进生成上下文（comprehensive 产物回流）。"""
    pid = (project_id or '').strip()
    if not pid:
        return ''
    rows = list(db.scalars(select(TestPointRow).where(TestPointRow.project_id == pid).order_by(TestPointRow.created_at.desc()).limit(max(1, min(int(limit), 50)))).all())
    if not rows:
        return ''
    chunks = []
    for r in rows:
        title = (r.title or '').strip() or '测试点'
        desc = (r.description or '').strip()
        chunks.append(f'- {title}' + (f'：{desc[:400]}' if desc else ''))
    return '以下为项目已落库测试点，生成用例时请覆盖相关场景：\n' + '\n'.join(chunks)

def regenerate_logical_case(db: Session, case_id: str, auth: AuthContext, *, max_cases: int | None=None, use_rag: bool | None=None) -> list[LogicalCaseOut]:
    """基于已有用例内容重新生成（不删除原用例，对齐 TP regenerate 语义）。"""
    existing = get_logical_case(db, case_id)
    parts = [f'标题: {existing.title}', f'描述: {existing.description}' if existing.description else '', '前置条件:\n' + '\n'.join(existing.preconditions or []), '步骤:\n' + '\n'.join(existing.logical_steps or []), '预期:\n' + '\n'.join(existing.expected_results or [])]
    requirement_text = '\n\n'.join((p for p in parts if p and str(p).strip()))
    if not requirement_text.strip():
        requirement_text = existing.title or '重新生成用例'
    cap = int(max_cases) if max_cases is not None else cfg_int('AP_MAX_CASE_NUM', '5', minimum=1)
    cap = max(1, min(cap, 20))
    rag = bool(use_rag) if use_rag is not None else cfg_bool('AP_ENABLE_CASE_GENERATION_RAG', '1')
    body = LogicalCaseGenerateIn(project_id=existing.project_id, requirement_text=requirement_text, requirement_ids=list(existing.source_requirement_ids or []), max_cases=cap, module=existing.module or '', use_rag=rag)
    created = generate_logical_cases(db, body, auth)
    for c in created:
        meta = dict(c.generation_metadata or {})
        meta['regenerated_from'] = case_id
        c.generation_metadata = meta
    return created

def batch_generate_logical_cases(db: Session, body: Any, auth: AuthContext) -> dict:
    """多需求批量生成。

    process_mode=parallel 且 AP_ENABLE_PARALLEL_PROCESSING=1 时：
    每条需求独立 Session 并发生成（SQLite 已 check_same_thread=False）；
    否则顺序执行。
    """
    reqs = [str(r).strip() for r in getattr(body, 'requirements', None) or [] if str(r).strip()]
    if not reqs:
        raise ValueError('requirements 不能为空')
    mode = str(getattr(body, 'process_mode', None) or 'sequential').strip().lower()
    if mode not in {'sequential', 'parallel'}:
        mode = 'sequential'
    want_parallel = mode == 'parallel' and parallel_processing_enabled() and (len(reqs) > 1)
    workers = min(design_max_workers(), len(reqs))
    sqlite_fallback = ''
    try:
        if want_parallel and database_url().startswith('sqlite'):
            want_parallel = False
            sqlite_fallback = 'sqlite_single_writer'
    except (ImportError, RuntimeError, TypeError, ValueError):
        sqlite_fallback = ''

    def _build_gin(requirement_text: str) -> LogicalCaseGenerateIn:
        return LogicalCaseGenerateIn(project_id=body.project_id, requirement_text=requirement_text, max_cases=int(getattr(body, 'case_count_per_req', 3) or 3), module=str(getattr(body, 'module', '') or ''), use_rag=bool(getattr(body, 'use_rag', False)), auto_approve=bool(getattr(body, 'auto_approve', False)), auto_approve_min_quality=float(getattr(body, 'auto_approve_min_quality', 0.85) or 0.85), confirmed_only=bool(getattr(body, 'confirmed_only', False)), score_threshold=getattr(body, 'score_threshold', None))

    def _pack(req_index: int, requirement_text: str, cases: list[LogicalCaseOut] | None=None, exc: Exception | None=None) -> dict:
        if exc is not None:
            return {'success': False, 'requirement_id': f'req-{req_index + 1}', 'requirement_text': requirement_text[:200], 'cases': [], 'count': 0, 'error': str(exc), 'degraded': False}
        case_dumps = [c.model_dump(mode='json') for c in cases or []]
        any_degraded = any((bool((c.get('generation_metadata') or {}).get('degraded')) or str((c.get('generation_metadata') or {}).get('generator') or '').startswith('heuristic') for c in case_dumps))
        return {'success': True, 'requirement_id': f'req-{req_index + 1}', 'requirement_text': requirement_text[:200], 'cases': case_dumps, 'count': len(cases or []), 'degraded': any_degraded, 'generator': 'heuristic' if any_degraded else (case_dumps[0].get('generation_metadata') or {}).get('generator') if case_dumps else 'llm_v1'}

    def _run_one(req_index: int, requirement_text: str, session: Session) -> dict:
        try:
            cases = generate_logical_cases(session, _build_gin(requirement_text), auth)
            return _pack(req_index, requirement_text, cases=cases)
        except Exception as exc:
            return _pack(req_index, requirement_text, exc=exc)
    results: list[dict] = [{} for _ in reqs]
    executed_mode = 'sequential'
    parallel_fallback = ''
    if want_parallel:
        # 延迟：仅并行模式才需要独立 Session 工厂
        from autopilot_platform.platform.core.db import session_factory
        factory = session_factory()
        if factory is None:
            parallel_fallback = 'session_factory_missing'
            for req_idx, req_text in enumerate(reqs):
                results[req_idx] = _run_one(req_idx, req_text, db)
        else:
            executed_mode = 'parallel'

            def _worker(pair: tuple[int, str]) -> tuple[int, dict]:
                w_idx, w_text = pair
                s = factory()
                try:
                    return w_idx, _run_one(w_idx, w_text, s)
                finally:
                    s.close()
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = [pool.submit(_worker, (i, t)) for i, t in enumerate(reqs)]
                for fut in as_completed(futures):
                    done_idx, packed = fut.result()
                    results[done_idx] = packed
    else:
        if mode == 'parallel' and (not parallel_processing_enabled()):
            parallel_fallback = 'parallel_disabled'
        for req_idx, req_text in enumerate(reqs):
            results[req_idx] = _run_one(req_idx, req_text, db)
    if executed_mode == 'parallel':
        note = f'并行生成：max_workers={workers}（每需求独立 Session）'
    elif parallel_fallback == 'session_factory_missing':
        note = '并行开关已开但 session_factory 未就绪，已回退顺序执行'
    elif sqlite_fallback == 'sqlite_single_writer':
        note = '请求 parallel，但当前是 SQLite 单写者，已顺序执行'
    elif parallel_fallback == 'parallel_disabled':
        note = '请求 parallel，但 AP_ENABLE_PARALLEL_PROCESSING=0，已顺序执行'
    else:
        note = '顺序写入数据库'
    total = sum((int(r.get('count') or 0) for r in results))
    ok = sum((1 for r in results if r.get('success')))
    degraded = any((bool(r.get('degraded')) for r in results))
    return {'success': ok == len(results), 'total_cases': total, 'degraded': degraded, 'generator': 'heuristic' if degraded else 'llm_v1', 'results': results, 'summary': {'requirement_count': len(reqs), 'success_count': ok, 'failed_count': len(reqs) - ok, 'process_mode': mode, 'executed_mode': executed_mode, 'max_workers': workers if executed_mode == 'parallel' else 1, 'parallel_enabled': parallel_processing_enabled(), 'note': note}, 'message': f'生成完成：{total} 条用例（成功需求 {ok}/{len(reqs)}）'}
