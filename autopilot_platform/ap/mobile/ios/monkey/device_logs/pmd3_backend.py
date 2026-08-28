"""pymobiledevice3 syslog / crash 回退路径。"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import Callable, Optional


def _python() -> str:
    return sys.executable


def syslog_cmd(udid: str) -> list[str]:
    cmd = [_python(), "-m", "pymobiledevice3", "syslog", "live"]
    if udid:
        cmd += ["--udid", udid]
    return cmd


def crash_ls_cmd(udid: str) -> list[str]:
    cmd = [_python(), "-m", "pymobiledevice3", "crash", "ls"]
    if udid:
        cmd += ["--udid", udid]
    return cmd


def crash_pull_cmd(udid: str, target: str) -> list[str]:
    cmd = [_python(), "-m", "pymobiledevice3", "crash", "pull", target]
    if udid:
        cmd += ["--udid", udid]
    return cmd


def run_capture(cmd: list[str], *, timeout: int = 180) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, timeout=timeout)


def start_syslog(
    udid: str,
    out_path: str,
    *,
    log: Optional[Callable[[str], None]] = None,
) -> subprocess.Popen:
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    log = log or (lambda _m: None)
    out_f = open(out_path, "wb")  # noqa: SIM115
    # noinspection PyBroadException
    try:
        proc = subprocess.Popen(
            syslog_cmd(udid),
            stdout=out_f,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        out_f.close()
        raise
    proc._ap_syslog_file = out_f  # type: ignore[attr-defined]
    log(f"Monkey 设备日志：pymobiledevice3 syslog 已启动 pid={proc.pid}")
    return proc


def stop_syslog(proc: subprocess.Popen | None, *, wait_sec: float = 2.0) -> None:
    if proc is None:
        return
    from . import goios_backend
    goios_backend.stop_syslog(proc, wait_sec=wait_sec)
