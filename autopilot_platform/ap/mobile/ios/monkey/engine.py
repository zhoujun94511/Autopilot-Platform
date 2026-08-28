"""iOS Monkey 主循环。"""

from __future__ import annotations

import json
import os
import random
import time
from datetime import datetime
from typing import TYPE_CHECKING, Any

from ....keywords.registry import KeywordError
from ..alert import maybe_handle_ios_alert
from .bundle import resolve_target_bundle_id
from .config import build_monkey_config
from .driver import IOSMonkeyDriver, create_monkey_driver
from .element import pick_random_element
from .policy import (
    MonkeyConfig,
    choose_action,
    random_direction,
    random_point,
    should_refresh_source,
    throttle_sleep_ms,
)
from .recovery import MonkeyRecovery
from .recorder import MonkeyRecorder
from .state import StuckTracker, build_state_hash
from .state_cache import PageStateCache
from .watchdog import ensure_monkey_stack
from ....engine.interrupt import RunInterrupted, flow_checkpoint, interruptible_sleep

if TYPE_CHECKING:
    from ....keywords.context import ExecutionContext


class IOSMonkeyEngine:
    def __init__(
        self,
        ctx: "ExecutionContext",
        driver: IOSMonkeyDriver,
        config: MonkeyConfig,
        *,
        report_root: str = "",
    ):
        self.ctx = ctx
        self.driver = driver
        self.config = config
        self.rng = random.Random(config.seed)
        base = str(ctx.get_var("__project_path__") or "")
        self.recorder = MonkeyRecorder(
            base or ".",
            root=report_root,
            bundle_id=config.bundle_id,
            backend=driver.backend,
            seed=config.seed or 0,
            duration_sec=config.duration_sec,
            policy=config.policy_preset,
        )
        self.recovery = MonkeyRecovery(
            ctx, driver, config.bundle_id, alert_handle=self._handle_alert,
        )
        self.stuck = StuckTracker(config.stuck_same_state_limit)
        self._page = PageStateCache()
        self._started_at = 0.0

    def _handle_alert(self) -> None:
        res = maybe_handle_ios_alert(self.ctx, stage="ios_monkey")
        if res.handled:
            self.recorder.bump_alert()
            self.ctx.log(f"Monkey：已处理系统弹框({res.action})")

    def _watchdog(self) -> None:
        if ensure_monkey_stack(self.ctx, self.config.bundle_id):
            return
        self.recorder.bump_watchdog()

    def _execute_action(
        self,
        action: str,
        w: int,
        h: int,
        elements: list,
    ) -> dict[str, Any]:
        detail: dict[str, Any] = {"action": action}
        if action == "tap_random_point":
            x, y = random_point(self.rng, w, h, self.config.bounds)
            self.driver.tap(x, y)
            detail.update(x=x, y=y)
        elif action == "tap_random_element":
            el = pick_random_element(
                elements, self.rng, allow_dangerous=self.config.allow_dangerous,
            )
            if el is None:
                x, y = random_point(self.rng, w, h, self.config.bounds)
                self.driver.tap(x, y)
                detail.update(action="tap_random_point_fallback", x=x, y=y)
            else:
                cx, cy = el.center
                self.driver.tap(cx, cy)
                detail.update(label=el.display_text, x=cx, y=cy)
        elif action == "swipe_random":
            direction = random_direction(self.rng)
            strategy = self.driver.swipe_direction(direction)
            detail.update(direction=direction, strategy=strategy)
        elif action == "long_press_random":
            x, y = random_point(self.rng, w, h, self.config.bounds)
            self.driver.long_press(x, y, 800)
            detail.update(x=x, y=y)
        elif action == "handle_alert":
            self._handle_alert()
        elif action == "app_recover":
            ok = self.recovery.ensure_foreground()
            detail.update(foreground=ok)
        else:
            x, y = random_point(self.rng, w, h, self.config.bounds)
            self.driver.tap(x, y)
            detail.update(action="tap_random_point", x=x, y=y)
        return detail

    @staticmethod
    def _timed_out(deadline: float | None) -> bool:
        return deadline is not None and time.monotonic() >= deadline

    def run(self) -> dict[str, Any]:
        cfg = self.config
        self._started_at = time.monotonic()
        deadline = (self._started_at + cfg.duration_sec) if cfg.duration_sec > 0 else None

        self._handle_alert()
        if not self.recovery.ensure_foreground():
            raise KeywordError(f"Monkey 无法将被测 App 置于前台: {cfg.bundle_id}")

        mode = f"时长 {cfg.duration_sec}s" if cfg.duration_sec > 0 else f"事件数 {cfg.max_events}"
        self.ctx.log(
            f"iOS Monkey 启动: {mode} preset={cfg.policy_preset} "
            f"throttle={cfg.throttle_ms}±{cfg.throttle_jitter_ms}ms "
            f"source_interval={cfg.source_interval}"
        )

        errors = 0
        index = 0
        while True:
            if flow_checkpoint(self.ctx):
                elapsed = int(time.monotonic() - self._started_at)
                summary = self.recorder.finalize(
                    result="cancelled",
                    duration_sec=elapsed,
                )
                self.ctx.log("iOS Monkey 已按用户请求停止")
                return summary
            index += 1
            if self._timed_out(deadline):
                break
            if index > cfg.max_events:
                break

            if index % cfg.wda_watchdog_interval == 0:
                self._watchdog()

            if index % cfg.foreground_check_interval == 0:
                self.recovery.ensure_foreground()
            if index % cfg.alert_check_interval == 0:
                self._handle_alert()

            w, h = self.driver.window_size()
            action = choose_action(self.rng, cfg.weights)
            need_source = should_refresh_source(
                index, action,
                interval=cfg.source_interval,
                last_index=self._page.last_index,
                force=self.stuck.is_stuck(),
            )
            if need_source:
                elements, state_hash = self._page.refresh(
                    self.driver, cfg.bundle_id, index=index, w=w, h=h,
                    build_hash=build_state_hash,
                )
            else:
                elements, state_hash = self._page.reuse()

            same = self.stuck.observe(state_hash or "empty")
            if self.stuck.is_stuck():
                self.recovery.escape_stuck(same, serious_limit=cfg.stuck_same_state_limit + 4)
                self.recorder.bump_stuck()
                self._page.refresh(
                    self.driver, cfg.bundle_id, index=index, w=w, h=h,
                    build_hash=build_state_hash,
                )

            payload: dict[str, Any] = {
                "index": index,
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "backend": self.driver.backend,
                "state": state_hash,
                "sameStateCount": same,
                "sourceRefreshed": need_source,
            }
            try:
                payload.update(self._execute_action(action, w, h, elements))
                payload["result"] = "ok"
            except Exception as exc:  # noqa: BLE001
                errors += 1
                payload["result"] = "error"
                payload["error"] = str(exc)
                self._handle_alert()
                self._watchdog()
                self.recorder.save_error(index, self.driver, exc, context=payload)
                if errors >= 3:
                    self.recorder.finalize(
                        result="failed",
                        duration_sec=int(time.monotonic() - self._started_at),
                    )
                    raise KeywordError(f"iOS Monkey 连续异常过多: {exc}") from exc

            self.recorder.record_event(payload)
            sleep_ms = throttle_sleep_ms(cfg, self.rng)
            if sleep_ms > 0:
                try:
                    interruptible_sleep(sleep_ms / 1000.0, self.ctx)
                except RunInterrupted:
                    elapsed = int(time.monotonic() - self._started_at)
                    summary = self.recorder.finalize(
                        result="cancelled",
                        duration_sec=elapsed,
                    )
                    self.ctx.log("iOS Monkey 已按用户请求停止")
                    return summary

        elapsed = int(time.monotonic() - self._started_at)
        result = "passed" if errors == 0 else "passed_with_errors"
        return self.recorder.finalize(result=result, duration_sec=elapsed)


