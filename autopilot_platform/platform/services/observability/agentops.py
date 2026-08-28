"""AgentOps 聚合：扫近期 result.json 的 Intent Trace + AI usage 摘要。"""

from __future__ import annotations

import json
import logging
from collections import Counter
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...ai import ai_usage
from ...core.models import JobRow, ReportRow

log = logging.getLogger(__name__)

_MAX_REPORTS = 80


def _bump(counter: Counter[str], key: str, n: int = 1) -> None:
    k = (key or "").strip() or "(empty)"
    counter[k] += n


def _scan_result_payload(payload: dict[str, Any], acc: dict[str, Any]) -> None:
    raw_cases = payload.get("cases")
    cases = raw_cases if isinstance(raw_cases, list) else []
    for case in cases:
        if not isinstance(case, dict):
            continue
        raw_steps = case.get("steps")
        steps = raw_steps if isinstance(raw_steps, list) else []
        for step in steps:
            if not isinstance(step, dict):
                continue
            hit = str(step.get("binding_hit") or "").strip()
            if not hit and not step.get("intent_id"):
                continue
            acc["intent_steps"] += 1
            if hit:
                _bump(acc["binding_hit"], hit)
            if step.get("heal_applied"):
                acc["heal_count"] += 1
            strategy = str(step.get("resolve_strategy") or "").strip()
            if strategy:
                _bump(acc["resolve_strategy"], strategy)
            fr = str(step.get("fail_reason") or "").strip()
            if fr:
                _bump(acc["fail_reason"], fr)
            if bool(step.get("perception_used_screenshot")) or strategy == "vision":
                acc["vision_steps"] += 1
            try:
                lat = int(step.get("latency_ms") or 0)
            except (TypeError, ValueError):
                lat = 0
            if lat > 0:
                acc["latency_sum_ms"] += lat
                acc["latency_n"] += 1
            try:
                tok = int(step.get("vision_tokens") or 0)
            except (TypeError, ValueError):
                tok = 0
            if tok > 0:
                acc["vision_tokens_sum"] += tok
            vs = str(step.get("verification_status") or "").strip()
            if vs:
                _bump(acc["verification_status"], vs)
            if step.get("screenshot_path") or step.get("dom_path"):
                acc["evidence_steps"] += 1


def aggregate_from_reports(
    db: Session,
    *,
    project_id: str | None = None,
    project_ids: list[str] | None = None,
    limit: int = _MAX_REPORTS,
) -> dict[str, Any]:
    """从 ReportRow.result_json_path 聚合 Intent 指标。"""
    lim = max(1, min(int(limit or _MAX_REPORTS), 200))
    q = (
        select(ReportRow, JobRow.project_id)
        .join(JobRow, JobRow.id == ReportRow.job_id)
        .where(ReportRow.result_json_path != "")
        .order_by(ReportRow.created_at.desc())
        .limit(lim * 2)  # 过滤后可能不足 lim
    )
    pid = (project_id or "").strip()
    if pid:
        q = q.where(JobRow.project_id == pid)
    elif project_ids is not None:
        ids = [str(x).strip() for x in project_ids if str(x).strip()]
        if not ids:
            return _empty_trace(scanned=0)
        q = q.where(JobRow.project_id.in_(ids))

    acc: dict[str, Any] = {
        "intent_steps": 0,
        "heal_count": 0,
        "vision_steps": 0,
        "vision_tokens_sum": 0,
        "latency_sum_ms": 0,
        "latency_n": 0,
        "evidence_steps": 0,
        "binding_hit": Counter(),
        "resolve_strategy": Counter(),
        "fail_reason": Counter(),
        "verification_status": Counter(),
    }
    scanned = 0
    for rep, _job_pid in db.execute(q).all():
        if scanned >= lim:
            break
        path = Path(str(getattr(rep, "result_json_path", "") or ""))
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            log.debug("agentops skip %s: %s", path, exc)
            continue
        if not isinstance(payload, dict):
            continue
        scanned += 1
        _scan_result_payload(payload, acc)

    hit = dict(acc["binding_hit"])
    total_hit = sum(hit.values()) or 0
    cache_n = int(hit.get("cache", 0))
    heal_n = int(acc["heal_count"])
    vision_n = int(acc["vision_steps"])
    steps_n = int(acc["intent_steps"])
    avg_lat = (
        round(acc["latency_sum_ms"] / acc["latency_n"], 1) if acc["latency_n"] else 0.0
    )
    return {
        "reports_scanned": scanned,
        "intent_steps": steps_n,
        "binding_hit": hit,
        "cache_hit_rate": round(cache_n / total_hit, 4) if total_hit else 0.0,
        "heal_rate": round(heal_n / steps_n, 4) if steps_n else 0.0,
        "vision_rate": round(vision_n / steps_n, 4) if steps_n else 0.0,
        "heal_count": heal_n,
        "vision_steps": vision_n,
        "vision_tokens_sum": int(acc["vision_tokens_sum"]),
        "avg_latency_ms": avg_lat,
        "fail_reason": dict(acc["fail_reason"]),
        "resolve_strategy": dict(acc["resolve_strategy"]),
        "verification_status": dict(acc["verification_status"]),
        "evidence_steps": int(acc["evidence_steps"]),
        "note": "聚合自近期上传的 result.json（Intent Trace）；非实时流式",
    }


def _empty_trace(*, scanned: int = 0) -> dict[str, Any]:
    return {
        "reports_scanned": scanned,
        "intent_steps": 0,
        "binding_hit": {},
        "cache_hit_rate": 0.0,
        "heal_rate": 0.0,
        "vision_rate": 0.0,
        "heal_count": 0,
        "vision_steps": 0,
        "vision_tokens_sum": 0,
        "avg_latency_ms": 0.0,
        "fail_reason": {},
        "resolve_strategy": {},
        "verification_status": {},
        "evidence_steps": 0,
        "note": "无可用 result.json",
    }


def agentops_snapshot(
    db: Session,
    *,
    project_id: str | None = None,
    project_ids: list[str] | None = None,
    limit: int = _MAX_REPORTS,
) -> dict[str, Any]:
    """完整 AgentOps 快照：trace 聚合 + AI token 日摘要。"""
    trace = aggregate_from_reports(
        db, project_id=project_id, project_ids=project_ids, limit=limit
    )
    try:
        tokens = ai_usage.usage_summary(top_projects=5)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        tokens = {"error": str(exc)[:200]}
    return {
        "project_id": (project_id or "").strip() or None,
        "trace": trace,
        "tokens": tokens,
    }
