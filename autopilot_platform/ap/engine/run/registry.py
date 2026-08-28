"""运行策略注册表（可插拔：sequential / parallel_device / 后续扩展）。"""

from __future__ import annotations

from typing import Callable, Dict

from .config import RunConfig
from ..suite import SuiteResult
from ...model.testcase import TestCase

RunStrategyFn = Callable[[list[TestCase], RunConfig], SuiteResult]

_REGISTRY: Dict[str, RunStrategyFn] = {}


def register(mode: str, fn: RunStrategyFn) -> None:
    _REGISTRY[mode] = fn


def get(mode: str) -> RunStrategyFn:
    if mode not in _REGISTRY:
        raise KeyError(f"未知运行策略：{mode!r}（已注册：{list(_REGISTRY)}）")
    return _REGISTRY[mode]
