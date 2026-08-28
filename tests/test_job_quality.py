"""Job 质量聚合。"""

from __future__ import annotations

from collections import Counter
from datetime import timedelta
from unittest.mock import MagicMock

from autopilot_platform.platform.core.models import JobRow, utcnow
from autopilot_platform.platform.services.observability import job_quality as jq


def test_scan_all_fail_reasons_includes_non_intent():
    counter: Counter[str] = Counter()
    payload = {
        "cases": [
            {
                "steps": [
                    {"fail_reason": "element_not_found", "status": "failed"},
                    {"status": "failed"},
                    {"status": "passed"},
                ]
            }
        ]
    }
    n = jq._scan_all_fail_reasons(payload, counter)
    assert n == 2
    assert counter["element_not_found"] == 1
    assert counter["(step_failed)"] == 1


def test_scan_attributions():
    counter: Counter[str] = Counter()
    payload = {
        "cases": [
            {
                "steps": [
                    {"status": "FAIL", "fail_class": "locator", "fail_reason": "no_candidate"},
                    {"status": "FAIL", "attribution": "product_bug"},
                    {"status": "passed", "attribution": "env_issue"},
                ],
            }
        ]
    }
    jq.scan_attributions(payload, counter)
    assert counter["inner_agent_bug"] == 1
    assert counter["product_bug"] == 1
    assert "env_issue" not in counter


def test_scan_attributions_dedup_same_root_cause():
    counter: Counter[str] = Counter()
    payload = {
        "cases": [
            {
                "steps": [
                    {
                        "status": "FAIL",
                        "attribution": "product_bug",
                        "fail_class": "locator",
                        "fail_reason": "element_not_found",
                    },
                    {
                        "status": "FAIL",
                        "attribution": "product_bug",
                        "fail_class": "locator",
                        "fail_reason": "element_not_found",
                    },
                ],
            }
        ]
    }
    jq.scan_attributions(payload, counter)
    assert counter["product_bug"] == 1


def test_scan_fail_classes():
    counter: Counter[str] = Counter()
    payload = {
        "cases": [
            {
                "fail_class": "assertion",
                "steps": [
                    {"status": "FAIL", "fail_class": "timeout"},
                    {"status": "failed", "fail_class": "locator"},
                    {"status": "passed", "fail_class": "assertion"},
                ],
            }
        ]
    }
    jq.scan_fail_classes(payload, counter)
    assert counter["timeout"] == 1
    assert counter["locator"] == 1
    assert "assertion" not in counter


def test_job_quality_trend_from_jobs(monkeypatch, tmp_path):
    now = utcnow()
    jobs = [
        JobRow(
            id="j1",
            status="succeeded",
            project_id="p1",
            updated_at=now - timedelta(days=1),
            created_at=now - timedelta(days=1),
        ),
        JobRow(
            id="j2",
            status="failed",
            project_id="p1",
            error="KeywordError: boom",
            updated_at=now - timedelta(days=1),
            created_at=now - timedelta(days=1),
        ),
        JobRow(
            id="j3",
            status="failed",
            project_id="p1",
            error="Timeout waiting",
            updated_at=now,
            created_at=now,
        ),
    ]
    db = MagicMock()
    db.scalars.return_value.all.return_value = jobs
    db.execute.return_value.all.return_value = []

    out = jq.job_quality_snapshot(db, project_id="p1", days=3, report_limit=10)
    assert out["jobs_scanned"] == 3
    assert out["failed_jobs"] == 2
    assert out["fail_rate"] > 0
    assert "KeywordError" in str(out["error_prefix_top"]) or out["error_prefix_top"]
    assert len(out["trend"]) == 3
