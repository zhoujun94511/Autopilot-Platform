"""AgentOps 聚合与 API 冒烟。"""

from __future__ import annotations

from collections import Counter
from unittest.mock import MagicMock

from autopilot_platform.platform.services.observability import agentops as agentops_mod


def test_scan_result_payload_counts_hits():
    acc = {
        "intent_steps": 0,
        "heal_count": 0,
        "vision_steps": 0,
        "vision_tokens_sum": 0,
        "latency_sum_ms": 0,
        "latency_n": 0,
        "evidence_steps": 0,
        "binding_hit": Counter(),
        "resolve_strategy": Counter(),
        "fail_reason": Counter(),
        "verification_status": Counter(),
    }
    payload = {
        "cases": [
            {
                "name": "c1",
                "steps": [
                    {
                        "intent_id": "s1",
                        "binding_hit": "cache",
                        "resolve_strategy": "cache",
                        "latency_ms": 120,
                    },
                    {
                        "intent_id": "s2",
                        "binding_hit": "healed",
                        "heal_applied": True,
                        "fail_reason": "timeout",
                        "resolve_strategy": "vision",
                        "perception_used_screenshot": True,
                        "vision_tokens": 40,
                        "screenshot_path": "reports/evidence/c1/s2/screenshot.png",
                    },
                ],
            }
        ]
    }
    agentops_mod._scan_result_payload(payload, acc)
    assert acc["intent_steps"] == 2
    assert acc["binding_hit"]["cache"] == 1
    assert acc["heal_count"] == 1
    assert acc["vision_steps"] == 1
    assert acc["vision_tokens_sum"] == 40
    assert acc["evidence_steps"] == 1
    assert acc["fail_reason"]["timeout"] == 1


def test_empty_trace_shape():
    out = agentops_mod._empty_trace()
    assert out["reports_scanned"] == 0
    assert out["cache_hit_rate"] == 0.0


def test_aggregate_no_rows():
    db = MagicMock()
    db.execute.return_value.all.return_value = []
    out = agentops_mod.aggregate_from_reports(db, limit=10)
    assert out["reports_scanned"] == 0
    assert out["intent_steps"] == 0


def test_agentops_snapshot_has_tokens(monkeypatch):
    monkeypatch.setattr(
        "autopilot_platform.platform.services.observability.agentops.aggregate_from_reports",
        lambda *a, **k: agentops_mod._empty_trace(scanned=0),
    )
    monkeypatch.setattr(
        "autopilot_platform.platform.ai.ai_usage.usage_summary",
        lambda top_projects=5: {"total_tokens": 12, "calls": 1, "day": "2099-01-01"},
    )
    snap = agentops_mod.agentops_snapshot(MagicMock(), limit=5)
    assert "trace" in snap
    assert snap["tokens"]["total_tokens"] == 12
