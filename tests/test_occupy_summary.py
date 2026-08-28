"""设备占用摘要与预占用途解析。"""

from __future__ import annotations

from autopilot_platform.platform.services.execution.devices.scheduling import (
    build_occupy_summary,
    parse_reservation_purpose,
)


def test_parse_reservation_purpose():
    assert parse_reservation_purpose("[远控预留]调试") == "远控预留"
    assert parse_reservation_purpose("[手工调试]") == "手工调试"
    assert parse_reservation_purpose("[演示联调]客户") == "演示联调"
    assert parse_reservation_purpose("随便写") == ""


def test_build_occupy_summary_job():
    s = build_occupy_summary(
        busy_kind="job",
        busy_job_name="Smoke",
        busy_job_id="abcdefghij",
        busy_job_project_id="p1",
    )
    assert s.startswith("批跑占用")
    assert "Smoke" in s
    assert "abcdefg…" in s or "abcdefgh" in s
    assert "p1" in s


def test_build_occupy_summary_reservation():
    s = build_occupy_summary(
        busy_kind="reservation",
        reservation_username="alice",
        reservation_reason="[远控预留]联调",
    )
    assert s == "人工预占 · alice · 远控预留"
