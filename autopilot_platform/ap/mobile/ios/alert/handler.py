"""iOS 系统弹框统一处理器。"""

from __future__ import annotations

import re
import time
from typing import TYPE_CHECKING, Any

from ..runtime import driver_backend, is_wda_backend
from ....runtime import settings as app_settings
from .appium_adapter import AppiumAlertAdapter
from .model import AlertInfo, AlertPolicy, AlertResult
from .policy import decide
from .recorder import AlertRecorder
from .rules import _decode_xml_entities
from .wda_adapter import WdaAlertAdapter, alert_button_labels

if TYPE_CHECKING:
    from ....keywords.context import ExecutionContext


def _ios_alert_enabled(ctx: "ExecutionContext") -> bool:
    ctx_val = ctx.get_var("__ios_alert_enabled__")
    if ctx_val is not None:
        return bool(ctx_val)
    return app_settings.ios_alert_enabled()


def _project_dir(ctx: "ExecutionContext") -> str:
    return str(ctx.get_var("__project_path__") or "")


def _resolve_policy(ctx: "ExecutionContext", override: str = "") -> AlertPolicy:
    if override:
        pol = str(override).strip().lower()
        if pol in ("auto", "accept", "dismiss", "ignore", "strict"):
            return pol  # type: ignore[return-value]
    ctx_pol = str(ctx.get_var("__ios_alert_policy__") or "").strip().lower()
    if ctx_pol in ("auto", "accept", "dismiss", "ignore", "strict"):
        return ctx_pol  # type: ignore[return-value]
    return app_settings.ios_alert_policy()  # type: ignore[return-value]


def _wda_client_from_driver(drv: Any) -> Any | None:
    client = getattr(drv, "wda_client", None)
    if client is not None:
        return client
    return getattr(drv, "_c", None)


def _resolve_adapter(ctx: "ExecutionContext") -> Any | None:
    from ....keywords.mobile.driver import get_manager

    mgr = get_manager(ctx)
    if mgr.platform != "ios":
        return None
    drv = mgr.optional_driver()
    if drv is None:
        return None
    backend = driver_backend(drv, mgr.backend or str(ctx.get_var("__mobile_backend_mode__") or ""))
    if is_wda_backend(backend, drv):
        client = _wda_client_from_driver(drv)
        return WdaAlertAdapter(client) if client is not None else None
    if backend == "appium":
        return AppiumAlertAdapter(drv)
    return None


