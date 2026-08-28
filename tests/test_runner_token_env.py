"""独立 Runner --token / --token-env 解析（不启动执行循环）。"""

from __future__ import annotations

import pytest

from autopilot_platform.core.constants import DEFAULT_API_TOKEN
from autopilot_platform.runner.__main__ import resolve_runner_token


def test_resolve_runner_token_prefers_cli(monkeypatch):
    monkeypatch.setenv("MC_RUNNER_TOKEN", "from-env")
    assert resolve_runner_token(token="cli-token", token_env="MC_RUNNER_TOKEN") == "cli-token"


def test_resolve_runner_token_reads_named_env(monkeypatch):
    monkeypatch.setenv("MC_RUNNER_TOKEN", "from-env")
    assert resolve_runner_token(token=None, token_env="MC_RUNNER_TOKEN") == "from-env"


def test_resolve_runner_token_default_env_falls_back(monkeypatch):
    monkeypatch.delenv("MC_API_TOKEN", raising=False)
    assert resolve_runner_token(token=None, token_env="MC_API_TOKEN") == DEFAULT_API_TOKEN


def test_resolve_runner_token_missing_custom_env(monkeypatch):
    monkeypatch.delenv("MC_MISSING", raising=False)
    with pytest.raises(SystemExit):
        resolve_runner_token(token=None, token_env="MC_MISSING")
