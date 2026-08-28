"""同机同 runner_id 跨进程实例锁（Platform Runner）。"""

from __future__ import annotations

import multiprocessing as mp
import os

import pytest

from autopilot_platform.runner.instance_lock import (
    RunnerInstanceBusyError,
    RunnerInstanceLock,
    lock_path_for,
)


def _hold_lock(runner_id: str, lock_dir: str, ready: mp.Queue, release: mp.Queue) -> None:
    lock = RunnerInstanceLock(runner_id, lock_dir=lock_dir)
    lock.acquire()
    ready.put(os.getpid())
    release.get(timeout=30)
    lock.release()


def test_same_runner_id_second_process_fails_fast(tmp_path):
    lock_dir = str(tmp_path / "locks")
    rid = "platform-same-id"
    ctx = mp.get_context("spawn")
    ready: mp.Queue = ctx.Queue()
    release: mp.Queue = ctx.Queue()
    proc = ctx.Process(target=_hold_lock, args=(rid, lock_dir, ready, release))
    proc.start()
    try:
        holder_pid = ready.get(timeout=15)
        assert isinstance(holder_pid, int) and holder_pid > 0
        with pytest.raises(RunnerInstanceBusyError, match=rid):
            RunnerInstanceLock(rid, lock_dir=lock_dir).acquire()
    finally:
        release.put(1)
        proc.join(timeout=10)
        if proc.is_alive():
            proc.terminate()
            proc.join(timeout=5)


def test_different_runner_id_not_blocked(tmp_path):
    lock_dir = str(tmp_path / "locks")
    a = RunnerInstanceLock("runner-a", lock_dir=lock_dir)
    b = RunnerInstanceLock("runner-b", lock_dir=lock_dir)
    a.acquire()
    try:
        b.acquire()
        assert b.held
    finally:
        b.release()
        a.release()


def test_lock_path_stable_for_same_id(tmp_path):
    p1 = lock_path_for("host-x", lock_dir=tmp_path)
    p2 = lock_path_for("host-x", lock_dir=tmp_path)
    assert p1 == p2


def test_platform_run_forever_aborts_when_lock_held(tmp_path, monkeypatch):
    from autopilot_platform.runner import agent as agent_mod

    lock_dir = str(tmp_path / "locks")
    rid = "platform-abort"
    held = RunnerInstanceLock(rid, lock_dir=lock_dir)
    held.acquire()
    try:

        class _BoomClient:
            def __init__(self, *a, **k):
                raise AssertionError("should not connect when lock fails")

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        monkeypatch.setattr(agent_mod, "PlatformClient", _BoomClient)
        with pytest.raises(SystemExit) as ei:
            agent_mod.run_forever(
                "http://127.0.0.1:9",
                "tok",
                runner_id=rid,
                lock_dir=lock_dir,
            )
        assert ei.value.code == 2
    finally:
        held.release()
