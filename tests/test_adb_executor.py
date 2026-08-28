"""adb_executor 串行队列。"""

from __future__ import annotations

import threading

import pytest


@pytest.fixture()
def adb_executor(monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "adbutils", __import__("unittest.mock").mock.MagicMock())
    for key in list(sys.modules):
        if key.startswith("autopilot_platform.runner.remote.android"):
            del sys.modules[key]
    return __import__(
        "autopilot_platform.runner.remote.android.adb_executor",
        fromlist=["adb_executor"],
    )


def test_submit_runs_on_worker_thread(adb_executor):
    main = threading.current_thread().ident
    seen: list[int] = []
    done = threading.Event()

    def work() -> None:
        seen.append(threading.current_thread().ident or 0)
        done.set()

    adb_executor.submit_adb_dispatch("serial-a", event_type="ping", work=work)
    assert done.wait(timeout=5.0)
    adb_executor.flush("serial-a")
    assert seen
    assert seen[0] != main


def test_heavy_commands_use_scrcpy_lock(adb_executor, monkeypatch):
    import sys
    import types

    entered = threading.Event()
    release = threading.Event()
    calls: list[str] = []

    class _FakeLock:
        def __enter__(self):
            calls.append("enter")
            entered.set()
            assert release.wait(timeout=2.0)
            return self

        def __exit__(self, *_args) -> None:
            calls.append("exit")

    fake_scrcpy = types.ModuleType(
        "autopilot_platform.runner.remote.android.scrcpyclients"
    )
    fake_scrcpy._reconfigure_lock_for = lambda _device_id: _FakeLock()
    monkeypatch.setitem(
        sys.modules,
        "autopilot_platform.runner.remote.android.scrcpyclients",
        fake_scrcpy,
    )

    def work() -> None:
        calls.append("work")

    adb_executor.submit_adb_dispatch("serial-b", event_type="app.list", work=work)
    assert entered.wait(timeout=2.0)
    release.set()
    adb_executor.flush("serial-b")
    assert calls == ["enter", "work", "exit"]
    adb_executor.shutdown_device("serial-b", wait=True)


def test_flush_drains_queue(adb_executor):
    order: list[int] = []

    for value in (1, 2, 3):
        adb_executor.submit_adb_dispatch(
            "serial-c",
            event_type="ping",
            work=lambda v=value: order.append(v),
        )
    adb_executor.flush("serial-c")
    assert order == [1, 2, 3]
    adb_executor.shutdown_device("serial-c", wait=True)
