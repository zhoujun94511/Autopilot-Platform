"""AI / LLM 客户端与生成、需求分析。

子模块按需加载：``import platform.ai`` 或 ``from platform.ai import ai_usage``
不得顺带初始化 ``ai_client`` / 生成器等重栈。
"""
from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from . import ai_case_generator as ai_case_generator
    from . import ai_client as ai_client
    from . import ai_config as ai_config
    from . import ai_requirements_analyze as ai_requirements_analyze
    from . import ai_usage as ai_usage

__all__ = [
    "ai_client",
    "ai_config",
    "ai_case_generator",
    "ai_requirements_analyze",
    "ai_usage",
]


def __getattr__(name: str) -> Any:
    if name in __all__:
        return import_module(f"{__name__}.{name}")
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
