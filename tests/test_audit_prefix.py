"""审计 action 前缀过滤。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from sqlalchemy.dialects import sqlite

from autopilot_platform.platform.ops import audit as audit_svc


def _compile_filter(q):
    return q.compile(dialect=sqlite.dialect(), compile_kwargs={"literal_binds": True})


def test_list_audits_prefix_uses_startswith():
    db = MagicMock()
    captured = {}

    def _paginate(_db, q, *, page, page_size):
        assert (page, page_size) == (1, 20)
        captured["sql"] = str(_compile_filter(q))
        return [], 0

    with patch(
        "autopilot_platform.platform.services.shared.pagination.paginate",
        _paginate,
    ):
        audit_svc.list_audits(db, action="acl.", page=1, page_size=20)
    assert "audit_logs.action LIKE 'acl.' || '%'" in captured["sql"]


def test_list_audits_exact_match():
    db = MagicMock()
    captured = {}

    def _paginate(_db, q, *, page, page_size):
        assert (page, page_size) == (1, 20)
        captured["sql"] = str(_compile_filter(q))
        return [], 0

    with patch(
        "autopilot_platform.platform.services.shared.pagination.paginate",
        _paginate,
    ):
        audit_svc.list_audits(db, action="acl.grant", page=1, page_size=20)
    assert "audit_logs.action = 'acl.grant'" in captured["sql"]
