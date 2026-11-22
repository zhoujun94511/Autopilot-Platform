"""Validate the current Runner claim before accepting job output."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import update
from sqlalchemy.orm import Session

from autopilot_platform.core.constants import JOB_CLAIM_GENERATION_CAPABILITY as JOB_CLAIM_GENERATION_CAPABILITY
from autopilot_platform.core.constants import JobStatus

from ...core import api_messages as msg
from ...core.models import JobRow, RunnerRow, db_get

_LEGACY_NULL_CLAIM_STATES = (
    JobStatus.CLAIMED.value,
    JobStatus.RUNNING.value,
    JobStatus.CANCELLED.value,
)
# Older runners may deliver the final report after they report completion.
_OUTPUT_STATES = (
    *_LEGACY_NULL_CLAIM_STATES,
    JobStatus.SUCCEEDED.value,
    JobStatus.FAILED.value,
)


def _claim_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def require_job_claim_generation(
    db: Session, row: JobRow, runner_id: str, claimed_at: datetime | None
) -> datetime | None:
    current = row.claimed_at
    if claimed_at is not None:
        if current is None or _claim_utc(claimed_at) != _claim_utc(current):
            raise PermissionError(msg.JOB_CLAIM_GENERATION_MISMATCH)
    else:
        runner = db_get(db, RunnerRow, runner_id)
        if runner is not None and JOB_CLAIM_GENERATION_CAPABILITY in runner.capabilities:
            raise PermissionError(msg.JOB_CLAIM_GENERATION_MISMATCH)
        # Claims acquired before claimed_at was introduced have no generation.
        if current is None and row.status not in _LEGACY_NULL_CLAIM_STATES:
            raise PermissionError(msg.JOB_CLAIM_GENERATION_MISMATCH)
    return current


def require_job_upload_claim(
    db: Session, row: JobRow, runner_id: str, claimed_at: datetime | None
) -> datetime | None:
    if not runner_id or row.runner_id != runner_id or row.status not in _OUTPUT_STATES:
        raise PermissionError(msg.JOB_NOT_OWNED_BY_RUNNER)
    return require_job_claim_generation(db, row, runner_id, claimed_at)


def lock_job_upload_claim(
    db: Session, job_id: str, runner_id: str, claimed_at: datetime | None
) -> None:
    """Ensure the claim stays current through the write on SQLite and PostgreSQL."""
    # A conditional no-op UPDATE acquires a write lock on both databases and
    # catches changes after the request awaited the body. Keep the original time.
    allowed_states = _LEGACY_NULL_CLAIM_STATES if claimed_at is None else _OUTPUT_STATES
    result = db.execute(
        update(JobRow)
        .where(
            JobRow.id == job_id,
            JobRow.runner_id == runner_id,
            JobRow.status.in_(allowed_states),
            JobRow.claimed_at == claimed_at,
        )
        .values(claimed_at=JobRow.claimed_at)
        .execution_options(synchronize_session=False)
    )
    if getattr(result, "rowcount", 0) != 1:
        raise PermissionError(msg.JOB_CLAIM_GENERATION_MISMATCH)
