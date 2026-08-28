"""go-ios syslog / crash 命令封装（只启动本模块拥有的子进程）。"""

from __future__ import annotations

import os
import subprocess
from typing import Callable, Optional

from ....ios_bootstrap import AGENT_ENV, resolve_go_ios


def available() -> bool:
    return resolve_go_ios() is not None


def _exe() -> str:
    path = resolve_go_ios()
    if path is None:
        raise RuntimeError("go-ios 不可用")
    return str(path)


def syslog_cmd(udid: str) -> list[str]:
    cmd = [_exe()]
    if udid:
        cmd += ["--udid", udid]
    cmd.append("syslog")
    return cmd


def crash_ls_cmd(udid: str) -> list[str]:
    cmd = [_exe()]
    if udid:
        cmd += ["--udid", udid]
    cmd += ["crash", "ls"]
    return cmd


def crash_cp_cmd(udid: str, pattern: str, target: str) -> list[str]:
    cmd = [_exe()]
    if udid:
        cmd += ["--udid", udid]
    cmd += ["crash", "cp", pattern, target]
    return cmd


def run_capture(cmd: list[str], *, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        capture_output=True,
        timeout=timeout,
        env={**os.environ, **AGENT_ENV},
    )


def start_syslog(
    udid: str,
    out_path: str,
    *,
    log: Optional[Callable[[str], None]] = None,
) -> subprocess.Popen:
    """启动 syslog 子进程；stdout 写入 out_path。调用方负责 terminate。"""
    return _start_stream(out_path, syslog_cmd(udid), log=log, label="syslog")


def ostrace_cmd(
    udid: str,
    *,
    process: str = "",
    match: str = "",
    level: str = "default,info,error,fault",
) -> list[str]:
    cmd = [_exe()]
    if udid:
        cmd += ["--udid", udid]
    cmd += ["ostrace", "--follow"]
    if process:
        cmd.append(f"--process={process}")
    if match:
        cmd.append(f"--match={match}")
    if level:
        cmd.append(f"--level={level}")
    return cmd


def start_ostrace(
    udid: str,
    out_path: str,
    *,
    process: str = "",
    match: str = "",
    log: Optional[Callable[[str], None]] = None,
) -> subprocess.Popen:
    """启动 ostrace 子进程（设备侧按进程过滤，适合长跑）。"""
    return _start_stream(
        out_path,
        ostrace_cmd(udid, process=process, match=match),
        log=log,
        label="ostrace",
    )


def _start_stream(
    out_path: str,
    cmd: list[str],
    *,
    log: Optional[Callable[[str], None]] = None,
    label: str = "syslog",
) -> subprocess.Popen:
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    log = log or (lambda _m: None)
    out_f = open(out_path, "wb")  # noqa: SIM115
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=out_f,
            stderr=subprocess.DEVNULL,
            env={**os.environ, **AGENT_ENV},
        )
    except OSError:
        out_f.close()
        raise
    proc._ap_syslog_file = out_f  # type: ignore[attr-defined]
    log(f"Monkey 设备日志：go-ios {label} 已启动 pid={proc.pid}")
    return proc


def stop_syslog(proc: subprocess.Popen | None, *, wait_sec: float = 2.0) -> None:
    """终止 syslog 子进程；不触碰隧道 / runwda / WDA。"""
    if proc is None:
        return
    # noinspection PyBroadException
    try:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=wait_sec)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=1)
    except Exception:
        pass
    f = getattr(proc, "_ap_syslog_file", None)
    if f is not None:
        # noinspection PyBroadException
        try:
            f.close()
        except Exception:
            pass
