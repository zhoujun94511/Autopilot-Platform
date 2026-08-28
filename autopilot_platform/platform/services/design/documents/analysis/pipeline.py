"""Document analysis services."""
from __future__ import annotations
import logging
from typing import Any
from sqlalchemy.orm import Session
from autopilot_platform.platform.auth import AuthContext
from autopilot_platform.platform.design.design_schemas import RequirementOut
logger = logging.getLogger(__name__)
from autopilot_platform.platform.services.design.documents.crud import get_document
from autopilot_platform.platform.services.design.documents.analysis.heuristics import _normalize_analysis_type, _heuristic_requirement_drafts, _heuristic_test_points, _heuristic_business_rules
from autopilot_platform.platform.services.design.documents.analysis.persist import _record_analysis, _persist_business_rules, _persist_test_points, _create_requirements_from_drafts
from autopilot_platform.platform.services.shared.billing_scope import fill_scope, project_org_id
from autopilot_platform.platform.ai import ai_usage

def analyze_document(db: Session, document_id: str, auth: AuthContext, *, max_requirements: int=20, use_llm: bool=True, analysis_type: str='requirements') -> dict[str, Any]:
    """按 analysis_type 分流；全程置计费作用域，避免绕过项目/组织日配额。"""
    atype = _normalize_analysis_type(analysis_type)
    row = get_document(db, document_id)
    text = (row.content_text or '').strip()
    if not text:
        raise ValueError('文档无文本内容可解析')
    billing_project_id, billing_org_id = fill_scope(row.project_id or '', project_org_id(db, row.project_id or ''))
    scope_token = ai_usage.set_ai_billing_scope(project_id=billing_project_id, org_id=billing_org_id)
    try:
        return _analyze_document_inner(db, row, auth, atype=atype, text=text, max_requirements=max_requirements, use_llm=use_llm)
    finally:
        ai_usage.reset_ai_billing_scope(scope_token)

