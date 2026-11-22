"""Platform Runner：报告须在 complete 之前上传；失败时保留本地文件。"""

from __future__ import annotations

import threading
import zipfile
from dataclasses import replace
from types import SimpleNamespace
from io import BytesIO
from typing import cast

from autopilot_platform.runner import agent as agent_module
from autopilot_platform.runner.agent import RunnerAgent
from autopilot_platform.runner.client import PlatformClient
from autopilot_platform.runner.contract import JobOut, JobResultIn, JobStatus, ReportIndex


class _Client:
    def __init__(self, job: JobOut, *, fail_upload: bool = False) -> None:
        self.job = job
        self.fail_upload = fail_upload
        self.calls: list[str] = []
        self.last_result: JobResultIn | None = None

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    @staticmethod
    def heartbeat(_body) -> dict:
        return {}

    def claim(self, _runner_id: str, *, wait_sec: int = 0) -> JobOut:
        _ = wait_sec
        return self.job

    def mark_running(self, _job_id: str, _runner_id: str) -> JobOut:
        self.calls.append("running")
        return self.job

    def upload_report(self, _job_id: str, _runner_id: str, _path: str) -> dict:
        self.calls.append("report")
        if self.fail_upload:
            raise OSError("network down")
        return {}

    def upload_result_json(self, _job_id: str, _runner_id: str, _path: str) -> dict:
        self.calls.append("result")
        return {}

    def upload_evidence_zip(self, _job_id: str, _runner_id: str, _path: str) -> dict:
        self.calls.append("evidence")
        return {}

    def complete(self, _job_id: str, _runner_id: str, result: JobResultIn) -> JobOut:
        self.calls.append("complete")
        self.last_result = result
        return self.job


def _run_with_report(tmp_path, monkeypatch, *, fail_upload: bool, cancelled: bool = False):
    monkeypatch.setenv("MC_RUNNER_STATE_DIR", str(tmp_path / "runner-state"))
    monkeypatch.setattr(agent_module.tempfile, "gettempdir", lambda: str(tmp_path))
    report_dir = tmp_path / "mc-report-delivery"
    report_dir.mkdir()
    report_path = report_dir / "report.html"
    report_path.write_text("<html>ok</html>", encoding="utf-8")
    (report_dir / "result.json").write_text("{}", encoding="utf-8")
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("reports/evidence/c1/s1.png", b"fake")
    (report_dir / "evidence.zip").write_bytes(buf.getvalue())
    job = JobOut(
        id="job-1",
        name="job",
        status=JobStatus.CLAIMED,
        project_dir="/tmp/proj",
        platform="android",
    )
    result = JobResultIn(
        status=JobStatus.SUCCEEDED,
        report=ReportIndex(report_path=str(report_path)),
    )

    def _execute(_job, _client, cancel_event=None):
        if cancelled and cancel_event is not None:
            cancel_event.set()
        return result

    monkeypatch.setattr(agent_module, "execute_job", _execute)
    runner = RunnerAgent("http://platform", runner_id="runner-1")
    client = _Client(job, fail_upload=fail_upload)
    monkeypatch.setattr(agent_module, "PlatformClient", lambda *_a, **_k: client)
    monkeypatch.setattr(runner, "_heartbeat_once", lambda _client: None)
    monkeypatch.setattr(runner, "_ensure_remote_sync", lambda: None)
    monkeypatch.setattr(runner, "_sync_remote_sessions", lambda _client: None)
    monkeypatch.setattr(runner, "_ensure_exec_heartbeat", lambda _client: None)
    monkeypatch.setattr(runner, "_maybe_stop_exec_heartbeat", lambda: None)
    assert runner.run_once(cast(PlatformClient, client)) is True
    job_threads = getattr(runner, "_job_threads")
    job_threads[job.id].join(timeout=5)
    assert not job_threads[job.id].is_alive()
    return client, report_dir


def test_platform_runner_uploads_report_before_complete(tmp_path, monkeypatch):
    client, report_dir = _run_with_report(tmp_path, monkeypatch, fail_upload=False)
    assert client.calls == ["running", "report", "result", "evidence", "complete"]
    assert not report_dir.exists()


