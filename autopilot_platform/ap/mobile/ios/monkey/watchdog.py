"""WDA / Appium 探活与恢复（Monkey 长跑 watchdog）。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ....keywords.context import ExecutionContext


def ensure_wda_stack(ctx: "ExecutionContext", bundle_id: str) -> bool:
    """WDA HTTP 探活 → session 恢复 → 必要时重跑 IosDevicePrep。"""
    from ....keywords.mobile.driver import get_manager
    from ... import ios_bootstrap as ib
    from ..health import ensure_wda_session, wda_port_alive

    mgr = get_manager(ctx)
    if mgr.backend != "wda":
        return True

    port = int(getattr(mgr, "_wda_port", 0) or ib.DEFAULT_WDA_PORT)
    if wda_port_alive(port):
        drv = mgr.optional_driver()
        if drv is not None:
            client = getattr(drv, "wda_client", None) or getattr(drv, "_c", None)
            if client is not None:
                # noinspection PyBroadException
                try:
                    ensure_wda_session(client, bundle_id=bundle_id)
                    return True
                except Exception:
                    pass

    ctx.log(f"Monkey：WDA 端口 {port} 不可达或 session 失效，尝试重启 WDA 栈…")
    prep = getattr(mgr, "_ios_prep", None)
    if prep is not None:
        # noinspection PyBroadException
        try:
            prep.prepare()
            drv = mgr.optional_driver()
            client = getattr(drv, "wda_client", None) or getattr(drv, "_c", None) if drv else None
            if client is not None:
                ensure_wda_session(client, bundle_id=bundle_id)
                if bundle_id:
                    # noinspection PyBroadException
                    try:
                        client.launch_app(bundle_id)
                    except Exception:
                        client.activate_app(bundle_id)
                ctx.log("Monkey：WDA 栈已恢复")
                return wda_port_alive(port)
        except Exception as exc:
            ctx.log(f"Monkey：WDA 栈恢复失败: {exc}")
            return False
    return wda_port_alive(port)


def ensure_monkey_stack(ctx: "ExecutionContext", bundle_id: str) -> bool:
    """按 backend 探活：WDA-direct → ensure_wda_stack；Appium → 会话探测/重建。"""
    from ....keywords.mobile.driver import get_manager, ios_session_probe
    from ....keywords.mobile.platform import host_os, select_backend

    mgr = get_manager(ctx)
    mode = str(
        ctx.get_var("__mobile_backend_mode__")
        or ctx.get_var("__ios_backend_mode__")
        or "auto"
    )
    backend = (mgr.backend or "").lower() or select_backend(
        "ios", host=host_os(), mode=mode,
    )
    if backend == "wda":
        return ensure_wda_stack(ctx, bundle_id)
    if backend == "appium":
        if ios_session_probe(mgr):
            return True
        ctx.log("Monkey：Appium 会话失效，尝试按 Monkey caps 重建…")
        from .session_prep import prepare_monkey_appium_session
        # noinspection PyBroadException
        try:
            prepare_monkey_appium_session(ctx, bundle_id)
        except Exception:
            return False
        return ios_session_probe(mgr)
    return True
