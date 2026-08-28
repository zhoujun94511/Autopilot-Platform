"""iOS 自动化组件层（WDA-direct / Appium iOS 共用）。

关键字层（session/element）通过本包调用，避免在关键字里散落 backend 分支。
"""

from .runtime import driver_backend, is_ios_driver, is_wda_backend
from .app_lifecycle import (
    activate_app,
    current_bundle_id,
    is_app_installed,
    launch_app,
    reset_app,
    terminate_app,
)
from .context_switch import list_contexts, switch_context
from .scroll import scroll_to_element
from .swipe import wda_swipe_by_ratio
from .keys import press_delete_keys, press_physical_key
from .picker import ios_combo_select
from .attributes import read_element_attribute, ios_attr_candidates
from .device_info import lookup_ios_device_info, wda_status_to_device_info
from .gesture import tap_at, long_press_at, swipe_element, swipe_between_points, swipe_element_horizontal
from .webview import get_current_url, js_click_element
from .health import ensure_wda_session, wda_http_alive, wda_port_alive
from .alert import (
    IOSAlertHandler,
    maybe_handle_ios_alert,
    try_ios_alert_click,
    ios_alert_after_session,
)
from .monkey import run_ios_monkey, resolve_target_bundle_id

__all__ = [
    "driver_backend",
    "is_ios_driver",
    "is_wda_backend",
    "current_bundle_id",
    "terminate_app",
    "activate_app",
    "launch_app",
    "reset_app",
    "is_app_installed",
    "list_contexts",
    "switch_context",
    "scroll_to_element",
    "wda_swipe_by_ratio",
    "press_physical_key",
    "press_delete_keys",
    "ios_combo_select",
    "read_element_attribute",
    "ios_attr_candidates",
    "lookup_ios_device_info",
    "wda_status_to_device_info",
    "tap_at",
    "long_press_at",
    "swipe_element",
    "swipe_between_points",
    "swipe_element_horizontal",
    "get_current_url",
    "js_click_element",
    "ensure_wda_session",
    "wda_http_alive",
    "wda_port_alive",
    "IOSAlertHandler",
    "maybe_handle_ios_alert",
    "try_ios_alert_click",
    "ios_alert_after_session",
    "run_ios_monkey",
    "resolve_target_bundle_id",
]
