"""本机托管 Runner：由 Platform 进程 subprocess 拉起 / 终止。

浏览器无法在用户 PC 上直接起进程；此模块仅适用于 Platform 与 Runner 同机
且绑定 loopback 的联调场景。须显式 ``MC_ALLOW_MANAGED_RUNNER=1``；
非 loopback（含 ``0.0.0.0`` / ``--lan``）一律禁止 Web 启停。
"""

from __future__ import annotations

import collections
import logging
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Deque, Optional, TextIO

from sqlalchemy.orm import Session

from autopilot_platform.core.schemas import (
    ManagedRunnerLogsOut,
    ManagedRunnerStatusOut,
    RunnerRegister,
)

from ....core import api_messages as msg
from ....core.settings import (
    allow_managed_runner,
    managed_runner_deny_message,
    managed_runner_id,
    managed_runner_server,
    platform_logs_root,
)
from ....core.models import RunnerRow, db_get
from .registry import (
    issue_runner_token,
    register_runner,
    set_device_inventory,
)

log = logging.getLogger("autopilot_platform.platform.managed_runner")

_LOG_MAX = 500
_STOP_WAIT_SEC = 8.0


def managed_runner_log_path() -> Path:
    return platform_logs_root() / "managed-runner.log"


def probe_local_devices(db: Session):
    """扫描 Platform 主机设备并写入 managed-local 候选清单，不创建 DeviceRow。"""
    from autopilot_platform.runner.devices import list_local_devices

    rid = managed_runner_id()
    row = db_get(db, RunnerRow, rid)
    if row is None:
        row = RunnerRow(
            runner_id=rid,
            hostname=os.environ.get("COMPUTERNAME")
            or os.environ.get("HOSTNAME")
            or "managed-host",
            version="managed",
            registration_source="managed",
        )
        db.add(row)
        db.commit()
    # 探测 inventory 不代表 Runner 进程在线；勿写 last_heartbeat_at（避免假在线）。
    devices = list_local_devices()
    return set_device_inventory(db, rid, devices)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ManagedRunnerManager:
    """进程内单例：托管一个本机 Runner 子进程。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._proc: Optional[subprocess.Popen[str]] = None
        self._reader: Optional[threading.Thread] = None
        self._started_at: Optional[datetime] = None
        self._last_error: str = ""
        self._exit_code: Optional[int] = None
        self._log: Deque[str] = collections.deque(maxlen=_LOG_MAX)
        self._log_file: Optional[TextIO] = None
        self._log_file_path: Path = managed_runner_log_path()
        self._token: str = ""
        self._runner_id: str = managed_runner_id()

    def status(self, *, log_lines: int = 40) -> ManagedRunnerStatusOut:
        with self._lock:
            self._reap_unlocked()
            running = self._is_running_unlocked()
            n = max(0, min(int(log_lines), _LOG_MAX))
            tail = list(self._log)[-n:] if n else []
            rid = self._runner_id or managed_runner_id()
            return ManagedRunnerStatusOut(
                enabled=allow_managed_runner(),
                running=running,
                managed=running or self._started_at is not None,
                pid=self._proc.pid if running and self._proc else None,
                runner_id=rid,
                started_at=self._started_at,
                last_error=self._last_error,
                exit_code=None if running else self._exit_code,
                log_tail=tail,
                log_file=str(self._log_file_path),
                cli_command=self.cli_command(rid),
            )

    def logs(self, *, lines: int = 100) -> ManagedRunnerLogsOut:
        st = self.status(log_lines=lines)
        return ManagedRunnerLogsOut(
            runner_id=st.runner_id,
            lines=st.log_tail,
            running=st.running,
            pid=st.pid,
            log_file=st.log_file,
        )

    @staticmethod
    def cli_command(runner_id: str | None = None) -> str:
        """供 UI/API 复制的启动示例；永不嵌入真实 Token（AUD-2026-01）。

        真实凭据仅经 ``issue_runner_token`` 签发后用于本机 subprocess / env，
        不进入 ``ManagedRunnerStatusOut.cli_command``、日志或可复制命令。
        """
        rid = (runner_id or managed_runner_id()).strip() or managed_runner_id()
        server = managed_runner_server()
        return (
            f"python -m autopilot_platform.runner "
            f"--server {server} --token-env MC_RUNNER_TOKEN --runner-id {rid}"
        )

    def start(
        self,
        db: Session,
        *,
        org_id: str | None = None,
        project_ids: list[str] | None = None,
        poll_interval: float = 3.0,
        popen_factory=None,
    ) -> ManagedRunnerStatusOut:
        if not allow_managed_runner():
            raise PermissionError(managed_runner_deny_message())

        with self._lock:
            self._reap_unlocked()
            if self._is_running_unlocked():
                pid = self._proc.pid if self._proc else 0
                raise ValueError(msg.MANAGED_RUNNER_ALREADY_RUNNING.format(pid=pid))

            rid = managed_runner_id()
            self._runner_id = rid
            self._last_error = ""
            self._exit_code = None

            # 确保注册行存在，再签发独立 scope token（勿把 admin token 交给 Runner）
            register_runner(
                db,
                RunnerRegister(
                    runner_id=rid,
                    hostname=os.environ.get("COMPUTERNAME")
                    or os.environ.get("HOSTNAME")
                    or "managed-host",
                    version="managed",
                    capabilities=["managed"],
                    registration_source="managed",
                ),
                registration_source="managed",
            )
            _, raw, _, _ = issue_runner_token(
                db,
                rid,
                org_id=org_id,
                project_ids=project_ids,
            )
            self._token = raw

            server = managed_runner_server()
            # Token 只进 env，不进 argv，避免进程列表 / 审计命令行泄露（AUD-2026-01）
            cmd = [
                sys.executable,
                "-m",
                "autopilot_platform.runner",
                "--server",
                server,
                "--runner-id",
                rid,
                "--poll-interval",
                str(max(0.5, float(poll_interval))),
            ]
            env = os.environ.copy()
            # 子进程用独立 scoped token，避免误用 admin / 全局通道
            env["MC_API_TOKEN"] = raw
            env["MC_RUNNER_ID"] = rid
            env["MC_SERVER"] = server

            factory = popen_factory or subprocess.Popen
            try:
                proc = factory(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    env=env,
                    bufsize=1,
                )
            except OSError as exc:
                self._last_error = str(exc)
                raise RuntimeError(
                    msg.MANAGED_RUNNER_START_FAILED.format(detail=str(exc))
                ) from exc

            self._proc = proc
            self._started_at = _utcnow()
            self._open_log_file()
            self._append_log(f"[managed] started pid={proc.pid} runner_id={rid}")
            self._reader = threading.Thread(
                target=self._read_stdout,
                args=(proc,),
                name=f"managed-runner-log-{proc.pid}",
                daemon=True,
            )
            self._reader.start()
            log.info("managed runner started pid=%s id=%s", proc.pid, rid)
            return self.status()

    def stop(self, *, timeout: float = _STOP_WAIT_SEC) -> ManagedRunnerStatusOut:
        if not allow_managed_runner():
            raise PermissionError(managed_runner_deny_message())

        with self._lock:
            self._reap_unlocked()
            if not self._is_running_unlocked() or self._proc is None:
                raise ValueError(msg.MANAGED_RUNNER_NOT_RUNNING)
            proc = self._proc
            pid = proc.pid
            self._append_log(f"[managed] stopping pid={pid}")
            try:
                proc.terminate()
            except OSError as exc:
                self._last_error = str(exc)
                raise RuntimeError(
                    msg.MANAGED_RUNNER_STOP_FAILED.format(detail=str(exc))
                ) from exc

        deadline = time.monotonic() + max(0.5, float(timeout))
        while time.monotonic() < deadline:
            with self._lock:
                self._reap_unlocked()
                if not self._is_running_unlocked():
                    break
            time.sleep(0.15)
        else:
            with self._lock:
                if self._proc is not None and self._is_running_unlocked():
                    try:
                        self._proc.kill()
                    except OSError:
                        pass
                    self._reap_unlocked()

        with self._lock:
            self._append_log(f"[managed] stopped pid={pid}")
            self._close_log_file()
            log.info("managed runner stopped pid=%s", pid)
            return self.status()

    def shutdown(self) -> None:
        """应用退出时尽力终止托管子进程。"""
        try:
            with self._lock:
                self._reap_unlocked()
                if self._is_running_unlocked():
                    pass
                else:
                    return
            self.stop(timeout=3.0)
        except (ValueError, RuntimeError, PermissionError, OSError):
            with self._lock:
                if self._proc is not None:
                    try:
                        self._proc.kill()
                    except OSError:
                        pass

    def _is_running_unlocked(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def _reap_unlocked(self) -> None:
        if self._proc is None:
            return
        code = self._proc.poll()
        if code is None:
            return
        self._exit_code = int(code)
        if code != 0 and not self._last_error:
            self._last_error = f"process exited with code {code}"
        self._append_log(f"[managed] exited code={code}")
        self._proc = None

    def _append_log(self, line: str) -> None:
        text = (line or "").rstrip("\r\n")
        if not text:
            return
        self._log.append(text)
        handle = self._log_file
        if handle is None:
            return
        try:
            handle.write(text + "\n")
            handle.flush()
        except OSError as exc:
            self._last_error = self._last_error or f"log write failed: {exc}"

    def _open_log_file(self) -> None:
        self._close_log_file()
        path = self._log_file_path
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._log_file = path.open("a", encoding="utf-8", errors="replace")
            stamp = _utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
            self._log_file.write(f"\n--- managed runner session {stamp} ---\n")
            self._log_file.write(f"[managed] log file: {path}\n")
            self._log_file.flush()
        except OSError as exc:
            self._log_file = None
            self._last_error = self._last_error or f"log open failed: {exc}"

    def _close_log_file(self) -> None:
        handle = self._log_file
        self._log_file = None
        if handle is None:
            return
        try:
            handle.close()
        except OSError:
            pass

    def _read_stdout(self, proc: subprocess.Popen[str]) -> None:
        stream = proc.stdout
        if stream is None:
            return
        try:
            for line in stream:
                with self._lock:
                    self._append_log(line)
        except (OSError, ValueError, TypeError):
            pass
        finally:
            try:
                stream.close()
            except OSError:
                pass


_manager = ManagedRunnerManager()


def get_managed_runner_manager() -> ManagedRunnerManager:
    return _manager


def reset_managed_runner_manager_for_tests() -> ManagedRunnerManager:
    """测试用：重置单例（先停旧进程）。"""
    global _manager
    try:
        _manager.shutdown()
    except (OSError, RuntimeError, ValueError, TypeError, AttributeError):
        pass
    _manager = ManagedRunnerManager()
    return _manager
