"""iOS Monkey 配置与随机策略。"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

DEFAULT_WEIGHTS: dict[str, int] = {
    "tap_random_element": 40,
    "tap_random_point": 20,
    "swipe_random": 25,
    "long_press_random": 5,
    "handle_alert": 3,
    "app_recover": 2,
}

PRESET_WEIGHTS: dict[str, dict[str, int]] = {
    "safe": {
        "tap_random_element": 50,
        "tap_random_point": 10,
        "swipe_random": 30,
        "long_press_random": 3,
        "handle_alert": 4,
        "app_recover": 3,
    },
    "balanced": dict(DEFAULT_WEIGHTS),
    "aggressive": {
        "tap_random_element": 30,
        "tap_random_point": 30,
        "swipe_random": 20,
        "long_press_random": 10,
        "handle_alert": 2,
        "app_recover": 1,
    },
}

SWIPE_DIRECTIONS = ("UP", "DOWN", "LEFT", "RIGHT")

BLACKLIST_TEXTS: tuple[str, ...] = (
    "删除", "移除", "清空", "注销", "退出登录", "删除账号",
    "支付", "购买", "订阅", "确认购买",
    "Delete", "Remove", "Clear", "Logout", "Sign Out",
    "Delete Account", "Purchase", "Subscribe",
)


@dataclass
class MonkeyBounds:
    top_margin: int = 80
    bottom_margin: int = 80
    left_margin: int = 5
    right_margin: int = 5


@dataclass
class MonkeyConfig:
    bundle_id: str
    max_events: int = 20
    duration_sec: int = 0
    throttle_ms: int = 500
    throttle_jitter_ms: int = 200
    source_interval: int = 5
    seed: int | None = None
    alert_check_interval: int = 5
    foreground_check_interval: int = 5
    wda_watchdog_interval: int = 10
    stuck_same_state_limit: int = 8
    allow_dangerous: bool = False
    policy_preset: str = "balanced"
    bounds: MonkeyBounds = field(default_factory=MonkeyBounds)
    weights: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))


def clamp_steps(steps: int) -> int:
    return max(20, min(200, int(steps)))


def clamp_duration(sec: int) -> int:
    """0 表示仅按事件数；否则 1~21600 秒（6 小时）。"""
    sec = int(sec)
    if sec <= 0:
        return 0
    return max(1, min(21_600, sec))


def apply_preset(cfg: MonkeyConfig, preset: str) -> None:
    name = (preset or "balanced").strip().lower()
    if name not in PRESET_WEIGHTS:
        name = "balanced"
    cfg.policy_preset = name
    cfg.weights = dict(PRESET_WEIGHTS[name])
    cfg.allow_dangerous = name == "aggressive"


def choose_action(rng: random.Random, weights: dict[str, int]) -> str:
    actions = [a for a in weights if int(weights.get(a, 0)) > 0]
    vals = [max(0, int(weights.get(a, 0))) for a in actions]
    if not actions or not any(vals):
        return "tap_random_point"
    return rng.choices(actions, weights=vals, k=1)[0]


def throttle_sleep_ms(cfg: MonkeyConfig, rng: random.Random) -> int:
    base = max(0, cfg.throttle_ms)
    jitter = max(0, cfg.throttle_jitter_ms)
    if jitter <= 0:
        return base
    lo = max(0, base - jitter)
    hi = base + jitter
    return rng.randint(lo, hi)


def random_point(rng: random.Random, width: int, height: int,
                 bounds: MonkeyBounds) -> tuple[int, int]:
    x = rng.randint(bounds.left_margin, max(bounds.left_margin, width - bounds.right_margin))
    y = rng.randint(bounds.top_margin, max(bounds.top_margin, height - bounds.bottom_margin))
    return x, y


def random_direction(rng: random.Random) -> str:
    return rng.choice(SWIPE_DIRECTIONS)


def is_blacklisted(text: str, *, allow_dangerous: bool) -> bool:
    if allow_dangerous:
        return False
    hay = (text or "").strip().lower()
    if not hay:
        return False
    for needle in BLACKLIST_TEXTS:
        if needle.lower() in hay:
            return True
    return False


def should_refresh_source(
    index: int,
    action: str,
    *,
    interval: int,
    last_index: int,
    force: bool = False,
) -> bool:
    if force:
        return True
    if action == "tap_random_element":
        return True
    if last_index <= 0:
        return True
    return (index - last_index) >= max(1, interval)
