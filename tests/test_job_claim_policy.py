"""Unit coverage for the claim checks shared by reports and logs."""

from datetime import timedelta
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from autopilot_platform.core.constants import JOB_CLAIM_GENERATION_CAPABILITY, JobStatus
from autopilot_platform.core.schemas import JobResultIn
from autopilot_platform.platform.core import api_messages as msg
from autopilot_platform.platform.core.db import Base
from autopilot_platform.platform.core.models import JobRow, RunnerRow, utcnow
from autopilot_platform.platform.services.execution.job_claims import require_job_upload_claim
from autopilot_platform.platform.services.execution.jobs import lifecycle


@pytest.mark.parametrize("status,owner", [(JobStatus.PENDING, None), (JobStatus.CLAIMED, "other")])
def test_job_upload_requires_assigned_runner(status, owner):
    row = JobRow(status=status.value, runner_id=owner)
    with pytest.raises(PermissionError, match=msg.JOB_NOT_OWNED_BY_RUNNER):
        require_job_upload_claim(Mock(spec=Session), row, "runner", None)


def test_job_upload_respects_claim_generation():
    current = utcnow()
    row = JobRow(status=JobStatus.RUNNING.value, runner_id="runner", claimed_at=current)
    db = Mock(spec=Session)
    runner = RunnerRow(runner_id="runner")
    runner.capabilities = [JOB_CLAIM_GENERATION_CAPABILITY]
    db.get.return_value = runner

    assert require_job_upload_claim(db, row, "runner", current.replace(tzinfo=None)) == current
    with pytest.raises(PermissionError, match=msg.JOB_CLAIM_GENERATION_MISMATCH):
        require_job_upload_claim(db, row, "runner", current - timedelta(seconds=1))
    with pytest.raises(PermissionError, match=msg.JOB_CLAIM_GENERATION_MISMATCH):
        require_job_upload_claim(db, row, "runner", None)

    runner.capabilities = []
    row.status = JobStatus.SUCCEEDED.value
    assert require_job_upload_claim(db, row, "runner", None) == current

    row.claimed_at = None
    with pytest.raises(PermissionError, match=msg.JOB_CLAIM_GENERATION_MISMATCH):
        require_job_upload_claim(db, row, "runner", None)

    row.status = JobStatus.RUNNING.value
    assert require_job_upload_claim(db, row, "runner", None) is None
    runner.capabilities = [JOB_CLAIM_GENERATION_CAPABILITY]
    with pytest.raises(PermissionError, match=msg.JOB_CLAIM_GENERATION_MISMATCH):
        require_job_upload_claim(db, row, "runner", None)


def test_pre_migration_claim_can_finish(monkeypatch):
    monkeypatch.setattr(lifecycle, "_fire_job_webhook", Mock())
    engine = create_engine("sqlite://")
    try:
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            db.add(RunnerRow(runner_id="legacy-runner"))
            db.add(JobRow(
                id="legacy-job",
                status=JobStatus.CLAIMED.value,
                runner_id="legacy-runner",
            ))
            db.commit()

            running = lifecycle.mark_job_running(db, "legacy-job", "legacy-runner")
            assert running.status == JobStatus.RUNNING
            assert running.claimed_at is None

            completed = lifecycle.complete_job(
                db, "legacy-job", "legacy-runner", JobResultIn(status=JobStatus.SUCCEEDED)
            )
            assert completed.status == JobStatus.SUCCEEDED
    finally:
        engine.dispose()
