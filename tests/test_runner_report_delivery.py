"""Platform Runner：报告须在 complete 之前上传；失败时保留本地文件。"""

from __future__ import annotations

import zipfile
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