def _analyze_document_inner(db: Session, row: Any, auth: AuthContext, *, atype: str, text: str, max_requirements: int, use_llm: bool) -> dict[str, Any]:
    requirements: list[RequirementOut] = []
    test_points: list[dict[str, Any]] = []
    business_rules: list[dict[str, Any]] = []
    modes: list[str] = []

    def _run_requirements() -> None:
        nonlocal requirements
        drafts: list[dict[str, str]] = []
        analyze_mode = 'heuristic'
        if use_llm:
            try:
                # 延迟：文档 LLM 分析仅 use_llm 时加载
                from autopilot_platform.platform.ai.ai_requirements_analyze import analyze_document_to_requirement_drafts
                drafts = analyze_document_to_requirement_drafts(text, max_requirements=max_requirements)
                analyze_mode = 'llm'
            except Exception as llm_exc:
                from autopilot_platform.platform.ai.ai_config import ai_reject_degraded
                logger.info('LLM requirements analyze fallback: %s', llm_exc)
                if ai_reject_degraded():
                    raise RuntimeError(f'AI unavailable (AP_AI_REJECT_DEGRADED): {llm_exc}') from llm_exc
                drafts = []
        if not drafts:
            drafts = _heuristic_requirement_drafts(text, max_requirements=max_requirements)
            analyze_mode = 'heuristic'
        modes.append(f'requirements:{analyze_mode}')
        requirements = _create_requirements_from_drafts(db, row=row, drafts=drafts, auth=auth, max_requirements=max_requirements)

    def _run_test_points() -> None:
        nonlocal test_points
        drafts: list[dict[str, str]] = []
        analyze_mode = 'heuristic'
        if use_llm:
            try:
                # 延迟：文档 LLM 分析仅 use_llm 时加载
                from autopilot_platform.platform.ai.ai_requirements_analyze import analyze_document_to_test_point_drafts
                drafts = analyze_document_to_test_point_drafts(text, max_items=min(max_requirements, 20))
                analyze_mode = 'llm'
            except Exception as llm_exc:
                from autopilot_platform.platform.ai.ai_config import ai_reject_degraded
                logger.info('LLM test_points analyze fallback: %s', llm_exc)
                if ai_reject_degraded():
                    raise RuntimeError(f'AI unavailable (AP_AI_REJECT_DEGRADED): {llm_exc}') from llm_exc
                drafts = []
        if not drafts:
            drafts = _heuristic_test_points(text, max_items=min(max_requirements, 20))
            analyze_mode = 'heuristic'
        modes.append(f'test_points:{analyze_mode}')
        test_points = _persist_test_points(db, project_id=row.project_id, drafts=drafts)

    def _run_business_rules() -> None:
        nonlocal business_rules
        drafts: list[dict[str, str]] = []
        analyze_mode = 'heuristic'
        if use_llm:
            try:
                # 延迟：文档 LLM 分析仅 use_llm 时加载
                from autopilot_platform.platform.ai.ai_requirements_analyze import analyze_document_to_business_rule_drafts
                drafts = analyze_document_to_business_rule_drafts(text, max_items=min(max_requirements, 20))
                analyze_mode = 'llm'
            except Exception as llm_exc:
                from autopilot_platform.platform.ai.ai_config import ai_reject_degraded
                logger.info('LLM business_rules analyze fallback: %s', llm_exc)
                if ai_reject_degraded():
                    raise RuntimeError(f'AI unavailable (AP_AI_REJECT_DEGRADED): {llm_exc}') from llm_exc
                drafts = []
        if not drafts:
            drafts = _heuristic_business_rules(text, max_items=min(max_requirements, 20))
            analyze_mode = 'heuristic'
        modes.append(f'business_rules:{analyze_mode}')
        business_rules = _persist_business_rules(db, project_id=row.project_id, drafts=drafts, auth=auth, document_id=row.id)
    part_failures: list[str] = []
    if atype == 'requirements':
        _run_requirements()
    elif atype == 'test_points':
        _run_test_points()
    elif atype == 'business_rules':
        _run_business_rules()
    else:
        try:
            _run_requirements()
        except Exception as part_exc:
            logger.info('comprehensive requirements failed: %s', part_exc)
            part_failures.append(f'requirements:{part_exc}')
            modes.append('requirements:failed')
        try:
            _run_test_points()
        except Exception as part_exc:
            logger.info('comprehensive test_points failed: %s', part_exc)
            part_failures.append(f'test_points:{part_exc}')
            modes.append('test_points:failed')
        try:
            _run_business_rules()
        except Exception as part_exc:
            logger.info('comprehensive business_rules failed: %s', part_exc)
            part_failures.append(f'business_rules:{part_exc}')
            modes.append('business_rules:failed')
    mode = '+'.join(modes) if modes else 'heuristic'
    degraded = any((m.endswith(':failed') for m in modes)) or (bool(use_llm) and any((m.endswith(':heuristic') for m in modes)))
    total = len(requirements) + len(test_points) + len(business_rules)
    summary = {'requirements_count': len(requirements), 'test_points_count': len(test_points), 'business_rules_count': len(business_rules), 'total_count': total}
    message = {'requirements': f'成功分析出 {len(requirements)} 个需求', 'test_points': f'成功提取 {len(test_points)} 个测试点', 'business_rules': f'成功提取 {len(business_rules)} 个业务规则', 'comprehensive': f'综合分析完成：需求 {len(requirements)}，测试点 {len(test_points)}，业务规则 {len(business_rules)}'}.get(atype, f'分析完成 {total} 项')
    try:
        _record_analysis(db, project_id=row.project_id, document_id=row.id, analysis_type=atype, requirement_count=len(requirements), mode=mode, auth=auth, requirement_ids=[c.id for c in requirements], detail={'test_points_count': len(test_points), 'business_rules_count': len(business_rules), 'test_point_ids': [t.get('id') for t in test_points if t.get('id')], 'business_rules': business_rules[:50], 'degraded': degraded, 'part_failures': part_failures if atype == 'comprehensive' else []})
    except Exception as exc:
        logger.debug('analysis history record skipped: %s', exc)
    generator = 'heuristic' if degraded or not use_llm else 'llm'
    if degraded:
        message = f'{message}（⚠ AI 已降级为启发式，degraded=true，mode={mode}；请人工审阅）'
    elif not use_llm:
        message = f'{message}（未启用 LLM，generator=heuristic）'
    if atype == 'comprehensive' and part_failures:
        message += f'；子分析失败 {len(part_failures)} 项'
    return {'success': True, 'message': message, 'analysis_type': atype, 'mode': mode, 'degraded': degraded, 'generator': generator, 'part_failures': part_failures if atype == 'comprehensive' else [], 'requirements': [r.model_dump(mode='json') for r in requirements], 'test_points': test_points, 'business_rules': business_rules, 'summary': summary}

def analyze_document_to_requirements(db: Session, document_id: str, auth: AuthContext, *, max_requirements: int=20, use_llm: bool=True, analysis_type: str='requirements') -> list[RequirementOut]:
    """兼容旧调用：返回入库的需求列表（非 requirements 类型时可能为空）。"""
    result = analyze_document(db, document_id, auth, max_requirements=max_requirements, use_llm=use_llm, analysis_type=analysis_type)
    from autopilot_platform.platform.design.design_schemas import RequirementOut as ReqOut
    out: list[RequirementOut] = []
    for item in result.get('requirements') or []:
        if isinstance(item, dict):
            out.append(ReqOut.model_validate(item))
    return out
