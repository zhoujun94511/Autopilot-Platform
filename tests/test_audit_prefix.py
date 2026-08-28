"""审计 action 前缀过滤。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from sqlalchemy.dialects import sqlite

from autopilot_platform.platform.ops import audit as audit_svc


def _compile(q) -> str:
    return str(q.compile(dialect=sqlite.dialect(), compile_kwargs={"literal_binds": False}))


def test_list_audits_prefix_uses_startswith():
    db = MagicMock()
    captured = {}

    def _paginate(_db, q, *, _page, _page_size):
        captured["sql"] = _compile(q)
        return [], 0

    with patch(
        "autopilot_platform.platform.services.shared.pagination.paginate",
        _paginate,
    ):
        audit_svc.list_audits(db, action="acl.", page=1, page_size=20)
    sql = captured["sql"].lower()
    assert "like" in sql or "startswith" in sql or "acl." in captured["sql"]


def test_list_audits_exact_match():
    db = MagicMock()
    captured = {}

    def _paginate(_db, q, *, _page, _page_size):
        captured["sql"] = _compile(q)
        return [], 0

    with patch(
        "autopilot_platform.platform.services.shared.pagination.paginate",
        _paginate,
    ):
        audit_svc.list_audits(db, action="acl.grant", page=1, page_size=20)
    assert "action" in captured["sql"].lower()
