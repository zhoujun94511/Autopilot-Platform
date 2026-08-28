"""Job 质量聚合：日趋势 + 全步 fail_reason + job.error 前缀（非仅 Intent）。"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ....ap.report.fail_class import scan_attributions, scan_fail_classes

from ...core.models import JobRow, ReportRow, utcnow

log = logging.getLogger(__name__)

_MAX_REPORTS = 80
_ERROR_PREFIX_RE = re.compile(r"^(.{1,80}?)(?:\n|: |；|;|。)")


def _day_key(dt: datetime | None) -> str:
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d")


def _error_prefix(err: str) -> str:
    text = (err or "").strip().replace("\r\n", "\n")
    if not text:
        return "(empty)"
    first = text.split("\n", 1)[0].strip()
    m = _ERROR_PREFIX_RE.match(first)
    if m:
        return (m.group(1) or first)[:80]
    return first[:80]


def _scan_all_fail_reasons(payload: dict[str, Any], counter: Counter[str]) -> int:
    """扫描全部步骤 fail_reason（含非 Intent）。返回失败步数。"""
    n = 0
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
            fr = str(step.get("fail_reason") or "").strip()
            if not fr:
                st = str(step.get("status") or step.get("result") or "").lower()
                if st in ("fail", "failed", "error"):
                    fr = "(step_failed)"
                else:
                    continue
            counter[fr] += 1
            n += 1
    return n


def job_quality_snapshot(
    db: Session,
    *,
    project_id: str | None = None,
    project_ids: list[str] | None = None,
    days: int = 14,
    report_limit: int = _MAX_REPORTS,
) -> dict[str, Any]:
    """项目（或作用域）Job 失败趋势 + 归因摘要。"""
    day_n = max(1, min(int(days or 14), 90))
    lim = max(1, min(int(report_limit or _MAX_REPORTS), 200))
    now = utcnow()
    since = now - timedelta(days=day_n)

    q = select(JobRow).where(JobRow.updated_at >= since).order_by(JobRow.updated_at.desc())
    pid = (project_id or "").strip()
    if pid:
        q = q.where(JobRow.project_id == pid)
    elif project_ids is not None:
        ids = [str(x).strip() for x in project_ids if str(x).strip()]
        if not ids:
            return _empty(days=day_n)
        q = q.where(JobRow.project_id.in_(ids))

    jobs = list(db.scalars(q.limit(2000)).all())

    by_day: dict[str, dict[str, int]] = {}
    status_counts: Counter[str] = Counter()
    error_prefixes: Counter[str] = Counter()
    for job in jobs:
        st = str(job.status or "unknown")
        status_counts[st] += 1
        dk = _day_key(job.updated_at or job.created_at)
        if not dk:
            continue
        bucket = by_day.setdefault(dk, {"total": 0, "succeeded": 0, "failed": 0, "cancelled": 0})
        bucket["total"] += 1
        if st in ("succeeded", "failed", "cancelled"):
            bucket[st] += 1
        if st == "failed":
            error_prefixes[_error_prefix(str(job.error or ""))] += 1

    # 补齐日期轴（含 0）
    trend: list[dict[str, Any]] = []
    for i in range(day_n - 1, -1, -1):
        d = (now - timedelta(days=i)).astimezone(timezone.utc).strftime("%Y-%m-%d")
        b = by_day.get(d) or {"total": 0, "succeeded": 0, "failed": 0, "cancelled": 0}
        total = int(b["total"])
        failed = int(b["failed"])
        trend.append(
            {
                "day": d,
                "total": total,
                "succeeded": int(b["succeeded"]),
                "failed": failed,
                "cancelled": int(b["cancelled"]),
                "fail_rate": round(failed / total, 4) if total else 0.0,
            }
        )

    terminal = (
        int(status_counts.get("succeeded", 0))
        + int(status_counts.get("failed", 0))
        + int(status_counts.get("cancelled", 0))
    )
    failed_n = int(status_counts.get("failed", 0))

    # 全步 fail_reason（扫近期带 result 的报告）
    rq = (
        select(ReportRow, JobRow.project_id)
        .join(JobRow, JobRow.id == ReportRow.job_id)
        .where(ReportRow.result_json_path != "")
        .order_by(ReportRow.created_at.desc())
        .limit(lim * 2)
    )
    if pid:
        rq = rq.where(JobRow.project_id == pid)
    elif project_ids is not None:
        ids = [str(x).strip() for x in project_ids if str(x).strip()]
        rq = rq.where(JobRow.project_id.in_(ids))

    fail_reason: Counter[str] = Counter()
    fail_class: Counter[str] = Counter()
    attribution: Counter[str] = Counter()
    scanned = 0
    failed_steps = 0
    for rep, _ in db.execute(rq).all():
        if scanned >= lim:
            break
        path = Path(str(getattr(rep, "result_json_path", "") or ""))
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            log.debug("job_quality skip %s: %s", path, exc)
            continue
        if not isinstance(payload, dict):
            continue
        scanned += 1
        failed_steps += _scan_all_fail_reasons(payload, fail_reason)
        scan_fail_classes(payload, fail_class)
        scan_attributions(payload, attribution)

    top_fr = dict(fail_reason.most_common(12))
    top_fc = dict(fail_class.most_common(8))
    top_attr = dict(attribution.most_common(8))
    top_err = dict(error_prefixes.most_common(10))

    return {
        "project_id": pid or None,
        "days": day_n,
        "jobs_scanned": len(jobs),
        "status_counts": dict(status_counts),
        "terminal_jobs": terminal,
        "failed_jobs": failed_n,
        "fail_rate": round(failed_n / terminal, 4) if terminal else 0.0,
        "trend": trend,
        "error_prefix_top": top_err,
        "fail_reason_top": top_fr,
        "fail_class_top": top_fc,
        "attribution_top": top_attr,
        "reports_scanned": scanned,
        "failed_steps": failed_steps,
        "note": "Job 行按 updated_at 窗口聚合；fail_reason / fail_class / attribution 来自近期 result.json 全步骤",
    }


def _empty(*, days: int) -> dict[str, Any]:
    return {
        "project_id": None,
        "days": days,
        "jobs_scanned": 0,
        "status_counts": {},
        "terminal_jobs": 0,
        "failed_jobs": 0,
        "fail_rate": 0.0,
        "trend": [],
        "error_prefix_top": {},
        "fail_reason_top": {},
        "fail_class_top": {},
        "attribution_top": {},
        "reports_scanned": 0,
        "failed_steps": 0,
        "note": "作用域内无 Job",
    }
