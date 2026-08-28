"""口令策略。"""

from __future__ import annotations

import pytest

from autopilot_platform.platform.core.security import validate_password_policy


@pytest.mark.parametrize(
    "pwd",
    ["short1", "allletters", "12345678", "Admin", ""],
)
def test_password_policy_rejects(pwd: str):
    with pytest.raises(ValueError):
        validate_password_policy(pwd)


def test_password_policy_accepts():
    validate_password_policy("Admin123")
    validate_password_policy("Secret12")
