"""Runner 主循环。"""

from __future__ import annotations

import os
import socket
import threading
import time
import uuid
from dataclasses import replace as dc_replace
from typing import Optional

import httpx

from autopilot_platform.core.constants import DEFAULT_API_TOKEN, JobStatus
from autopilot_platform.core.schemas import HeartbeatIn, JobResultIn, RunnerRegister

from .client import PlatformClient
from .devices import list_local_devices, probe_host_capabilities
from .device_policy import load_device_policy, update_device_policy
from .execute import execute_job
from .instance_lock import RunnerInstanceBusyError, RunnerInstanceLock
from .job_slots import JobSlotTracker

_HTTP_ERRS = (
    OSError,
    RuntimeError,
    ValueError,
    TypeError,
    AttributeError,
    httpx.HTTPError,
)


def _http_status_code(exc: httpx.HTTPStatusError) -> int | None:
    resp = exc.response
    if isinstance(resp, httpx.Response):
        return resp.status_code
    return None


def _package_version() -> str:
    try:
        from importlib.metadata import PackageNotFoundError, version
    except ImportError:
        return "0.1.0"
    try:
        return version("autopilot_platform")
    except PackageNotFoundError:
        return "0.1.0"


def default_runner_id() -> str:
    host = socket.gethostname() or "host"
    return f"{host}-{uuid.getnode():x}"


def _upload_report_bundle(
    client: PlatformClient,
    job_id: str,
    runner_id: str,
    report_path: str,
    *,
    attempts: int = 3,
) -> bool:
    """上传 report.html 与 result.json（若存在）；evidence.zip 尽力而为。"""
    if not report_path or not os.path.isfile(report_path):
        return False
    report_dir = os.path.dirname(os.path.abspath(report_path))

    def _retry(label: str, fn) -> bool:
        last: BaseException | None = None
        for i in range(max(1, int(attempts))):
            try:
                fn()
                return True
            except _HTTP_ERRS as exc:
                last = exc
                print(
                    f"[runner] {label} upload failed attempt={i + 1}: {exc}",
                    flush=True,
                )
                time.sleep(0.35 * (i + 1))
        if last is not None:
            print(f"[runner] {label} upload gave up: {last}", flush=True)
        return False

    t_up = time.monotonic()
    html_ok = _retry("report", lambda: client.upload_report(job_id, runner_id, report_path))
    if html_ok:
        print(
            f"[runner] upload report job={job_id} ({time.monotonic() - t_up:.2f}s)",
            flush=True,
        )
    result_json = os.path.join(report_dir, "result.json")
    json_ok = True
    if os.path.isfile(result_json):
        json_ok = _retry(
            "result.json",
            lambda: client.upload_result_json(job_id, runner_id, result_json),
        )
        if json_ok:
            print(f"[runner] upload result.json job={job_id}", flush=True)
    evidence_zip = os.path.join(report_dir, "evidence.zip")
    if os.path.isfile(evidence_zip):
        if _retry(
            "evidence.zip",
            lambda: client.upload_evidence_zip(job_id, runner_id, evidence_zip),
        ):
            print(f"[runner] upload evidence.zip job={job_id}", flush=True)
    return bool(html_ok and json_ok)


