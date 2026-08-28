"""按 RBAC 契约裁剪 API 响应（docs/rbac-capability-matrix.md §6）。"""

from __future__ import annotations

from typing import Any

from ..auth import AuthContext
from .projects import is_platform_admin


def can_view_ops_budget(auth: AuthContext | None) -> bool:
    if auth is None or auth.kind != "user":
        return False
    return is_platform_admin(auth)


def strip_usage_tokens(tokens: dict[str, Any] | None) -> None:
    """原地移除预算/全局用量字段（保留项目 trace 时勿调用）。"""
    if not isinstance(tokens, dict):
        return
    for key in (
        "daily_budget",
        "budget_remaining",
        "top_projects",
        "prompt_tokens",
        "completion_tokens",
        "cached_tokens",
        "cache_miss_tokens",
        "cache_write_tokens",
        "cache_hit_rate",
        "total_tokens",
        "calls",
        "day",
    ):
        tokens.pop(key, None)


def sanitize_design_stats(stats: dict[str, Any], auth: AuthContext | None) -> dict[str, Any]:
    if can_view_ops_budget(auth):
        return stats
    out = dict(stats)
    out.pop("tokens", None)
    return out


def sanitize_agentops_snapshot(snap: dict[str, Any], auth: AuthContext | None) -> dict[str, Any]:
    if can_view_ops_budget(auth):
        return snap
    out = dict(snap)
    out.pop("tokens", None)
    return out
