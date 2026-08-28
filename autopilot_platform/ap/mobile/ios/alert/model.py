"""iOS 系统弹框数据模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

AlertKind = Literal["system", "in_app", "unknown"]
AlertAction = Literal["accept", "dismiss", "click", "ignore", "fail", "none"]
AlertPolicy = Literal["auto", "accept", "dismiss", "ignore", "strict"]


@dataclass
class AlertInfo:
    exists: bool
    text: str = ""
    buttons: list[str] = field(default_factory=list)
    backend: str = ""
    alert_kind: AlertKind = "unknown"


@dataclass
class AlertDecision:
    action: AlertAction
    button: str = ""
    reason: str = ""


@dataclass
class AlertResult:
    exists: bool
    handled: bool
    action: str = ""
    text: str = ""
    backend: str = ""
    reason: str = ""
    recorded: bool = False
