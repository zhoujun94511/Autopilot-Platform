"""解析被测 App Bundle ID（会话/变量级，非 WDA session caps）。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ....keywords.context import ExecutionContext


def resolve_target_bundle_id(ctx: "ExecutionContext") -> str:
    """与 Android mobile_monkey 对齐：从 ctx/会话解析，不要求步骤参数。"""
    for key in ("app_package", "packageName", "package", "__app_package__"):
        val = str(ctx.get_var(key) or "").strip()
        if val:
            return val

    from ....keywords.mobile.driver import get_manager
    from ..app_lifecycle import current_bundle_id

    mgr = get_manager(ctx)
    drv = mgr.optional_driver()
    if drv is None:
        return ""
    backend = mgr.backend or str(ctx.get_var("__mobile_backend_mode__") or "")
    bid = current_bundle_id(drv, backend)
    if bid:
        return bid
    # noinspection PyBroadException
    try:
        return str(getattr(drv, "current_package", "") or "").strip()
    except Exception:
        return ""
