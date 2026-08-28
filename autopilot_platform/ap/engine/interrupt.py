"""长步骤协作式中断：取消/暂停探测、可中断 sleep、子进程登记。"""

from __future__ import annotations

import subprocess
import threading
import time
from typing import Any, Optional

_CHILD_PROCS_KEY = "__run_child_procs__"


class RunInterrupted(Exception):
    """用户停止或执行流控中断（非用例失败）。"""


def bind_run_control(
    ctx: Any,
    cancel_event: Optional[threading.Event],
    pause_event: Optional[threading.Event],
) -> None:
    ctx.variables["__run_cancel_event__"] = cancel_event
    ctx.variables["__run_pause_event__"] = pause_event


def _cancel_event(ctx: Any) -> Optional[threading.Event]:
    ev = ctx.get_var("__run_cancel_event__")
    return ev if isinstance(ev, threading.Event) else None


def _pause_event(ctx: Any) -> Optional[threading.Event]:
    ev = ctx.get_var("__run_pause_event__")
    return ev if isinstance(ev, threading.Event) else None


def flow_checkpoint(ctx: Any) -> bool:
    """长步骤内检查点：暂停则阻塞；返回 True 表示应中止（已取消）。"""
    from .run_control import checkpoint

    return checkpoint(_cancel_event(ctx), _pause_event(ctx))


def run_cancelled(ctx: Any) -> bool:
    ev = _cancel_event(ctx)
    return ev is not None and ev.is_set()


def interruptible_sleep(seconds: float, ctx: Any) -> None:
    if seconds <= 0:
        if flow_checkpoint(ctx):
            raise RunInterrupted("用户停止")
        return
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if flow_checkpoint(ctx):
            raise RunInterrupted("用户停止")
        # checkpoint 自身耗时可能已越过 deadline，负值会让 time.sleep 抛 ValueError
        time.sleep(max(0.0, min(0.05, deadline - time.monotonic())))


def register_child_proc(ctx: Any, proc: subprocess.Popen) -> None:
    procs = ctx.variables.setdefault(_CHILD_PROCS_KEY, [])
    if proc not in procs:
        procs.append(proc)


def unregister_child_proc(ctx: Any, proc: subprocess.Popen) -> None:
    procs = ctx.variables.get(_CHILD_PROCS_KEY)
    if not isinstance(procs, list):
        return
    try:
        procs.remove(proc)
    except ValueError:
        pass


def terminate_child_procs(ctx: Any) -> None:
    procs = ctx.variables.get(_CHILD_PROCS_KEY)
    if not isinstance(procs, list):
        return
    for proc in list(procs):
        # noinspection PyBroadException
        try:
            if proc.poll() is None:
                proc.terminate()
        except Exception:
            pass
    deadline = time.monotonic() + 5.0
    for proc in list(procs):
        # noinspection PyBroadException
        try:
            if proc.poll() is None:
                proc.wait(timeout=max(0, int(deadline - time.monotonic())))
        except Exception:
            # noinspection PyBroadException
            try:
                proc.kill()
            except Exception:
                pass
    procs.clear()


def adb_shell_cancellable(
    command: str,
    ctx: Any,
    *,
    serial: str = "",
    poll_sec: float = 0.1,
) -> str:
    """adb shell 可中断版：取消时 terminate 子进程。"""
    from ..mobile.adb import audit_adb_shell, ensure_adb

    exe = ensure_adb()
    if exe is None:
        raise RuntimeError("未找到 adb")
    shell_cmd = (command or "").strip()
    if not shell_cmd:
        raise RuntimeError("adb shell 命令为空")
    audit_adb_shell(shell_cmd, serial=serial, via="adb_shell_cancellable")
    cmd = [str(exe)]
    if serial:
        cmd += ["-s", serial]
    cmd += ["shell", shell_cmd]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    register_child_proc(ctx, proc)
    try:
        while proc.poll() is None:
            if flow_checkpoint(ctx):
                # noinspection PyBroadException
                try:
                    proc.terminate()
                except Exception:
                    pass
                # noinspection PyBroadException
                try:
                    proc.wait(timeout=5)
                except Exception:
                    # noinspection PyBroadException
                    try:
                        proc.kill()
                    except Exception:
                        pass
                raise RunInterrupted("用户停止")
            time.sleep(poll_sec)
        out = (proc.stdout.read() if proc.stdout else b"").decode("utf-8", "replace")
        err = (proc.stderr.read() if proc.stderr else b"").decode("utf-8", "replace")
        if proc.returncode != 0:
            raise RuntimeError(f"adb shell 失败({proc.returncode}): {command}\n{err or out}")
        return out
    finally:
        unregister_child_proc(ctx, proc)
