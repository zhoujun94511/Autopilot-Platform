"""RBAC API 响应裁剪 — 对齐 docs/rbac-capability-matrix.md §6。"""

from __future__ import annotations

from autopilot_platform.platform.auth import AuthContext
from autopilot_platform.platform.tenancy.rbac_response import (
    can_view_ops_budget,
    sanitize_agentops_snapshot,
    sanitize_design_stats,
)


def test_can_view_ops_budget_platform_admin_only():
    assert can_view_ops_budget(AuthContext(kind="user", role="admin", user_id="a"))
    assert not can_view_ops_budget(AuthContext(kind="user", role="operator", user_id="o"))
    assert not can_view_ops_budget(AuthContext(kind="runner", runner_id="r1"))


def test_sanitize_design_stats_strips_tokens_for_operator():
    raw = {"requirements": 3, "tokens": {"daily_budget": 999, "total_tokens": 10}}
    out = sanitize_design_stats(
        raw, AuthContext(kind="user", role="operator", user_id="u")
    )
    assert out["requirements"] == 3
    assert "tokens" not in out


def test_sanitize_design_stats_keeps_tokens_for_admin():
    raw = {"requirements": 3, "tokens": {"daily_budget": 999}}
    out = sanitize_design_stats(raw, AuthContext(kind="user", role="admin", user_id="a"))
    assert out["tokens"]["daily_budget"] == 999


def test_sanitize_agentops_strips_tokens_for_operator():
    raw = {"trace": {"intent_steps": 1}, "tokens": {"total_tokens": 5}}
    out = sanitize_agentops_snapshot(
        raw, AuthContext(kind="user", role="operator", user_id="u")
    )
    assert out["trace"]["intent_steps"] == 1
    assert "tokens" not in out
