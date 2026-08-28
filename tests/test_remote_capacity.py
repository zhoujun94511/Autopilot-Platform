"""远控容量、冷启动限流、占用后 prewarm。"""

from __future__ import annotations

import threading
import time
from typing import Any, cast

from autopilot_platform.runner.remote.capacity import ColdStartGate, max_concurrent_remote
from autopilot_platform.runner.remote.hub import RemotePlatformClient, RemoteSessionHub


def test_max_concurrent_remote_default(monkeypatch) -> None:
    monkeypatch.delenv("AUTOPILOT_MAX_CONCURRENT_REMOTE", raising=False)
    assert max_concurrent_remote() == 4


def test_cold_start_gate_limits_parallel(monkeypatch) -> None:
    monkeypatch.setenv("AUTOPILOT_REMOTE_COLD_START_LIMIT", "1")
    gate = ColdStartGate()
    assert gate.acquire(timeout=1.0) is True
    acquired = threading.Event()

    def _worker() -> None:
        if gate.acquire(timeout=0.2):
            acquired.set()
            gate.release()

    th = threading.Thread(target=_worker, daemon=True)
    th.start()
    th.join(timeout=1.0)
    assert not acquired.is_set()
    gate.release()
    time.sleep(0.05)
    acquired.clear()
    th2 = threading.Thread(target=_worker, daemon=True)
    th2.start()
    th2.join(timeout=1.0)
    assert acquired.is_set()


def test_hub_defers_spawn_when_at_capacity(monkeypatch) -> None:
    monkeypatch.setenv("AUTOPILOT_MAX_CONCURRENT_REMOTE", "1")
    started: list[str] = []

    class _FakeClient:
        commands = [
            {
                "session_id": "s1",
                "udid": "U1",
                "platform": "android",
                "status": "pending",
                "ice_servers": [],
            },
            {
                "session_id": "s2",
                "udid": "U2",
                "platform": "android",
                "status": "pending",
                "ice_servers": [],
            },
        ]

        def list_remote_commands(self, _runner_id: str = "") -> list[dict[str, Any]]:
            return list(self.commands)

        @staticmethod
        def list_prewarm_hints(_runner_id: str = "") -> list[dict[str, Any]]:
            return []

    class _StubSession:
        @staticmethod
        def start() -> None:
            started.append("ok")

        def stop(self) -> None:
            return

    def _fake_spawn(*_args: Any, **_kwargs: Any) -> _StubSession:
        return _StubSession()

    monkeypatch.setattr(RemoteSessionHub, "_spawn", staticmethod(_fake_spawn))
    monkeypatch.setattr(
        "autopilot_platform.runner.remote.hub.prewarm_android_scrcpy",
        lambda _udid: None,
    )

    hub = RemoteSessionHub()
    fake = cast(RemotePlatformClient, _FakeClient())
    hub.sync(fake, runner_id="r1")
    assert hub.active_session_count() == 1
    assert len(started) == 1

    hub.sync(fake, runner_id="r1")
    assert hub.active_session_count() == 1
    assert len(started) == 1


def test_hub_respawns_dead_session(monkeypatch) -> None:
    started: list[str] = []

    class _FakeClient:
        commands = [
            {
                "session_id": "s-dead",
                "udid": "U-DEAD",
                "platform": "android",
                "status": "pending",
                "ice_servers": [],
            }
        ]

        def list_remote_commands(self, _runner_id: str = "") -> list[dict[str, Any]]:
            return list(self.commands)

        @staticmethod
        def list_prewarm_hints(_runner_id: str = "") -> list[dict[str, Any]]:
            return []

    class _DeadSession:
        @staticmethod
        def start() -> None:
            started.append("start")

        @staticmethod
        def stop() -> None:
            started.append("stop")

        @staticmethod
        def is_alive() -> bool:
            return False

    def _fake_spawn(*_args: Any, **_kwargs: Any) -> _DeadSession:
        return _DeadSession()

    monkeypatch.setattr(RemoteSessionHub, "_spawn", staticmethod(_fake_spawn))
    monkeypatch.setattr(
        "autopilot_platform.runner.remote.hub.prewarm_android_scrcpy",
        lambda _udid: None,
    )

    hub = RemoteSessionHub()
    fake = cast(RemotePlatformClient, _FakeClient())
    hub.sync(fake, runner_id="r1")
    assert started == ["start"]
    hub.sync(fake, runner_id="r1")
    assert started == ["start", "stop", "start"]
    assert hub.active_session_count() == 1
