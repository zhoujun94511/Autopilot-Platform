"""iOS 系统弹框处理（WDA / Appium 双适配器）。"""

from .handler import (
    IOSAlertHandler,
    ios_alert_after_session,
    maybe_handle_ios_alert,
    try_ios_alert_click,
)
from .model import AlertDecision, AlertInfo, AlertResult
from .policy import decide
from .rules import ACCEPT_BUTTONS, DISMISS_BUTTONS, IOS_ALERT_RULES, match_rule, pick_button

__all__ = [
    "IOSAlertHandler",
    "AlertDecision",
    "AlertInfo",
    "AlertResult",
    "ACCEPT_BUTTONS",
    "DISMISS_BUTTONS",
    "IOS_ALERT_RULES",
    "decide",
    "match_rule",
    "pick_button",
    "ios_alert_after_session",
    "maybe_handle_ios_alert",
    "try_ios_alert_click",
]
