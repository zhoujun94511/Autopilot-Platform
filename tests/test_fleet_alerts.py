"""Runner 离线边沿告警。"""

from __future__ import annotations

import time
from datetime import timedelta
from unittest.mock import MagicMock

from autopilot_platform.platform.core.models import RunnerRow, utcnow
from autopilot_platform.platform.services.observability import fleet_alerts


def _mono_seq(start: float = 1000.0, step: float = 120.0):
    tick = {"v": start}

    def _next() -> float:
        tick["v"] += step
        return tick["v"]

    return _next


def test_runner_offline_edge_alerts_once(monkeypatch):
    fleet_alerts.reset_fleet_alert_state()
    monkeypatch.setattr(fleet_alerts, "alert_on_runner_offline", lambda: True)
    monkeypatch.setattr(fleet_alerts, "alert_webhook_url", lambda: "http://127.0.0.1:9/alert")
    monkeypatch.setattr(fleet_alerts, "alert_runner_offline_cooldown_sec", lambda: 60)
    monkeypatch.setattr(time, "monotonic", _mono_seq())

    sent: list[tuple[str, str]] = []

    def _capture(event: str, *, summary: str, detail=None):
        _ = detail
        sent.append((event, summary))

    monkeypatch.setattr(
        "autopilot_platform.platform.ops.notify.notify_alert",
        _capture,
    )

    now = utcnow()
    online = RunnerRow(
        runner_id="r1",
        hostname="host-a",
        last_heartbeat_at=now,
    )
    db = MagicMock()

    def _scalars(_stmt):
        result = MagicMock()
        result.all.return_value = [online]
        return result

    db.scalars.side_effect = _scalars

    assert fleet_alerts.check_runner_offline_alerts(db) == []
    assert sent == []

    online.last_heartbeat_at = now - timedelta(hours=2)
    ids = fleet_alerts.check_runner_offline_alerts(db)
    assert ids == ["r1"]
    assert sent and sent[0][0] == "runners.offline"

    # 冷却内不再告警
    sent.clear()
    assert fleet_alerts.check_runner_offline_alerts(db) == []
    assert sent == []


def test_runner_offline_disabled(monkeypatch):
    fleet_alerts.reset_fleet_alert_state()
    monkeypatch.setattr(fleet_alerts, "alert_on_runner_offline", lambda: False)
    monkeypatch.setattr(fleet_alerts, "alert_webhook_url", lambda: "http://127.0.0.1:9/alert")
    db = MagicMock()
    assert fleet_alerts.check_runner_offline_alerts(db) == []


def test_device_pool_empty_edge(monkeypatch):
    fleet_alerts.reset_fleet_alert_state()
    monkeypatch.setattr(fleet_alerts, "alert_on_device_empty", lambda: True)
    monkeypatch.setattr(fleet_alerts, "alert_webhook_url", lambda: "http://127.0.0.1:9/alert")
    monkeypatch.setattr(fleet_alerts, "alert_runner_offline_cooldown_sec", lambda: 60)
    monkeypatch.setattr(time, "monotonic", _mono_seq())

    sent: list[str] = []

    def _capture(event: str, *, summary: str, detail=None):
        _ = summary, detail
        sent.append(event)

    monkeypatch.setattr(
        "autopilot_platform.platform.ops.notify.notify_alert",
        _capture,
    )
    monkeypatch.setattr(
        fleet_alerts,
        "_count_online_runners",
        lambda _db, *, now: 1,
    )
    counts = {"n": 2}

    def _devices(_db, *, now):
        _ = now
        return counts["n"]

    monkeypatch.setattr(fleet_alerts, "_count_online_devices", _devices)

    db = MagicMock()
    assert fleet_alerts.check_device_pool_empty_alerts(db) is False
    counts["n"] = 0
    assert fleet_alerts.check_device_pool_empty_alerts(db) is True
    assert sent == ["devices.pool_empty"]
    sent.clear()
    assert fleet_alerts.check_device_pool_empty_alerts(db) is False
    assert sent == []