class RunnerAgent:
    def __init__(
        self,
        server: str,
        token: str = DEFAULT_API_TOKEN,
        *,
        runner_id: Optional[str] = None,
        poll_interval: float = 3.0,
        hostname: Optional[str] = None,
    ) -> None:
        self.server = server
        self.token = token
        self.runner_id = runner_id or default_runner_id()
        self.poll_interval = max(0.5, float(poll_interval))
        self.hostname = hostname or socket.gethostname()
        self._slots = JobSlotTracker()
        self._cancel: dict[str, threading.Event] = {}
        self._job_threads: dict[str, threading.Thread] = {}
        self._hb_guard = threading.Lock()
        self._hb_stop = threading.Event()
        self._hb_thread: Optional[threading.Thread] = None
        self._hb_client = None
        self._remote_guard = threading.Lock()
        self._remote_stop = threading.Event()
        self._remote_thread: Optional[threading.Thread] = None
        # Platform 暂不可达时仍沿用最近一次持久化 allowlist。
        self._device_policy = load_device_policy(self.runner_id)

    def _heartbeat_once(self, client: PlatformClient) -> None:
        inventory = list_local_devices()
        devices = self._device_policy.filter(inventory)
        caps, host_backends = probe_host_capabilities()
        body = HeartbeatIn(
            runner_id=self.runner_id,
            devices=devices,
            inventory=inventory,
            policy_revision=self._device_policy.revision,
            capabilities=caps,
            host_backends=host_backends,
        )
        try:
            response = client.heartbeat(body)
            self._device_policy = update_device_policy(
                self.runner_id, self._device_policy, response
            )
        except httpx.HTTPStatusError as exc:
            # 兜底：Platform 仍返回 404（旧版）时补注册再心跳一次
            if _http_status_code(exc) == 404:
                self.register(client)
                response = client.heartbeat(body)
                self._device_policy = update_device_policy(
                    self.runner_id, self._device_policy, response
                )
                return
            raise

    def _sync_remote_sessions(self, client: PlatformClient) -> None:
        """拉取 pending 远控会话并在本机拉起 scrcpy/WebRTC 或 iOS MJPEG。"""
        try:
            from typing import cast

            from .remote import get_hub
            from .remote.hub import RemotePlatformClient
            from .remote.prewarm import drain_prewarm_hints, ensure_adb_daemon

            ensure_adb_daemon()
            get_hub().sync(cast(RemotePlatformClient, client), runner_id=self.runner_id)
            try:
                hints = client.list_prewarm_hints(self.runner_id)
                drain_prewarm_hints(hints)
            except (*_HTTP_ERRS,) as exc:
                print(f"[runner] prewarm-hints: {exc}", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[runner] remote-sync: {exc}", flush=True)

    def _ensure_remote_sync(self) -> None:
        """空闲 claim 可阻塞 ~25s；独立线程 + 独立 httpx 客户端避免远控拉令被饿死。"""
        with self._remote_guard:
            if self._remote_thread is not None and self._remote_thread.is_alive():
                return
            self._remote_stop.clear()
            interval = min(0.5, max(0.25, float(self.poll_interval) / 6))

            def _loop() -> None:
                with PlatformClient(self.server, self.token) as rem_client:
                    while True:
                        try:
                            self._sync_remote_sessions(rem_client)
                        except (*_HTTP_ERRS,) as exc:
                            print(f"[runner] remote-sync-loop: {exc}", flush=True)
                        if self._remote_stop.wait(interval):
                            break

            self._remote_thread = threading.Thread(
                target=_loop, name=f"runner-remote-{self.runner_id}", daemon=True
            )
            self._remote_thread.start()

    def stop_remote_sync(self) -> None:
        with self._remote_guard:
            self._remote_stop.set()
            t = self._remote_thread
            self._remote_thread = None
        if t is not None and t.is_alive():
            t.join(timeout=2.0)

    def _poll_cancel(self, client: PlatformClient) -> None:
        items = list(self._cancel.items())
        if not items:
            return
        for jid, ev in items:
            if ev is None or ev.is_set():
                continue
            try:
                job = client.get_job(jid)
            except (*_HTTP_ERRS,) as exc:
                print(f"[runner] cancel-poll: {exc}", flush=True)
                continue
            st = job.status
            val = st.value if isinstance(st, JobStatus) else str(st)
            if val == JobStatus.CANCELLED.value:
                ev.set()
                print(f"[runner] job {jid} cancelled remotely; signaling stop", flush=True)

    def _ensure_exec_heartbeat(self, client: PlatformClient) -> None:
        with self._hb_guard:
            if self._hb_thread is not None and self._hb_thread.is_alive():
                return
            self._hb_client = client
            self._hb_stop.clear()

            def _loop() -> None:
                hb_client = self._hb_client
                while not self._hb_stop.wait(self.poll_interval):
                    if hb_client is None:
                        break
                    try:
                        self._heartbeat_once(hb_client)
                        self._sync_remote_sessions(hb_client)
                        self._poll_cancel(hb_client)
                    except (*_HTTP_ERRS,) as exc:
                        print(f"[runner] exec-heartbeat: {exc}", flush=True)

            self._hb_thread = threading.Thread(
                target=_loop, name=f"runner-hb-{self.runner_id}", daemon=True
            )
            self._hb_thread.start()

    def _maybe_stop_exec_heartbeat(self) -> None:
        with self._hb_guard:
            if self._slots.has_any():
                return
            self._hb_stop.set()
            t = self._hb_thread
            self._hb_thread = None
            self._hb_client = None
        if t is not None and t.is_alive():
            t.join(timeout=2.0)

    def _reap_job_threads(self) -> None:
        done = [jid for jid, th in list(self._job_threads.items()) if not th.is_alive()]
        for jid in done:
            th = self._job_threads.pop(jid, None)
            if th is not None:
                th.join(timeout=0.1)

    def _fail_claimed(self, client: PlatformClient, job_id: str, error: str) -> None:
        try:
            client.complete(
                job_id,
                self.runner_id,
                JobResultIn(
                    status=JobStatus.FAILED,
                    error=error,
                    log=f"[mc] {error}\n",
                ),
            )
        except (*_HTTP_ERRS,) as exc:
            print(f"[runner] complete failed for {job_id}: {exc}", flush=True)

    def _nack_claimed(self, client: PlatformClient, job_id: str, reason: str) -> None:
        try:
            client.nack(job_id, self.runner_id, reason=reason)
        except (*_HTTP_ERRS,) as exc:
            print(f"[runner] nack failed for {job_id}: {exc}", flush=True)

    def _run_claimed_job(self, job, cancel_ev: threading.Event) -> None:
        with PlatformClient(self.server, self.token) as client:
            try:
                try:
                    client.mark_running(job.id, self.runner_id)
                except (*_HTTP_ERRS, PermissionError) as exc:
                    print(f"[runner] skip job {job.id}: {exc}", flush=True)
                    self._fail_claimed(client, job.id, f"标记运行失败：{exc}")
                    return
                t_exec = time.monotonic()
                result = execute_job(job, client, cancel_event=cancel_ev)
                print(
                    f"[runner] execute job={job.id} status={result.status} "
                    f"({time.monotonic() - t_exec:.2f}s)",
                    flush=True,
                )
                if cancel_ev.is_set() and not (result.error or "").strip():
                    result = result.with_error("任务执行中被取消")
                report_path = (
                    (result.report.report_path if result.report else "") or ""
                )
                report_uploaded = False
                try:
                    if report_path:
                        report_uploaded = _upload_report_bundle(
                            client, job.id, self.runner_id, report_path
                        )
                except (*_HTTP_ERRS,) as exc:
                    print(
                        f"[runner] report upload failed; local files retained: {exc}",
                        flush=True,
                    )
                if report_path and os.path.isfile(report_path) and not report_uploaded:
                    note = "报告或 result.json 未能上传到平台（本地文件已保留）"
                    err = (result.error or "").strip()
                    merged = f"{err}; {note}" if err else note
                    st = result.status
                    st_val = st.value if hasattr(st, "value") else str(st)
                    new_status = result.status
                    if st_val != JobStatus.FAILED.value:
                        from autopilot_platform.runner.contract import JobStatus as RunnerJobStatus

                        new_status = RunnerJobStatus.FAILED
                    result = dc_replace(
                        result,
                        status=new_status,
                        error=merged,
                        log=(result.log or "") + f"\n[runner] {note}\n",
                    )
                t_done = time.monotonic()
                client.complete(job.id, self.runner_id, result)
                print(
                    f"[runner] complete job={job.id} ({time.monotonic() - t_done:.2f}s)",
                    flush=True,
                )
                if report_uploaded:
                    import shutil

                    parent = os.path.dirname(os.path.abspath(report_path))
                    base = os.path.basename(parent)
                    if base.startswith("mc-report-") and os.path.isdir(parent):
                        shutil.rmtree(parent, ignore_errors=True)
            finally:
                self._cancel.pop(job.id, None)
                self._slots.release(job.id)
                self._maybe_stop_exec_heartbeat()

    def run_once(self, client: PlatformClient) -> bool:
        self._heartbeat_once(client)
        self._ensure_remote_sync()
        self._sync_remote_sessions(client)
        self._reap_job_threads()

        t_claim = time.monotonic()
        wait_sec = 0 if self._slots.has_any() else min(25, max(0, int(self.poll_interval * 8)))
        job = client.claim(self.runner_id, wait_sec=wait_sec)
        if job is None:
            return self._slots.has_any()
        print(
            f"[runner] claim job={job.id} name={job.name!r} "
            f"({time.monotonic() - t_claim:.2f}s)",
            flush=True,
        )
        reason = self._slots.try_reserve(job.id, list(getattr(job, "device_udids", None) or []))
        if reason:
            print(f"[runner] reject job={job.id}: {reason}", flush=True)
            self._nack_claimed(client, job.id, f"本机设备槽位冲突：{reason}")
            return True
        cancel_ev = threading.Event()
        self._cancel[job.id] = cancel_ev
        self._ensure_exec_heartbeat(client)
        th = threading.Thread(
            target=self._run_claimed_job,
            args=(job, cancel_ev),
            name=f"runner-job-{str(job.id)[:8]}",
            daemon=True,
        )
        self._job_threads[job.id] = th
        th.start()
        return True

    def register(self, client: PlatformClient) -> None:
        caps, host_backends = probe_host_capabilities()
        ver = _package_version()
        print(
            f"[runner] register capabilities={caps} host_backends={host_backends} version={ver}",
            flush=True,
        )
        client.register(
            RunnerRegister(
                runner_id=self.runner_id,
                hostname=self.hostname,
                version=ver,
                capabilities=caps,
                host_backends=host_backends,
                registration_source="platform",
            )
        )
        if "android-remote" in caps:
            threading.Thread(
                target=self._prewarm_webrtc_background,
                name="runner-webrtc-prewarm",
                daemon=True,
            ).start()

    @staticmethod
    def _prewarm_webrtc_background() -> None:
        try:
            from .remote.prewarm import prewarm_webrtc_stack

            prewarm_webrtc_stack()
        except Exception as exc:  # noqa: BLE001
            print(f"[runner] webrtc prewarm skipped: {exc}", flush=True)


def run_forever(
    server: str,
    token: str = DEFAULT_API_TOKEN,
    *,
    runner_id: Optional[str] = None,
    poll_interval: float = 3.0,
    lock_dir: Optional[str] = None,
) -> None:
    agent = RunnerAgent(
        server, token, runner_id=runner_id, poll_interval=poll_interval
    )
    try:
        lock = RunnerInstanceLock(agent.runner_id, lock_dir=lock_dir)
        lock.acquire()
    except RunnerInstanceBusyError as exc:
        print(f"[runner] abort: {exc}", flush=True)
        raise SystemExit(2) from exc
    try:
        with PlatformClient(server, token) as client:
            agent.register(client)
            print(f"[runner] id={agent.runner_id} server={server}", flush=True)
            while True:
                try:
                    did = agent.run_once(client)
                    if not did:
                        # claim 已 wait；仅短退避，避免双重空闲等待
                        time.sleep(min(0.5, agent.poll_interval))
                except KeyboardInterrupt:
                    print("[runner] stopped", flush=True)
                    break
                except Exception as exc:
                    print(f"[runner] error: {exc}", flush=True)
                    time.sleep(agent.poll_interval)
    finally:
        agent.stop_remote_sync()
        lock.release()
