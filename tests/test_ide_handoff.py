"""IDE 打开管理台：一次性交接码，不把 JWT 放进 URL。"""

from __future__ import annotations

from autopilot_platform.platform.identity import ide_handoff as h


def test_issue_consume_once():
    h.reset_for_tests()
    code, ttl = h.issue("user-1")
    assert ttl == h.handoff_ttl_sec()
    assert ttl >= 120
    assert len(code) >= 16
    assert h.consume(code) == "user-1"
    assert h.consume(code) is None


def test_latest_code_wins():
    h.reset_for_tests()
    old, _ = h.issue("user-1")
    new, _ = h.issue("user-1")
    assert h.consume(old) is None
    assert h.consume(new) == "user-1"
