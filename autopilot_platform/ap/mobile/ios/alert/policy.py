"""iOS 弹框处理策略决策。"""

from __future__ import annotations

from .model import AlertAction, AlertDecision, AlertInfo, AlertPolicy
from .rules import (
    match_rule,
    pick_accept_button,
    pick_button,
    pick_dismiss_button,
)

_VALID_ACTIONS: frozenset[str] = frozenset(
    {"accept", "dismiss", "click", "ignore", "fail", "none"}
)


def _coerce_action(raw: str) -> AlertAction:
    action = (raw or "accept").strip().lower()
    if action in _VALID_ACTIONS:
        return action  # type: ignore[return-value]
    return "accept"


def decide(info: AlertInfo, policy: AlertPolicy | str) -> AlertDecision:
    pol = (policy or "auto").strip().lower()
    if pol == "ignore":
        return AlertDecision("ignore", reason="policy=ignore")
    if pol == "accept":
        btn = pick_accept_button(info.buttons)
        return AlertDecision("accept", button=btn, reason="policy=accept")
    if pol == "dismiss":
        btn = pick_dismiss_button(info.buttons)
        return AlertDecision("dismiss", button=btn, reason="policy=dismiss")
    if pol == "strict":
        rule = match_rule(info.text)
        if rule is None:
            return AlertDecision("fail", reason="strict: unknown alert")
        btn = pick_button(info.buttons, tuple(rule.get("button_priority", ())))
        action = _coerce_action(str(rule.get("action", "accept")))
        return AlertDecision(action, button=btn, reason=f"strict:{rule.get('id', '')}")

    # auto
    rule = match_rule(info.text)
    if rule is not None:
        btn = pick_button(info.buttons, tuple(rule.get("button_priority", ())))
        action = _coerce_action(str(rule.get("action", "accept")))
        return AlertDecision(action, button=btn, reason=f"rule:{rule.get('id', '')}")
    btn = pick_accept_button(info.buttons)
    if btn:
        return AlertDecision("accept", button=btn, reason="auto:default_accept")
    return AlertDecision("fail", reason="auto: no matching button")
