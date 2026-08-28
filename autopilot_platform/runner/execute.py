"""执行任务：调用本仓 engine 并写 HTML 报告。"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
import time
import zipfile

import httpx
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from .contract import JobOut, JobResultIn, JobStatus, ReportIndex, backends_ok
from autopilot_platform.ap.runtime.job_log import JOB_LOG_ID

if TYPE_CHECKING:
    from .client import PlatformClient


def _resolve_project_dir(
    job: JobOut, client: Optional[PlatformClient]
) -> tuple[str, Optional[str], Optional[str]]:
    project_dir = (job.project_dir or "").strip()
    if project_dir and os.path.isdir(project_dir):
        return project_dir, None, None

    aid = (job.artifact_id or "").strip()
    if aid and client is not None:
        try:
            dest = tempfile.mkdtemp(prefix=f"mc-art-{aid[:8]}-")
            path = client.download_artifact(aid, dest)
            return path, None, dest
        except (OSError, RuntimeError, ValueError, httpx.HTTPError) as exc:
            return "", f"制品下载失败：{exc}", None

    if project_dir:
        return "", f"工程目录不存在或不是目录：{project_dir!r}", None
    return "", "任务未提供可用的工程目录或制品 ID", None


class _ListHandler(logging.Handler):
    def __init__(self, job_id: str = "", flush=None) -> None:
        super().__init__(level=logging.INFO)
        self.lines: list[str] = []
        self._job_id = (job_id or "").strip()
        self._flush = flush
        self._flushed_upto = 0
        self._last_flush = time.monotonic()
        self.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        if self._job_id and JOB_LOG_ID.get() != self._job_id:
            return
        try:
            self.lines.append(self.format(record))
        except (ValueError, TypeError, OSError, AttributeError, RuntimeError):
            return
        self.flush_incremental()

    def flush_incremental(self, *, force: bool = False) -> None:
        if self._flush is None:
            return
        pending = len(self.lines) - self._flushed_upto
        if pending <= 0:
            return
        if not force and pending < 8 and (time.monotonic() - self._last_flush) < 2.0:
            return
        chunk = "\n".join(self.lines[self._flushed_upto :]) + "\n"
        self._flushed_upto = len(self.lines)
        self._last_flush = time.monotonic()
        try:
            self._flush(chunk)
        except (OSError, RuntimeError, ValueError, TypeError, AttributeError, httpx.HTTPError):
            pass


def _resolve_app_build_path(
    job: JobOut, client: Optional[PlatformClient]
) -> tuple[str, Optional[str], Optional[str]]:
    bid = (job.app_build_id or "").strip()
    if not bid:
        return "", None, None
    if client is None:
        return "", f"指定了应用构建 {bid}，但无法连接平台下载", None
    try:
        dest = tempfile.mkdtemp(prefix=f"mc-app-{bid[:8]}-")
        path = client.download_app_build(bid, dest)
        return path, None, dest
    except (OSError, RuntimeError, ValueError, httpx.HTTPError) as exc:
        return "", f"应用构建下载失败：{exc}", None


def _preflight_devices(job: JobOut) -> Optional[str]:
    udids = [u for u in (job.device_udids or []) if str(u).strip()]
    if not udids:
        return None
    from .devices import list_local_devices

    by_udid = {d.udid: d for d in list_local_devices()}
    for uid in udids:
        d = by_udid.get(uid)
        if d is None:
            return f"运行前本机未找到设备：{uid}"
        if (d.state or "").strip().lower() != "ready":
            note = (d.health_note or "").strip()
            return f"设备未就绪：{uid} 状态={d.state}" + (f"（{note}）" if note else "")
        if not backends_ok(
            d.backends,
            platform=str(job.platform or d.platform or ""),
            backend_mode=str(job.backend_mode or "auto"),
        ):
            return (
                f"设备后端不匹配：{uid} backends={list(d.backends)} "
                f"任务 backend_mode={job.backend_mode!r} platform={job.platform!r}"
            )
    return None


def _make_log_flusher(job: JobOut, client: Optional["PlatformClient"]):
    if client is None:
        return None
    fn = getattr(client, "append_job_log", None)
    if not callable(fn):
        return None
    job_id = str(getattr(job, "id", "") or "")
    if not job_id:
        return None
    runner_id = str(getattr(job, "runner_id", "") or "")

    def _flush(text: str) -> None:
        fn(job_id, runner_id, text, replace=False)

    return _flush


def execute_job(
    job: JobOut,
    client: Optional[PlatformClient] = None,
    *,
    cancel_event=None,
) -> JobResultIn:
    from autopilot_platform.ap.engine import FaultStrategy, run_project_directory  # 延迟：仅真正执行 Job
    from autopilot_platform.ap.report import ReportMeta, report_filename, write_report
    from autopilot_platform.ap.report.result_json import cases_from_suite, write_result_json

    t0 = time.monotonic()
    lines: list[str] = [
        f"[runner] job_id={job.id} name={job.name!r} platform={job.platform} "
        f"backend_mode={job.backend_mode or 'auto'}",
        f"[runner] artifact_id={job.artifact_id or ''} project_dir={job.project_dir or ''} "
        f"app_build_id={job.app_build_id or ''}",
    ]
    cleanup: list[str] = []

    def _run() -> JobResultIn:
        pre_err = _preflight_devices(job)
        if pre_err:
            lines.append(f"[runner] ERROR preflight: {pre_err}")
            return JobResultIn(status=JobStatus.FAILED, error=pre_err, log="\n".join(lines) + "\n")
        lines.append(f"[runner] preflight ok ({time.monotonic() - t0:.2f}s)")

        plat = (job.platform or "").strip().lower()
        if plat in ("android", "ios") and not (job.app_build_id or "").strip():
            lines.append(
                "[runner] WARN 未指定 app_build_id：用例制品与安装包分离，"
                "请在应用资源库选择要测的 apk/ipa 版本；设备已装且不安装则可忽略。"
            )

        project_dir, err, art_tmp = _resolve_project_dir(job, client)
        if art_tmp:
            cleanup.append(art_tmp)
        if err:
            lines.append(f"[runner] ERROR resolve: {err}")
            return JobResultIn(status=JobStatus.FAILED, error=err, log="\n".join(lines) + "\n")

        lines.append(f"[runner] project_dir={project_dir}")

        app_path, app_err, app_tmp = _resolve_app_build_path(job, client)
        if app_tmp:
            cleanup.append(app_tmp)
        if app_err:
            lines.append(f"[runner] ERROR app build: {app_err}")
            return JobResultIn(status=JobStatus.FAILED, error=app_err, log="\n".join(lines) + "\n")
        if app_path:
            lines.append(f"[runner] app_build_path={app_path}")

        report_tmp = tempfile.mkdtemp(prefix=f"mc-report-{job.id[:8]}-")
        cleanup.append(report_tmp)

        mode = "parallel_device" if job.parallel else "sequential"
        udids = list(job.device_udids or []) or None
        base_vars: dict = {}
        if udids and len(udids) == 1 and not job.parallel:
            base_vars["__device_udid__"] = udids[0]
        elif udids and len(udids) > 1 and not job.parallel:
            base_vars["__device_udid__"] = udids[0]
            lines.append(
                f"[runner] WARN non-parallel with {len(udids)} udids; using first={udids[0]}"
            )
        plat = (job.platform or "").strip().lower()
        if plat == "web":
            # web：backend_mode 承载浏览器类型（chrome/edge/firefox/headless）；auto=用例内指定
            bm = (job.backend_mode or "").strip().lower()
            if bm and bm != "auto":
                base_vars["__web_browser__"] = bm
            # web_engine 独立字段，不占用 backend_mode
            eng = str(getattr(job, "web_engine", None) or "selenium").strip().lower()
            if eng not in ("selenium", "playwright"):
                eng = "selenium"
            base_vars["__web_engine__"] = eng
            lines.append(
                f"[runner] web browser={base_vars.get('__web_browser__', 'auto')} "
                f"engine={eng}"
            )
        elif plat == "http":
            from autopilot_platform.ap.keywords.http.env import apply_job_http_env
            from autopilot_platform.ap.keywords.registry import KeywordError

            try:
                apply_job_http_env(
                    base_vars,
                    project_dir=project_dir,
                    profile=str(job.backend_mode or ""),
                )
            except KeywordError as env_err:
                lines.append(f"[runner] ERROR http env: {env_err}")
                return JobResultIn(
                    status=JobStatus.FAILED,
                    error=str(env_err),
                    log="\n".join(lines) + "\n",
                )
            lines.append(
                f"[runner] http env={base_vars.get('__http_env_profile__') or 'auto'} "
                f"base_url={base_vars.get('base_url') or ''}"
            )
        elif job.backend_mode:
            base_vars["__mobile_backend_mode__"] = job.backend_mode
        if app_path:
            base_vars["__app_build_path__"] = app_path

        lines.append(
            f"[runner] run mode={mode} udids={udids or []} workers={job.parallel_workers}"
        )
        entry_paths = [p for p in (job.entry_paths or []) if str(p).strip()]
        if entry_paths:
            lines.append(f"[runner] entry_paths={entry_paths}")
        if cancel_event is not None and cancel_event.is_set():
            lines.append("[runner] cancelled before run")
            return JobResultIn(
                status=JobStatus.FAILED,
                error="任务执行中被取消",
                log="\n".join(lines) + "\n",
            )

        handler = _ListHandler(str(job.id), flush=_make_log_flusher(job, client))
        root = logging.getLogger()
        token = JOB_LOG_ID.set(str(job.id))
        root.addHandler(handler)
        try:
            suite = run_project_directory(
                project_dir,
                mode=mode,
                platform=job.platform or "",
                parallel_workers=int(job.parallel_workers or 0),
                device_udids=udids if (job.parallel or (udids and len(udids) == 1)) else (
                    [udids[0]] if udids else None
                ),
                wda_bundle=job.wda_bundle or "",
                backend_mode=job.backend_mode or "auto",
                fault_strategy=FaultStrategy.CONTINUE,
                base_vars=base_vars or None,
                parallel_fault_isolation=True,
                cancel_event=cancel_event,
                entry_paths=entry_paths or None,
            )
        except Exception as run_err:
            lines.extend(handler.lines)
            lines.append(f"[runner] ERROR run: {run_err}")
            return JobResultIn(
                status=JobStatus.FAILED,
                error=f"执行失败：{run_err}",
                log="\n".join(lines) + "\n",
            )
        finally:
            handler.flush_incremental(force=True)
            root.removeHandler(handler)
            JOB_LOG_ID.reset(token)

        lines.extend(handler.lines)
        if cancel_event is not None and cancel_event.is_set():
            lines.append("[runner] cancelled during run")
            return JobResultIn(
                status=JobStatus.FAILED,
                error="任务执行中被取消",
                log="\n".join(lines) + "\n",
            )

        counts = suite.case_counts()
        lines.append(
            f"[runner] counts passed={counts.get('passed', 0)} failed={counts.get('failed', 0)} "
            f"total={counts.get('total', 0)} duration_ms={getattr(suite, 'duration_ms', 0)}"
        )
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = os.path.join(report_tmp, report_filename())
        try:
            meta = ReportMeta(
                project_dir=project_dir,
                platforms=[str(job.platform or "").strip()] if job.platform else [],
                backend_mode=str(job.backend_mode or "").strip(),
            )
            write_report(suite, out_path, generated_at=ts, meta=meta)
            lines.append(f"[runner] report={os.path.abspath(out_path)}")
        except (OSError, ValueError, TypeError, RuntimeError) as report_err:
            lines.append(f"[runner] ERROR report: {report_err}")
            return JobResultIn(
                status=JobStatus.FAILED,
                error=f"报告写入失败：{report_err}",
                report=ReportIndex(
                    passed=int(counts.get("passed", 0)),
                    failed=int(counts.get("failed", 0)),
                    total=int(counts.get("total", 0)),
                    duration_ms=int(getattr(suite, "duration_ms", 0) or 0),
                ),
                log="\n".join(lines) + "\n",
            )

        failed = int(counts.get("failed", 0))
        status = JobStatus.SUCCEEDED if failed == 0 else JobStatus.FAILED
        summary = (
            f"{suite.name}: {counts.get('passed', 0)}/{counts.get('total', 0)} passed, "
            f"{suite.duration_ms}ms"
        )
        try:
            result_path = os.path.join(report_tmp, "result.json")
            try:
                from autopilot_platform.ap import __version__ as _ap_ver
            except (ImportError, AttributeError):
                _ap_ver = ""
            write_result_json(
                result_path,
                job_id=str(getattr(job, "id", "") or ""),
                status=str(status.value),
                suite_name=getattr(suite, "name", "") or "suite",
                passed=int(counts.get("passed", 0)),
                failed=failed,
                total=int(counts.get("total", 0)),
                duration_ms=int(getattr(suite, "duration_ms", 0) or 0),
                summary=summary,
                artifact_id=getattr(job, "artifact_id", None) or "",
                app_build_id=getattr(job, "app_build_id", None) or "",
                project_id=getattr(job, "project_id", None) or "",
                platform=getattr(job, "platform", None) or "",
                backend_mode=getattr(job, "backend_mode", None) or "",
                device_udids=list(getattr(job, "device_udids", None) or []),
                html_report_path=os.path.abspath(out_path),
                cases=cases_from_suite(suite, project_dir=project_dir),
                runtime_version=str(_ap_ver or ""),
            )
            lines.append(f"[runner] result_json={os.path.abspath(result_path)}")
        except (OSError, ValueError, TypeError, RuntimeError) as result_err:
            lines.append(f"[runner] ERROR result.json: {result_err}")
            return JobResultIn(
                status=JobStatus.FAILED,
                error=f"result.json 写入失败：{result_err}",
                report=ReportIndex(
                    report_path=os.path.abspath(out_path),
                    passed=int(counts.get("passed", 0)),
                    failed=failed,
                    total=int(counts.get("total", 0)),
                    duration_ms=int(getattr(suite, "duration_ms", 0) or 0),
                    summary=summary,
                ),
                log="\n".join(lines) + "\n",
            )
        # D3：把工程内 evidence 打进 report_tmp，避免制品临时目录被清理后丢失
        try:
            ev_src = os.path.join(project_dir, "reports", "evidence")
            if os.path.isdir(ev_src) and any(os.scandir(ev_src)):
                zip_path = os.path.join(report_tmp, "evidence.zip")
                with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                    for root, _dirs, files in os.walk(ev_src):
                        for fn in files:
                            abs_f = os.path.join(root, fn)
                            # zip 内路径：reports/evidence/...
                            rel = os.path.relpath(abs_f, project_dir).replace("\\", "/")
                            zf.write(abs_f, rel)
                lines.append(f"[runner] evidence_zip={os.path.abspath(zip_path)}")
        except (OSError, ValueError, TypeError, RuntimeError) as ev_err:
            lines.append(f"[runner] WARN evidence.zip: {ev_err}")
        lines.append(f"[runner] done status={status.value} summary={summary}")
        keep_report = report_tmp
        cleanup[:] = [entry for entry in cleanup if entry != keep_report]
        return JobResultIn(
            status=status,
            error=None if failed == 0 else f"{failed} 个用例失败",
            report=ReportIndex(
                report_path=os.path.abspath(out_path),
                passed=int(counts.get("passed", 0)),
                failed=failed,
                total=int(counts.get("total", 0)),
                duration_ms=int(getattr(suite, "duration_ms", 0) or 0),
                summary=summary,
            ),
            log="\n".join(lines) + "\n",
        )

    raised: BaseException | None = None
    result: JobResultIn | None = None
    try:
        result = _run()
    except BaseException as exc:
        raised = exc
    for cleanup_dir in cleanup:
        shutil.rmtree(cleanup_dir, ignore_errors=True)
    if raised is not None:
        raise raised
    if result is None:
        raise RuntimeError("execute_job：内部错误，无执行结果")
    return result
