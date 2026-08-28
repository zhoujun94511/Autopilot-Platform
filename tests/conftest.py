"""Pytest 共享 fixtures / 辅助。"""

from __future__ import annotations

import os

import pytest

from list_page_helpers import page_items, page_total


def pytest_configure(config: pytest.Config) -> None:
    _ = config
    # 历史用例大量用 DEFAULT_API_TOKEN 当运维通道；生产代码默认已关闭该升权。
    # 单测显式打开迁移旗标，新增安全回归用例应 monkeypatch 关掉并自行断言。
    os.environ.setdefault("MC_ALLOW_LEGACY_TOKEN_ADMIN", "1")
    os.environ.setdefault("MC_HOST", "127.0.0.1")
    # 联调进程会设 MC_FRONTEND_DEV_URL；单测默认走 dist/API，避免根路径变成 307。
    os.environ.pop("MC_FRONTEND_DEV_URL", None)


@pytest.fixture()
def list_page_items():
    return page_items


@pytest.fixture()
def list_page_total():
    return page_total
