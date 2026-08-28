"""批跑 result.json → 设计域 automation_status 回写。

当 cases[] 含 logical_case_id 时，按 IDE 写入的状态证据更新设计态：
- passed → EXECUTABLE / BINDING_PARTIAL / PENDING_VERIFY（缺验证时）
- failed → DEBUGGING / MAPPING_REQUIRED
其余状态不降级、不覆盖 PUBLISHED/DEPRECATED。
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import Any
from sqlalchemy.orm import Session
from autopilot_platform.platform.design.design_models import LogicalCaseRow
from autopilot_platform.platform.core.models import db_get
log = logging.getLogger(__name__)
_PASS_TARGETS = frozenset({'PENDING_VERIFY', 'INTENT_READY', 'DEBUGGING', 'BINDING_PARTIAL', 'MAPPING_REQUIRED', 'LOGICAL_ONLY', 'EXECUTABLE'})
_FAIL_TARGETS = frozenset({'PENDING_VERIFY', 'INTENT_READY', 'EXECUTABLE', 'BINDING_PARTIAL', 'MAPPING_REQUIRED', 'LOGICAL_ONLY'})

def _norm_status(raw: Any) -> str:
    return str(raw or '').strip().lower()

def _case_passed(item: dict[str, Any]) -> bool | None:
    st = _norm_status(item.get('status'))
    if st in ('passed', 'pass', 'ok', 'success', 'succeeded'):
        return True
    if st in ('failed', 'fail', 'error', 'broken'):
        return False
    return None

def _has_missing_verification(item: dict[str, Any]) -> bool:
    steps = item.get('steps')
    if not isinstance(steps, list):
        return False
    for step in steps:
        if not isinstance(step, dict):
            continue
        if not str(step.get('intent_id') or '').strip() and (not str(step.get('binding_hit') or '').strip()):
            continue
        st = str(step.get('status') or '').strip().lower()
        if st not in ('pass', 'passed', 'ok', 'success'):
            continue
        if str(step.get('verification_status') or '').strip().lower() == 'missing':
            return True
    return False

def _target_status(item: dict[str, Any], passed: bool) -> str:
    """消费 IDE run_status_sync 写入 result.json 的决策证据。"""
    evidence = str(item.get('automation_status_evidence') or '').strip().upper()
    if passed:
        if evidence == 'PENDING_VERIFY' or _has_missing_verification(item):
            return 'PENDING_VERIFY'
        if evidence in ('EXECUTABLE', 'BINDING_PARTIAL'):
            return evidence
        steps = item.get('steps')
        intents = [step for step in (steps if isinstance(steps, list) else []) if isinstance(step, dict) and str(step.get('intent_id') or '').strip()]
        complete_hits = {'cache', 'resolved', 'healed', 'rolled_back'}
        if intents and any((str(step.get('binding_hit') or '').strip().lower() not in complete_hits for step in intents)):
            return 'BINDING_PARTIAL'
        return 'EXECUTABLE'
    if evidence == 'MAPPING_REQUIRED' or bool(item.get('mapping_required')):
        return 'MAPPING_REQUIRED'
    return 'DEBUGGING'

def apply_result_json_to_logical_cases(db: Session, payload: dict[str, Any], *, project_id: str | None=None) -> dict[str, Any]:
    """根据 result.json 回写 logical_case.automation_status。返回汇总。

    ``project_id`` 为 Job 所属项目时强制对齐：用例跨项目一律跳过，防止 scoped Runner
    借 result.json 篡改他项状态。
    """
    cases = payload.get('cases') if isinstance(payload, dict) else None
    if not isinstance(cases, list) or not cases:
        return {'updated': 0, 'skipped': 0, 'missing': 0, 'details': []}
    updated = 0
    skipped = 0
    missing = 0
    details: list[dict[str, str]] = []
    now = datetime.now(timezone.utc)
    job_project = (project_id or '').strip()
    for item in cases:
        if not isinstance(item, dict):
            skipped += 1
            continue
        lc_id = str(item.get('logical_case_id') or '').strip()
        if not lc_id:
            skipped += 1
            continue
        passed = _case_passed(item)
        if passed is None:
            skipped += 1
            details.append({'logical_case_id': lc_id, 'action': 'skip_unknown_status'})
            continue
        row = db_get(db, LogicalCaseRow, lc_id)
        if row is None:
            missing += 1
            details.append({'logical_case_id': lc_id, 'action': 'missing'})
            continue
        row_project = str(row.project_id or '').strip()
        if job_project and row_project and (row_project != job_project):
            skipped += 1
            details.append({'logical_case_id': lc_id, 'action': 'skip_project_mismatch', 'case_project': row_project, 'job_project': job_project})
            log.warning('skip automation_status sync: case %s project=%s != job project=%s', lc_id, row_project, job_project)
            continue
        cur = str(row.automation_status or '').strip()
        if cur in ('PUBLISHED', 'DEPRECATED'):
            skipped += 1
            details.append({'logical_case_id': lc_id, 'action': 'skip_terminal', 'from': cur})
            continue
        target = _target_status(item, passed)
        if passed:
            if cur not in _PASS_TARGETS:
                skipped += 1
                details.append({'logical_case_id': lc_id, 'action': 'skip_pass', 'from': cur})
                continue
            if cur == target:
                skipped += 1
                continue
            if cur == 'EXECUTABLE' and target not in ('EXECUTABLE', 'PENDING_VERIFY', 'BINDING_PARTIAL'):
                skipped += 1
                details.append({'logical_case_id': lc_id, 'action': 'skip_pass', 'from': cur})
                continue
            row.automation_status = target
        else:
            if cur not in _FAIL_TARGETS and cur != 'DEBUGGING':
                skipped += 1
                details.append({'logical_case_id': lc_id, 'action': 'skip_fail', 'from': cur})
                continue
            if cur == target:
                skipped += 1
                continue
            row.automation_status = target
        row.updated_at = now
        updated += 1
        details.append({'logical_case_id': lc_id, 'action': 'set', 'from': cur, 'to': row.automation_status})
    return {'updated': updated, 'skipped': skipped, 'missing': missing, 'details': details}