def run_ios_monkey(ctx: "ExecutionContext", steps: int = 20, **kwargs: Any) -> None:
    """mobile_monkey 的 iOS 分支入口。

    资源策略：仅停止本模块启动的 syslog 子进程；**不**关闭 WDA 隧道、driver 或
    mobile 会话，以便同一用例内 Monkey 之后的步骤可继续复用已拉起的 WDA。
    """
    from ....keywords.mobile.driver import get_manager
    from ....runtime import settings as app_settings
    from .device_logs import DeviceLogCollector, LogCollectionOptions
    from .paths import allocate_report_dir
    from .report_html import render_monkey_report
    from .report_registry import write_latest_pointer

    bundle_id = str(kwargs.get("bundleId") or kwargs.get("bundle") or "").strip()
    if not bundle_id:
        bundle_id = resolve_target_bundle_id(ctx)
    if not bundle_id:
        raise KeywordError(
            "无法确定 iOS Monkey 目标 Bundle ID；请先执行装包/启动 App，"
            "或配置 DataConfig 变量 app_package"
        )

    mgr = get_manager(ctx)
    if mgr.platform != "ios":
        raise KeywordError("当前会话不是 iOS，无法执行 iOS Monkey")
    if mgr.optional_driver() is None:
        raise KeywordError("iOS 会话未创建，请先执行 mobile_app_start 或 mobile_app_install_and_open")

    config = build_monkey_config(ctx, bundle_id, steps, **kwargs)
    from .session_prep import prepare_monkey_appium_session
    prepare_monkey_appium_session(ctx, bundle_id)
    driver = create_monkey_driver(ctx)
    base = str(ctx.get_var("__project_path__") or ".")
    udid = str(ctx.get_var("__device_udid__") or "")
    report_root = allocate_report_dir(base, udid=udid)

    log_opts = LogCollectionOptions.from_context(ctx, kwargs)
    collector = DeviceLogCollector(
        udid, bundle_id, report_root, log_opts, log=ctx.log,
    )

    summary: dict[str, Any] = {"reportDir": report_root, "bundleId": bundle_id}
    try:
        with collector:
            summary = IOSMonkeyEngine(
                ctx, driver, config, report_root=report_root,
            ).run()
    finally:
        if collector.active:
            collector.stop()

    if summary.get("result") == "cancelled":
        raise RunInterrupted("用户停止")

    dev = collector.last_summary
    if dev is not None:
        summary["deviceLogs"] = dev.to_dict()
        if dev.crashRelevantCount > 0:
            summary["crashDetected"] = True
        summary_path = os.path.join(report_root, "summary.json")
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)

    report_html = ""
    want_html = app_settings.ios_monkey_report_html()
    if str(kwargs.get("reportHtml") or "").strip().lower() in ("0", "false", "no", "off"):
        want_html = False
    if want_html:
        # noinspection PyBroadException
        try:
            report_html = render_monkey_report(report_root)
            summary["reportHtml"] = report_html
            with open(os.path.join(report_root, "summary.json"), "w", encoding="utf-8") as f:
                json.dump(summary, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            ctx.log(f"Monkey：report.html 生成失败（忽略）: {exc}")

    write_latest_pointer(base, report_root, report_html, udid=udid)
    ctx.set_var("__ios_monkey_last_report__", report_root)

    ctx.log(
        f"iOS Monkey 完成: bundle[{bundle_id}] 事件[{summary.get('eventCount')}] "
        f"耗时[{summary.get('durationSec')}s] seed[{config.seed}] "
        f"preset[{config.policy_preset}] backend[{summary.get('backend')}]\n"
        f"报告目录: {summary.get('reportDir')}"
        + (f"\nHTML: {report_html}" if report_html else "")
    )
