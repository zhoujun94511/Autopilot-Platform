"""Monkey 启动前 Appium 会话加固（与 driver / ios_bootstrap 联动，非孤岛补丁）。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ....keywords.context import ExecutionContext


def prepare_monkey_appium_session(ctx: "ExecutionContext", bundle_id: str) -> None:
    """Mac Appium 长跑：合入 newCommandTimeout=0 并刷新 driver（保留 go-ios WDA 准备）。"""
    from ....keywords.mobile.driver import get_manager
    from ....keywords.mobile.platform import host_os, select_backend
    from ....mobile import ios_bootstrap as ib

    mode = str(
        ctx.get_var("__mobile_backend_mode__")
        or ctx.get_var("__ios_backend_mode__")
        or "auto"
    )
    if select_backend("ios", host=host_os(), mode=mode) != "appium":
        return

    mgr = get_manager(ctx)
    udid = str(ctx.get_var("__device_udid__") or "")
    base: dict = {}
    existing = ctx.get_var("__appium_caps__")
    if isinstance(existing, dict):
        base["__appium_caps__"] = dict(existing)
    ib.merge_appium_ios_caps(
        base, udid, backend_mode="appium",
        extra={"appium:newCommandTimeout": 0},
    )
    merged = base.get("__appium_caps__")
    if isinstance(merged, dict):
        ctx.set_var("__appium_caps__", merged)
        mgr.extra_caps.update(merged)

    if mgr.optional_driver() is None:
        return

    ctx.log("Monkey：刷新 Appium 会话（appium:newCommandTimeout=0，防长跑空闲杀 session）")
    drv = mgr.optional_driver()
    if drv is not None:
        # noinspection PyBroadException
        try:
            drv.quit()
        except Exception:
            pass
        mgr.release_driver()
    # noinspection PyBroadException
    try:
        mgr.create("ios", bundle_id, "", udid)
    except Exception as exc:
        ctx.log(f"Monkey：Appium 会话刷新失败: {exc}")
        raise
