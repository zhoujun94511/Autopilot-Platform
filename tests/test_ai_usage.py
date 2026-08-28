"""AI usage 计量与日预算。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_extract_usage_sums():
    from autopilot_platform.platform.ai import ai_usage

    u = ai_usage.extract_usage(
        {"usage": {"prompt_tokens": 10, "completion_tokens": 5}}
    )
    assert u["total_tokens"] == 15
    assert u["cached_tokens"] == 0
    assert ai_usage.extract_usage({})["total_tokens"] == 0


def test_extract_usage_openai_cached():
    from autopilot_platform.platform.ai import ai_usage

    u = ai_usage.extract_usage(
        {
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "total_tokens": 120,
                "prompt_tokens_details": {"cached_tokens": 80},
            }
        }
    )
    assert u["cached_tokens"] == 80
    assert u["prompt_tokens"] == 100
    assert u["completion_tokens"] == 20


def test_extract_usage_deepseek_cache():
    from autopilot_platform.platform.ai import ai_usage

    u = ai_usage.extract_usage(
        {
            "usage": {
                "prompt_tokens": 50,
                "completion_tokens": 10,
                "prompt_cache_hit_tokens": 40,
                "prompt_cache_miss_tokens": 10,
            }
        }
    )
    assert u["cached_tokens"] == 40
    assert u["cache_miss_tokens"] == 10
    assert u["total_tokens"] == 60


def test_extract_usage_anthropic_aliases():
    from autopilot_platform.platform.ai import ai_usage

    u = ai_usage.extract_usage(
        {
            "usage": {
                "input_tokens": 30,
                "output_tokens": 7,
                "cache_read_input_tokens": 12,
                "cache_creation_input_tokens": 5,
            }
        }
    )
    assert u["prompt_tokens"] == 30
    assert u["completion_tokens"] == 7
    assert u["cached_tokens"] == 12
    assert u["cache_write_tokens"] == 5


def test_extract_usage_gemini_metadata():
    from autopilot_platform.platform.ai import ai_usage

    u = ai_usage.extract_usage(
        {
            "usageMetadata": {
                "promptTokenCount": 8,
                "candidatesTokenCount": 3,
                "totalTokenCount": 11,
                "cachedContentTokenCount": 4,
            }
        }
    )
    assert u["prompt_tokens"] == 8
    assert u["completion_tokens"] == 3
    assert u["cached_tokens"] == 4
    assert u["total_tokens"] == 11


def test_record_and_summary(tmp_path, monkeypatch):
    from autopilot_platform.platform.ai import ai_usage

    monkeypatch.setenv("MC_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    monkeypatch.delenv("AP_AI_DAILY_TOKEN_BUDGET", raising=False)
    ai_usage.reset_for_tests()

    ai_usage.record_usage(
        {
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "total_tokens": 120,
            "cached_tokens": 60,
            "cache_miss_tokens": 40,
        },
        source="chat",
        model="gpt-test",
        provider="openai",
    )
    summary = ai_usage.usage_summary()
    assert summary["total_tokens"] == 120
    assert summary["calls"] == 1
    assert summary["prompt_tokens"] == 100
    assert summary["cached_tokens"] == 60
    assert summary["cache_miss_tokens"] == 40
    assert summary["cache_hit_rate"] == 0.6
    path = Path(summary["jsonl"])
    assert path.is_file()
    row = json.loads(path.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert row["usage"]["total_tokens"] == 120
    assert row["usage"]["cached_tokens"] == 60


def test_enforce_budget(tmp_path, monkeypatch):
    from autopilot_platform.platform.ai import ai_usage

    monkeypatch.setenv("MC_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("AP_AI_DAILY_TOKEN_BUDGET", "50")
    monkeypatch.setenv("AP_AI_ENFORCE_TOKEN_BUDGET", "1")
    ai_usage.reset_for_tests()
    ai_usage.record_usage(
        {"prompt_tokens": 40, "completion_tokens": 20, "total_tokens": 60},
        source="chat",
        model="m",
        provider="openai",
    )
    with pytest.raises(RuntimeError, match="预算"):
        ai_usage.check_budget_before_call()


def test_project_budget_enforce(tmp_path, monkeypatch):
    from autopilot_platform.platform.ai import ai_usage

    monkeypatch.setenv("MC_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    monkeypatch.delenv("AP_AI_DAILY_TOKEN_BUDGET", raising=False)
    monkeypatch.setenv("AP_AI_PROJECT_DAILY_TOKEN_BUDGET", "100")
    monkeypatch.setenv("AP_AI_ENFORCE_TOKEN_BUDGET", "1")
    ai_usage.reset_for_tests()
    token = ai_usage.set_ai_billing_scope(project_id="p-a", org_id="o-1")
    try:
        ai_usage.record_usage(
            {"prompt_tokens": 80, "completion_tokens": 30, "total_tokens": 110},
            source="chat",
            model="m",
        )
        with pytest.raises(RuntimeError, match="项目"):
            ai_usage.check_budget_before_call()
        # 其他项目不受影响
        ai_usage.set_ai_billing_scope(project_id="p-b")
        ai_usage.check_budget_before_call()
    finally:
        ai_usage.reset_ai_billing_scope(token)
    summary = ai_usage.usage_summary(project_id="p-a")
    assert summary["project_total_tokens"] == 110
    assert any(r["project_id"] == "p-a" for r in summary["top_projects"])