class IOSAlertHandler:
    def __init__(self, ctx: "ExecutionContext", *, policy: str = ""):
        self.ctx = ctx
        self.policy = _resolve_policy(ctx, policy)
        self.recorder = AlertRecorder(_project_dir(ctx) or None)

    def peek(self) -> AlertInfo:
        adapter = _resolve_adapter(self.ctx)
        if adapter is None:
            return AlertInfo(exists=False)
        return adapter.get_alert()

    def maybe_handle(self, *, stage: str = "", policy: str = "") -> AlertResult:
        if not _ios_alert_enabled(self.ctx):
            return AlertResult(exists=False, handled=False, reason="disabled")

        adapter = _resolve_adapter(self.ctx)
        if adapter is None:
            return AlertResult(exists=False, handled=False, reason="no_ios_adapter")

        info = adapter.get_alert()
        if not info.exists:
            return AlertResult(exists=False, handled=False, backend=info.backend)

        pol = _resolve_policy(self.ctx, policy or self.policy)
        decision = decide(info, pol)
        if decision.action == "ignore":
            return AlertResult(
                exists=True, handled=False, action="ignore",
                text=info.text, backend=info.backend, reason=decision.reason,
            )

        recorded = False
        if decision.action == "fail":
            if app_settings.ios_alert_record_unknown():
                self.recorder.save(info, decision, adapter, stage=stage)
                recorded = True
            return AlertResult(
                exists=True, handled=False, action="fail",
                text=info.text, backend=info.backend, reason=decision.reason,
                recorded=recorded,
            )

        handled = self._execute(adapter, decision.action, decision.button)
        if not handled and app_settings.ios_alert_record_unknown():
            self.recorder.save(info, decision, adapter, stage=stage)
            recorded = True
        return AlertResult(
            exists=True,
            handled=handled,
            action=decision.action if handled else "none",
            text=info.text,
            backend=info.backend,
            reason=decision.reason,
            recorded=recorded,
        )

    @staticmethod
    def _execute(adapter: Any, action: str, button: str) -> bool:
        # noinspection PyBroadException
        try:
            if action == "accept":
                adapter.accept(button)
            elif action == "dismiss":
                adapter.dismiss(button)
            elif action == "click":
                adapter.accept(button)
            else:
                return False
            time.sleep(0.5)
            return not adapter.is_open()
        except Exception:
            return False

    def try_click_locator(
        self,
        locator: Any,
        timeout_ms: int,
        *,
        wait_for_alert: bool | None = None,
    ) -> bool:
        """按定位符点击系统 Alert 按钮（仅 WDA 主路径）。"""
        from ....keywords.mobile.driver import (
            extract_ios_button_label,
            ios_alert_locator_hint,
            locator_xpath_value,
        )

        adapter = _resolve_adapter(self.ctx)
        if adapter is None or not isinstance(adapter, WdaAlertAdapter):
            return False

        raw = locator_xpath_value(locator)
        label = _decode_xml_entities(extract_ios_button_label(locator))
        btn_idx = 1
        m = re.search(r"XCUIElementTypeButton\[(\d+)]", raw)
        if m:
            btn_idx = max(1, int(m.group(1)))

        if wait_for_alert is None:
            wait_for_alert = ios_alert_locator_hint(locator)

        deadline = time.monotonic() + max(0, timeout_ms) / 1000.0
        no_alert_since: float | None = None
        while time.monotonic() < deadline:
            if not adapter.is_open():
                if not wait_for_alert:
                    return False
                if no_alert_since is None:
                    no_alert_since = time.monotonic()
                elif time.monotonic() - no_alert_since >= 2.0:
                    return False
                time.sleep(0.3)
                continue
            no_alert_since = None

            candidates: list[str] = []
            if label:
                candidates.append(label)
            decoded = [_decode_xml_entities(lb) for lb in alert_button_labels(adapter.client)]
            if not label and decoded and btn_idx <= len(decoded):
                candidates.append(decoded[btn_idx - 1])
            for d in decoded:
                if d not in candidates:
                    candidates.append(d)
            for cand in candidates:
                if not cand:
                    continue
                # noinspection PyBroadException
                try:
                    adapter.accept(cand)
                    time.sleep(0.6)
                    if not adapter.is_open():
                        return True
                except Exception:
                    pass
            time.sleep(0.4)
        return False


def maybe_handle_ios_alert(
    ctx: "ExecutionContext",
    *,
    stage: str = "",
    policy: str = "",
) -> AlertResult:
    return IOSAlertHandler(ctx, policy=policy).maybe_handle(stage=stage, policy=policy)


def try_ios_alert_click(
    ctx: "ExecutionContext",
    locator: Any,
    timeout_ms: int,
    *,
    wait_for_alert: bool | None = None,
) -> bool:
    return IOSAlertHandler(ctx).try_click_locator(
        locator, timeout_ms, wait_for_alert=wait_for_alert,
    )


def ios_alert_after_session(ctx: "ExecutionContext", stage: str) -> None:
    """装包/启动后 opportunistic 处理一次系统弹框。"""
    if not _ios_alert_enabled(ctx):
        return
    res = maybe_handle_ios_alert(ctx, stage=stage)
    if res.handled:
        ctx.log(f"已处理 iOS 系统弹框({res.action}): {(res.text or '')[:120]}")
