"""用例生成内容去重（消费 AP_ENABLE_CONTENT_DEDUP / THRESHOLD / BATCH_SIZE）。"""
from __future__ import annotations
import re
from difflib import SequenceMatcher
from typing import Any, Sequence
from sqlalchemy import select
from sqlalchemy.orm import Session
from autopilot_platform.platform.ops.runtime_config import content_dedup_batch_size, content_dedup_enabled, content_similarity_threshold

def _norm_text(value: str) -> str:
    s = (value or '').strip().lower()
    s = re.sub('\\s+', ' ', s)
    return s

def case_fingerprint(*, title: str, logical_steps: Sequence[str] | None=None) -> str:
    steps = [str(x).strip() for x in logical_steps or [] if str(x).strip()]
    return _norm_text((title or '') + '\n' + '\n'.join(steps))

def text_similarity(a: str, b: str) -> float:
    left = _norm_text(a)
    right = _norm_text(b)
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    return float(SequenceMatcher(None, left, right).ratio())

def _existing_fingerprints(db: Session, project_id: str, *, limit: int) -> list[str]:
    from autopilot_platform.platform.design.design_models import LogicalCaseRow
    pid = (project_id or '').strip()
    if not pid:
        return []
    rows = list(db.scalars(select(LogicalCaseRow).where(LogicalCaseRow.project_id == pid).order_by(LogicalCaseRow.updated_at.desc()).limit(max(1, int(limit)))).all())
    out: list[str] = []
    for row in rows:
        out.append(case_fingerprint(title=str(getattr(row, 'title', '') or ''), logical_steps=list(getattr(row, 'logical_steps', None) or [])))
    return out

def filter_duplicate_drafts(db: Session, *, project_id: str, drafts: list[Any]) -> tuple[list[Any], dict[str, Any]]:
    """按标题+步骤相似度过滤草稿；关闭去重时原样返回。

    若全部命中重复，保留首条以免空结果，并在 meta 标注。
    """
    meta: dict[str, Any] = {'enabled': content_dedup_enabled(), 'threshold': content_similarity_threshold(), 'batch_size': content_dedup_batch_size(), 'dropped': 0, 'kept': len(drafts), 'kept_one_fallback': False}
    if not meta['enabled'] or not drafts:
        return list(drafts), meta
    threshold = float(meta['threshold'])
    batch = int(meta['batch_size'])
    existing = _existing_fingerprints(db, project_id, limit=batch)
    kept: list[Any] = []
    kept_fps: list[str] = []
    dropped = 0
    for draft in drafts:
        title = str(getattr(draft, 'title', '') or '')
        steps = list(getattr(draft, 'logical_steps', None) or [])
        fp = case_fingerprint(title=title, logical_steps=steps)
        dup = any((text_similarity(fp, other) >= threshold for other in existing + kept_fps))
        if dup:
            dropped += 1
            continue
        kept.append(draft)
        kept_fps.append(fp)
    if not kept and drafts:
        kept = [drafts[0]]
        meta['kept_one_fallback'] = True
        dropped = max(0, len(drafts) - 1)
    meta['dropped'] = dropped
    meta['kept'] = len(kept)
    return kept, meta
