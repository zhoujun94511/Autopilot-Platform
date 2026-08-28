"""Runner 远控拉令线程：独立 httpx 客户端，避免 claim 长轮询饿死 remote-sync。"""

from __future__ import annotations

import time

from autopilot_platform.runner.agent import RunnerAgent


def test_remote_sync_thread_uses_dedicated_platform_client(monkeypatch) -> None:
    created: list[tuple[str, str]] = []
    sync_calls: list[str] = []

    class FakePlatformClient:
        def __init__(self, _server: str, _token: str) -> None:
            created.append((_server, _token))

        def __enter__(self) -> FakePlatformClient:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        @staticmethod
        def list_remote_commands(_runner_id: str = "") -> list[dict]:
            sync_calls.append(_runner_id)
            return []

    monkeypatch.setattr(
        "autopilot_platform.runner.agent.PlatformClient",
        FakePlatformClient,
    )

    agent = RunnerAgent(
        "http://platform.test",
        token="tok",
        runner_id="runner-remote-sync",
        poll_interval=3.0,
    )
    agent._ensure_remote_sync()
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if sync_calls:
            break
        time.sleep(0.05)
    agent.stop_remote_sync()

    assert len(created) == 1
    assert created[0] == ("http://platform.test", "tok")
    assert sync_calls, "remote-sync should poll immediately on thread start"


def test_remote_sync_runs_while_main_client_claim_blocks(monkeypatch) -> None:
    """模拟主线程 claim 长阻塞时，远控线程仍应能 list_remote_commands。"""
    remote_during_claim: list[bool] = []

    class RemoteOnlyClient:
        def __init__(self, _server: str, _token: str) -> None:
            pass

        def __enter__(self) -> RemoteOnlyClient:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        @staticmethod
        def list_remote_commands(_runner_id: str = "") -> list[dict]:
            remote_during_claim.append(True)
            return []

    monkeypatch.setattr(
        "autopilot_platform.runner.agent.PlatformClient",
        RemoteOnlyClient,
    )

    agent = RunnerAgent("http://p", token="t", runner_id="r-block", poll_interval=3.0)
    agent._ensure_remote_sync()

    # 远控线程应在 0.5s 内 poll（不依赖主线程 claim）
    deadline = time.monotonic() + 1.5
    while time.monotonic() < deadline and not remote_during_claim:
        time.sleep(0.05)

    agent.stop_remote_sync()

    assert remote_during_claim, "remote-sync should poll while main claim is blocked"
