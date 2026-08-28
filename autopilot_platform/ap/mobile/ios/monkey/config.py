"""从关键字参数 / settings 构建 MonkeyConfig。"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING, Any

from ....runtime import settings as app_settings
from .policy import (
    MonkeyConfig,
    apply_preset,
    clamp_duration,
    clamp_steps,
)

if TYPE_CHECKING:
    from ....keywords.context import ExecutionContext


def _int_kw(kwargs: dict[str, Any], *keys: str, default: int = 0) -> int:
    for key in keys:
        raw = kwargs.get(key)
        if raw not in (None, ""):
            try:
                return int(float(str(raw).strip()))
            except (TypeError, ValueError):
                pass
    return default


def build_monkey_config(
    _ctx: "ExecutionContext",
    bundle_id: str,
    steps: int,
    **kwargs: Any,
) -> MonkeyConfig:
    duration_sec = clamp_duration(_int_kw(kwargs, "durationSec", "duration", "duration_sec"))
    # 事件数始终参与：纯步数模式为上限；按时长模式为安全帽（防失控长跑）
    max_events = clamp_steps(steps)

    seed_raw = kwargs.get("seed")
    if str(seed_raw or "").strip().isdigit():
        seed = int(str(seed_raw).strip())
    else:
        seed = random.randint(1, 999_999)

    throttle = _int_kw(kwargs, "throttleMs", "throttle_ms")
    if throttle <= 0:
        throttle = app_settings.ios_monkey_throttle_ms()

    jitter = _int_kw(kwargs, "throttleJitterMs", "throttle_jitter_ms")
    if jitter <= 0 and kwargs.get("throttleJitterMs") in (None, ""):
        jitter = app_settings.ios_monkey_throttle_jitter_ms()

    source_interval = _int_kw(kwargs, "sourceInterval", "source_interval")
    if source_interval <= 0:
        source_interval = app_settings.ios_monkey_source_interval()

    preset = str(
        kwargs.get("monkeyPolicy") or kwargs.get("policy") or app_settings.ios_monkey_policy()
    ).strip().lower()

    cfg = MonkeyConfig(
        bundle_id=bundle_id,
        max_events=max_events,
        duration_sec=duration_sec,
        throttle_ms=max(0, throttle),
        throttle_jitter_ms=max(0, jitter),
        source_interval=max(1, source_interval),
        seed=seed,
        wda_watchdog_interval=max(3, _int_kw(kwargs, "wdaWatchdogInterval") or 10),
    )
    apply_preset(cfg, preset)
    return cfg
