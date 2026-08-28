"""冷启动追踪工具测试。"""

from __future__ import annotations

from autopilot_platform.runner.remote.android.cold_start_trace import (
    ColdStartTrace,
    get_active,
    mark,
    set_active,
)


def test_cold_start_trace_marks_and_summary(monkeypatch) -> None:
    monkeypatch.setenv("MC_REMOTE_COLD_TRACE", "1")
    trace = ColdStartTrace("session-abc-123", "UDID-TEST-1")
    set_active(trace)
    try:
        trace.mark("phase.a", foo=1)
        mark("phase.b")
        assert len(trace._marks) == 2
        assert get_active() is trace
        trace.summary("connected", ok=True)
    finally:
        set_active(None)
    assert get_active() is None


def test_cold_start_trace_disabled(monkeypatch) -> None:
    monkeypatch.setenv("MC_REMOTE_COLD_TRACE", "0")
    trace = ColdStartTrace("s1", "d1")
    trace.mark("ignored")
    assert trace._marks == []
