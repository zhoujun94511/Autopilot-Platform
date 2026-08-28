"""可选视觉解析钩子（契约预留 resolver=vision）。

默认关闭（``AUTOPILOT_INTENT_VISION=0``）。
开启后加载 ``autopilot.intent.vision_plugin``（截图 + 多模态 API）。
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from .config import intent_vision_enabled, vision_max_calls_per_case

log = logging.getLogger(__name__)

_budget_lock = threading.Lock()
_case_calls = 0
_budget_warned = False


def vision_enabled() -> bool:
    return intent_vision_enabled()


def reset_vision_call_budget() -> None:
    """用例开始时清零：vision 按步触发，需要每用例硬顶避免一个用例刷爆额度。"""
    global _case_calls, _budget_warned
    with _budget_lock:
        _case_calls = 0
        _budget_warned = False


def vision_calls_used() -> int:
    with _budget_lock:
        return _case_calls


def _take_vision_call() -> bool:
    """占用一次调用额度；超顶返回 False（仅首次告警）。"""
    global _case_calls, _budget_warned
    cap = vision_max_calls_per_case()
    with _budget_lock:
        if 0 < cap <= _case_calls:
            if not _budget_warned:
                _budget_warned = True
                log.warning(
                    "vision 调用达每用例上限 %s（AUTOPILOT_VISION_MAX_CALLS_PER_CASE），"
                    "本用例后续步骤仅用启发式候选",
                    cap,
                )
            return False
        _case_calls += 1
        return True


def vision_candidates(
    *,
    action: str,
    target: str,
    value: str,
    platform: str,
    ctx: Any = None,
    enhanced: bool | None = None,
) -> list[dict[str, Any]]:
    if not vision_enabled():
        return []
    if not _take_vision_call():
        return []
    try:
        from . import vision_plugin  # type: ignore
    except ImportError:
        log.debug("vision enabled but vision_plugin not installed")
        return []
    propose = getattr(vision_plugin, "propose_candidates", None)
    if not callable(propose):
        return []
    try:
        rows = propose(
            action=action,
            target=target,
            value=value,
            platform=platform,
            ctx=ctx,
            enhanced=enhanced,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("vision_plugin failed: %s", exc)
        return []
    out: list[dict[str, Any]] = []
    for c in rows or []:
        if not isinstance(c, dict) or not c.get("keyword_id"):
            continue
        item = dict(c)
        item.setdefault("resolver", "vision")
        item.setdefault("score", 0.4)
        out.append(item)
    return out
