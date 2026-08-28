"""TURN 健康检查：未启用时 skip，避免 CI 无 coturn 失败。"""

from __future__ import annotations

import os

import pytest


@pytest.mark.skipif(
    os.environ.get("MC_TURN_ENABLED", "").strip() not in {"1", "true", "yes"},
    reason="MC_TURN_ENABLED not set; coturn optional",
)
def test_turn_health_ok_when_enabled():
    from autopilot_platform.platform.ops.turn_health import check_turn_health

    result = check_turn_health(timeout=5.0)
    assert result.get("status") in {"ok", "degraded"}, result
