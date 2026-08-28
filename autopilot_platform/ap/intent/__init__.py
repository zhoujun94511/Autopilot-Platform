"""Intent + Binding：意图可执行语义与工程内绑定缓存。

``from autopilot.intent import keyword`` / 加载 keywords 包时，不得顺带初始化 IntentRuntime。
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

from .bindings import (
    binding_path,
    load_binding,
    save_binding,
    upsert_step_binding,
)
from .manual_bind import apply_manual_binding
from .normalize import logical_texts_to_intent_steps, normalize_intent_steps
from .review import collect_failed_intents, failed_intent_steps_from_result

if TYPE_CHECKING:
    from .runtime import IntentRuntime as IntentRuntime
    from .runtime import run_intent_act as run_intent_act

__all__ = [
    "binding_path",
    "load_binding",
    "save_binding",
    "upsert_step_binding",
    "apply_manual_binding",
    "logical_texts_to_intent_steps",
    "normalize_intent_steps",
    "collect_failed_intents",
    "failed_intent_steps_from_result",
    "IntentRuntime",
    "run_intent_act",
]

_RUNTIME_EXPORTS = frozenset({"IntentRuntime", "run_intent_act"})


def __getattr__(name: str) -> Any:
    if name in _RUNTIME_EXPORTS:
        mod = import_module(f"{__name__}.runtime")
        val = getattr(mod, name)
        globals()[name] = val
        return val
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
