"""轻量 Prometheus 文本指标（无 prometheus_client 依赖）。"""

from __future__ import annotations

import threading
from collections import defaultdict
from typing import Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from autopilot_platform.core.constants import JobStatus
from ..ai import ai_usage

_lock = threading.Lock()
_counters: dict[tuple[str, tuple[tuple[str, str], ...]], float] = defaultdict(float)


def _key(name: str, labels: dict[str, str] | None = None) -> tuple[str, tuple[tuple[str, str], ...]]:
    items = tuple(sorted((labels or {}).items()))
    return name, items


def inc(name: str, *, labels: dict[str, str] | None = None, amount: float = 1.0) -> None:
    with _lock:
        _counters[_key(name, labels)] += amount


def reset_for_tests() -> None:
    with _lock:
        _counters.clear()


def note_job_terminal(status: str) -> None:
    """任务进入终态时累加计数。"""
    inc("mc_job_terminal_total", labels={"status": status})


def note_stale_reclaimed(n: int) -> None:
    if n > 0:
        inc("mc_stale_reclaimed_total", amount=float(n))


def note_alert_sent(event: str, *, ok: bool) -> None:
    inc("mc_alert_sent_total", labels={"event": event, "ok": "1" if ok else "0"})


def _escape_label(v: str) -> str:
    return v.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _format_labels(labels: Iterable[tuple[str, str]]) -> str:
    parts = [f'{k}="{_escape_label(v)}"' for k, v in labels]
    return "{" + ",".join(parts) + "}" if parts else ""


def _gauge_lines(name: str, help_text: str, samples: list[tuple[dict[str, str], float]]) -> list[str]:
    lines = [f"# HELP {name} {help_text}", f"# TYPE {name} gauge"]
    for labels, val in samples:
        lines.append(f"{name}{_format_labels(sorted(labels.items()))} {val}")
    return lines


def _counter_lines_from_store(name: str, help_text: str) -> list[str]:
    lines = [f"# HELP {name} {help_text}", f"# TYPE {name} counter"]
    with _lock:
        items = [(labs, v) for (n, labs), v in _counters.items() if n == name]
    if not items:
        lines.append(f"{name} 0")
        return lines
    for labs, v in sorted(items, key=lambda x: x[0]):
        lines.append(f"{name}{_format_labels(labs)} {v}")
    return lines


def collect_text(db: Session | None = None) -> str:
    """生成 Prometheus exposition 文本。"""
    from .models import DeviceRow, JobRow, RunnerRow
    from ..services.shared.status import is_online

    lines: list[str] = []
    lines.extend(
        _counter_lines_from_store(
            "mc_job_terminal_total",
            "Job terminal status events since process start",
        )
    )
    lines.extend(
        _counter_lines_from_store(
            "mc_stale_reclaimed_total",
            "Jobs reclaimed as stale since process start",
        )
    )
    lines.extend(
        _counter_lines_from_store(
            "mc_alert_sent_total",
            "Ops alert webhook attempts since process start",
        )
    )
    lines.extend(
        _counter_lines_from_store(
            "mc_ai_chat_calls_total",
            "AI chat completion calls since process start",
        )
    )
    lines.extend(
        _counter_lines_from_store(
            "mc_ai_tokens_total",
            "AI token totals reported by providers since process start",
        )
    )

    if db is not None:
        status_counts: dict[str, int] = {s.value: 0 for s in JobStatus}
        for status, cnt in db.execute(
            select(JobRow.status, func.count()).group_by(JobRow.status)
        ).all():
            status_counts[str(status)] = int(cnt)
        lines.extend(
            _gauge_lines(
                "mc_jobs",
                "Current jobs by status",
                [({"status": st}, float(n)) for st, n in sorted(status_counts.items())],
            )
        )

        runners = list(db.scalars(select(RunnerRow)).all())
        online_n = sum(1 for r in runners if is_online(r.last_heartbeat_at))
        lines.extend(
            _gauge_lines(
                "mc_runners",
                "Registered runners",
                [
                    ({"state": "online"}, float(online_n)),
                    ({"state": "total"}, float(len(runners))),
                ],
            )
        )

        devices = list(db.scalars(select(DeviceRow)).all())
        free_n = sum(1 for d in devices if not (d.busy_job_id or "").strip())
        lines.extend(
            _gauge_lines(
                "mc_devices",
                "TR pool devices",
                [
                    ({"state": "total"}, float(len(devices))),
                    ({"state": "free"}, float(free_n)),
                    ({"state": "busy"}, float(len(devices) - free_n)),
                ],
            )
        )

    lines.append("")
    return "\n".join(lines)


def ops_summary(db: Session) -> dict:
    """管理台运维摘要（JSON）。"""
    from .models import DeviceRow, JobRow, RunnerRow
    from ..services.shared.status import is_online

    jobs_by_status: dict[str, int] = {s.value: 0 for s in JobStatus}
    for status, cnt in db.execute(
        select(JobRow.status, func.count()).group_by(JobRow.status)
    ).all():
        jobs_by_status[str(status)] = int(cnt)

    runners = list(db.scalars(select(RunnerRow)).all())
    online_ids = {
        r.runner_id for r in runners if is_online(r.last_heartbeat_at)
    }
    runners_online = len(online_ids)
    runners_registered = len(runners)
    devices = list(db.scalars(select(DeviceRow)).all())
    online_devices = [d for d in devices if d.runner_id in online_ids]
    with _lock:
        counters = {
            f"{n}" + (";" + ",".join(f"{k}={v}" for k, v in labs) if labs else ""): val
            for (n, labs), val in _counters.items()
        }

    return {
        "jobs_by_status": jobs_by_status,
        "runners_online": runners_online,
        "runners_offline": max(0, runners_registered - runners_online),
        "runners_total": runners_registered,
        "devices_total": len(online_devices),
        "devices_busy": sum(
            1 for d in online_devices if (d.busy_job_id or "").strip()
        ),
        "counters": counters,
        "metrics_path": "/metrics",
        "ai": _ops_ai_snapshot(db),
    }


def _ops_ai_snapshot(db: Session) -> dict:
    """O6/T7：运维摘要中的 AI 用量与降级占比。"""
    out: dict = {}
    try:
        out["tokens"] = ai_usage.usage_summary(top_projects=5)
    except Exception as exc:  # noqa: BLE001
        out["tokens"] = {"error": str(exc)[:200]}
    try:
        from ..services.design.stats import degraded_case_stats

        out["degraded"] = degraded_case_stats(db, None)
    except Exception as exc:  # noqa: BLE001
        out["degraded"] = {"error": str(exc)[:200]}
    return out