def test_platform_runner_retains_local_report_when_upload_fails(tmp_path, monkeypatch):
    client, report_dir = _run_with_report(tmp_path, monkeypatch, fail_upload=True)
    assert client.calls[0] == "running"
    assert client.calls.count("report") >= 2
    assert "complete" in client.calls
    assert report_dir.exists()
    last = getattr(client, "last_result", None)
    assert last is not None
    st = last.status.value if hasattr(last.status, "value") else str(last.status)
    assert st == "failed"
    assert "未能上传" in (last.error or "")


def test_platform_runner_uploads_partial_report_when_cancelled(tmp_path, monkeypatch):
    client, report_dir = _run_with_report(
        tmp_path, monkeypatch, fail_upload=False, cancelled=True
    )
    assert client.calls == ["running", "report", "result", "evidence", "complete"]
    assert not report_dir.exists()


def test_runner_replays_persisted_result_after_transport_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("MC_RUNNER_STATE_DIR", str(tmp_path))
    claim_time = "2026-11-22T01:02:03Z"
    calls = []

    class Client:
        def complete(self, job_id, runner_id, result, *, claimed_at):
            calls.append((job_id, runner_id, result.status.value, claimed_at))
            if len(calls) == 1:
                raise OSError("connection interrupted")

    client = cast(PlatformClient, Client())
    first = RunnerAgent("http://platform", runner_id="runner-1")
    first._submit_result(client, "job-1", JobResultIn(status=JobStatus.SUCCEEDED), claimed_at=claim_time)
    assert len(list(tmp_path.rglob("*.json"))) == 1

    restarted = RunnerAgent("http://platform", runner_id="runner-1")
    restarted._retry_pending_results(client)
    restarted._retry_pending_results(client)
    assert calls == [("job-1", "runner-1", "succeeded", claim_time)] * 2
    assert not list(tmp_path.rglob("*.json"))


def test_runner_stops_when_the_server_reassigns_its_claim(monkeypatch):
    monkeypatch.setattr(agent_module, "load_device_policy", lambda _runner_id: None)
    runner = RunnerAgent("http://platform", runner_id="runner-1")
    claim = JobOut(
        id="job-1", name="job", status=JobStatus.RUNNING,
        runner_id=runner.runner_id, claimed_at="2026-11-22T01:02:03Z",
    )
    stop = threading.Event()
    runner._cancel[claim.id] = stop
    runner._job_claim_generations[claim.id] = claim.claimed_at
    runner._poll_cancel(cast(PlatformClient, SimpleNamespace(get_job=lambda _jid: claim)))
    assert not stop.is_set()

    reassigned = replace(claim, claimed_at="2026-11-22T01:03:03Z")
    runner._poll_cancel(cast(PlatformClient, SimpleNamespace(get_job=lambda _jid: reassigned)))
    assert stop.is_set()


def test_structured_report_failure_preserves_html(tmp_path, monkeypatch):
    from autopilot_platform.ap import engine, report
    from autopilot_platform.ap.report import result_json
    from autopilot_platform.runner import execute

    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setattr(execute.tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(engine, "run_project_directory", lambda *_a, **_k: SimpleNamespace(
        name="suite", duration_ms=2, case_counts=lambda: {"passed": 1, "failed": 0, "total": 1},
    ))
    monkeypatch.setattr(report, "write_report", lambda _suite, path, **_k: open(
        path, "w", encoding="utf-8",
    ).close())
    monkeypatch.setattr(result_json, "cases_from_suite", lambda *_a, **_k: [])

    def fail_json(*_args, **_kwargs):
        raise OSError("structured report writer failed")

    monkeypatch.setattr(result_json, "write_result_json", fail_json)
    result = execute.execute_job(JobOut(
        id="job-2", name="example", status=JobStatus.CLAIMED, project_dir=str(project),
        platform="http",
    ))
    assert result.status == JobStatus.FAILED
    assert "result.json" in (result.error or "")
    assert result.report is not None
    assert (tmp_path / result.report.report_path).is_file()
