"""Design document services."""
from __future__ import annotations
import logging
from pathlib import Path
from typing import Any
from sqlalchemy.orm import Session
from autopilot_platform.platform.auth import AuthContext
from autopilot_platform.platform.design.design_schemas import DesignDocumentOut, RequirementOut
logger = logging.getLogger(__name__)
from autopilot_platform.platform.services.design.documents.crud import save_document
from autopilot_platform.platform.services.design.documents.analysis.pipeline import analyze_document

def import_documents(db: Session, *, project_id: str, files: list[tuple[str, bytes]], auth: AuthContext, auto_analyze: bool=False, max_requirements: int=20, use_llm: bool=True, analysis_type: str='requirements') -> dict[str, Any]:
    """多文件上传（对齐 TestPilot DocumentsUpload）；可选上传后自动分析入库。"""
    pid = (project_id or '').strip()
    if not pid:
        raise ValueError('project_id 不能为空')
    if not files:
        raise ValueError('请至少选择一个文件')
    results: list[dict[str, Any]] = []
    docs_out: list[DesignDocumentOut] = []
    reqs_out: list[RequirementOut] = []
    for filename, raw in files:
        name = Path(filename or 'upload.bin').name
        try:
            doc = save_document(db, project_id=pid, filename=name, data=raw, auth=auth)
            docs_out.append(doc)
            analyzed = 0
            degraded = False
            analyze_mode = ''
            if auto_analyze:
                analyzed_result = analyze_document(db, doc.id, auth, max_requirements=max_requirements, use_llm=use_llm, analysis_type=analysis_type)
                for item in analyzed_result.get('requirements') or []:
                    if isinstance(item, dict):
                        try:
                            reqs_out.append(RequirementOut.model_validate(item))
                        except (ValueError, TypeError, AttributeError):
                            pass
                summary = analyzed_result.get('summary') or {}
                analyzed = int(summary.get('total_count') or 0)
                degraded = bool(analyzed_result.get('degraded'))
                analyze_mode = str(analyzed_result.get('mode') or '')
            msg = f'已上传，并解析出 {analyzed} 项' if auto_analyze else '已上传'
            if degraded:
                msg += f'（⚠ AI 已降级为启发式，degraded=true，mode={analyze_mode}）'
            results.append({'filename': name, 'success': True, 'status_code': 200, 'document_id': doc.id, 'analyzed_count': analyzed, 'analysis_type': analysis_type or 'requirements', 'degraded': degraded, 'mode': analyze_mode, 'message': msg})
        except Exception as exc:
            logger.info('document import failed for %s: %s', name, exc)
            results.append({'filename': name, 'success': False, 'status_code': 400, 'document_id': None, 'analyzed_count': 0, 'message': str(exc), 'error': str(exc)})
    success_count = sum((1 for r in results if r.get('success')))
    failed_count = len(results) - success_count
    analyzed_total = sum((int(r.get('analyzed_count') or 0) for r in results))
    any_degraded = any((bool(r.get('degraded')) for r in results if r.get('success')))
    message = f'成功 {success_count}/{len(results)} 个文件' + (f'，共解析 {analyzed_total} 条需求' if auto_analyze else '')
    if any_degraded:
        message += ' ⚠ 部分分析 AI 已降级为启发式（degraded）——请人工审阅'
    return {'success': failed_count == 0 and success_count > 0, 'summary': {'total': len(results), 'success_count': success_count, 'failed_count': failed_count, 'analyzed_count': analyzed_total, 'degraded': any_degraded}, 'results': results, 'documents': docs_out, 'requirements': reqs_out, 'degraded': any_degraded, 'message': message}
