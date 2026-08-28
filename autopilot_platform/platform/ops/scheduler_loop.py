"""平台计划后台扫描线程（AUD-2026-13：无独立 MQ，见 ADR_scheduler_no_mq）。"""

from __future__ import annotations

import logging
import threading
from typing import Optional

from ..core.settings import database_url, schedule_loop_enabled, schedule_tick_sec

logger = logging.getLogger(__name__)

_stop = threading.Event()
_thread: Optional[threading.Thread] = None


def _loop() -> None:
    # 延迟到调度线程启动后再加载 jobs/reports，避免 import 本模块时拉起重栈
    from sqlalchemy.exc import SQLAlchemyError

    from ..core.db import session_factory
    from ..services.shared.errors import BEST_EFFORT_ERRS
    from ..services.execution.schedules import tick as sched_svc
    from ..services.execution.jobs.recovery import reclaim_stale_jobs
    from ..services.execution.jobs.lifecycle import purge_job_logs
    from ..services.reports.storage import purge_job_reports
    from .scheduler_lock import try_acquire_scheduler_lease
    from . import audit as audit_svc
    from ..services.observability.fleet_alerts import tick_fleet_alerts

    # 单次 tick 失败不拖垮守护线程
    _tick_errs = (*BEST_EFFORT_ERRS, SQLAlchemyError)

    while not _stop.wait(schedule_tick_sec()):
        factory = session_factory()
        if factory is None:
            continue
        db = factory()
        try:
            if not try_acquire_scheduler_lease(db):
                logger.debug("schedule tick skipped (not DB leader)")
                continue
            ids = sched_svc.tick_due_schedules(db)
            if ids:
                logger.info("schedule tick created jobs: %s", ids)
            stale = reclaim_stale_jobs(db)
            if stale:
                logger.info("reclaimed stale jobs: %s", stale)
                try:
                    audit_svc.write_audit(
                        db,
                        action="job.reclaim",
                        actor="scheduler",
                        actor_kind="system",
                        resource_type="job",
                        detail=(
                            f"count={len(stale)};"
                            f"job_ids={','.join(stale[:20])}"
                        ),
                    )
                except BEST_EFFORT_ERRS as audit_exc:
                    logger.warning("reclaim audit failed: %s", audit_exc)
            try:
                deleted, days = purge_job_reports(db)
                if deleted:
                    logger.info(
                        "purged %s job reports older than %s days", deleted, days
                    )
                    audit_svc.write_audit(
                        db,
                        action="report.purge",
                        actor="scheduler",
                        actor_kind="system",
                        resource_type="report",
                        detail=f"deleted={deleted} days={days}",
                    )
            except _tick_errs as purge_exc:
                logger.warning("report purge failed: %s", purge_exc)
            try:
                deleted, days = purge_job_logs(db)
                if deleted:
                    logger.info(
                        "purged %s job log file(s) older than %s days", deleted, days
                    )
                    audit_svc.write_audit(
                        db,
                        action="job_log.purge",
                        actor="scheduler",
                        actor_kind="system",
                        resource_type="job_log",
                        detail=f"deleted={deleted} days={days}",
                    )
            except _tick_errs as jl_exc:
                logger.warning("job log purge failed: %s", jl_exc)
            try:
                deleted, days = audit_svc.purge_audit_logs(db)
                if deleted:
                    logger.info(
                        "purged %s audit log row(s) older than %s days", deleted, days
                    )
            except _tick_errs as al_exc:
                logger.warning("audit log purge failed: %s", al_exc)
            try:
                fleet = tick_fleet_alerts(db)
                if fleet.get("runner_offline"):
                    logger.info("runner offline alerts: %s", fleet["runner_offline"])
                if fleet.get("device_pool_empty"):
                    logger.info("device pool empty alert fired")
            except _tick_errs as fleet_exc:
                logger.warning("fleet alert tick failed: %s", fleet_exc)
        except _tick_errs as exc:
            logger.warning("schedule tick failed: %s", exc)
        finally:
            db.close()


def start_schedule_loop() -> None:
    global _thread
    if not schedule_loop_enabled():
        logger.info("schedule loop disabled (MC_SCHEDULE_ENABLED)")
        return
    if _thread is not None and _thread.is_alive():
        return
    db_url = database_url()
    logger.warning(
        "Schedule loop enabled (tick=%ss): one DB leader via ops_locks. "
        "Deploy as single active scheduler per database "
        "(or MC_SCHEDULE_ENABLED=0 on followers). "
        "SQLite is single-writer — prefer PostgreSQL for multi-instance HA. db=%s",
        schedule_tick_sec(),
        "sqlite" if db_url.startswith("sqlite") else "non-sqlite",
    )
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="mc-schedule-tick", daemon=True)
    _thread.start()
    logger.info("schedule loop started (tick=%ss)", schedule_tick_sec())


def stop_schedule_loop() -> None:
    global _thread
    _stop.set()
    t = _thread
    _thread = None
    if t is not None:
        t.join(timeout=2.0)
