"""Platform Runner：槽位冲突走 nack，不 complete FAILED。"""

from __future__ import annotations

from unittest.mock import MagicMock

from autopilot_platform.core.constants import JobStatus
from autopilot_platform.core.schemas import JobOut
from autopilot_platform.runner.agent import RunnerAgent
from autopilot_platform.runner.job_slots import JobSlotTracker


def _job(jid: str, udids: list[str]) -> JobOut:
    return JobOut(
        id=jid,
        name=jid,
        status=JobStatus.CLAIMED,
        project_dir="/tmp",
        platform="android" if udids else "web",
        device_udids=udids,
    )


def test_overlap_nacks_instead_of_fail():
    t = JobSlotTracker()
    assert t.try_reserve("j1", ["x"]) == ""
    agent = RunnerAgent("http://127.0.0.1:9", runner_id="r1")
    agent._slots = t
    client = MagicMock()
    client.heartbeat.return_value = None
    client.claim.return_value = _job("j2", ["x"])
    client.complete.return_value = None
    agent._heartbeat_once = lambda *_a, **_k: None  # type: ignore[method-assign]
    assert agent.run_once(client) is True
    assert client.nack.called
    assert not client.complete.called
    assert client.nack.call_args.args[0] == "j2"
    assert "槽位冲突" in str(client.nack.call_args.kwargs.get("reason") or "")


def test_web_and_device_slots_recycle_independently():
    t = JobSlotTracker()
    assert t.try_reserve("web1", []) == ""
    assert t.try_reserve("and1", ["a1"]) == ""
    assert t.try_reserve("web2", []) != ""
    t.release("web1")
    assert t.try_reserve("web2", []) == ""
    assert t.busy_udids() == {"a1"}
    t.release("and1")
    assert t.try_reserve("and2", ["a1"]) == ""
    assert t.has_web()
