"""设计域活动格式化。"""

from __future__ import annotations

from datetime import datetime, timezone

from autopilot_platform.platform.core.models import AuditLogRow
from autopilot_platform.platform.services.design.activity import (
    action_label,
    format_design_activity,
)


def test_format_logical_case_update():
    row = AuditLogRow(
        id="a1",
        action="design.logical_case.update",
        actor="admin",
        resource_type="logical_case",
        resource_id="lc-abc123456789",
        detail="",
        created_at=datetime(2026, 7, 30, 9, 28, 59, tzinfo=timezone.utc),
    )
    out = format_design_activity(row)
    assert out["label"] == "更新意图用例"
    assert "用例" in out["summary"]
    assert out["message"] == out["summary"]
    assert out["category"] == "edit"
    assert out["time_display"]


def test_format_generate_count():
    row = AuditLogRow(
        id="a2",
        action="design.logical_case.generate",
        actor="admin",
        resource_type="project",
        resource_id="p1",
        detail="count=3",
        created_at=datetime.now(timezone.utc),
    )
    out = format_design_activity(row)
    assert out["label"] == "AI 生成用例"
    assert out["summary"] == "生成 3 条用例"


def test_format_enqueue_job():
    row = AuditLogRow(
        id="a3",
        action="design.logical_case.enqueue_job",
        actor="admin",
        resource_type="job",
        resource_id="job-1",
        detail="project=e2e-beeaa9e9 artifact=5849dd3f3df340f999a4d9df972ed286",
        created_at=datetime.now(timezone.utc),
    )
    out = format_design_activity(row)
    assert out["label"] == "提交远程批跑"
    assert "项目 e2e-beeaa9e9" in out["summary"]
    assert out["category"] == "run"


def test_action_label_fallback():
    assert action_label("design.logical_case.create") == "创建意图用例"
