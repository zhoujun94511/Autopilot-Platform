"""iOS 系统弹框显式关键字。"""

from __future__ import annotations

from ..registry import keyword, KeywordError
from ..context import ExecutionContext
from ...mobile.ios.alert import IOSAlertHandler, maybe_handle_ios_alert


@keyword("ios_alert_handle", name="处理iOS系统弹框", category="Mobile")
def ios_alert_handle(ctx: ExecutionContext, policy: str = "", stage: str = "explicit",
                     **_kw) -> dict:
    """主动检测并处理 iOS 系统级 Alert（非 App 内 onboarding 按钮）。"""
    pol = str(policy or "").strip()
    res = maybe_handle_ios_alert(ctx, stage=stage or "explicit", policy=pol)
    if pol == "strict" and res.exists and not res.handled:
        raise KeywordError(f"strict 策略下未能处理未知弹框: {res.text[:200]}")
    return {
        "exists": res.exists,
        "handled": res.handled,
        "action": res.action,
        "text": res.text,
        "backend": res.backend,
        "reason": res.reason,
    }


@keyword("ios_alert_exists", name="检测iOS系统弹框", category="Mobile")
def ios_alert_exists(ctx: ExecutionContext, **_kw) -> bool:
    """仅检测是否存在系统 Alert，不执行点击。"""
    return IOSAlertHandler(ctx).peek().exists


@keyword("ios_alert_set_policy", name="设置iOS弹框策略", category="Mobile")
def ios_alert_set_policy(ctx: ExecutionContext, policy: str = "auto", **_kw) -> None:
    """设置当前用例运行期的弹框策略（auto/accept/dismiss/ignore/strict）。"""
    pol = str(policy or "auto").strip().lower()
    if pol not in ("auto", "accept", "dismiss", "ignore", "strict"):
        raise KeywordError(f"不支持的 iOS 弹框策略: {policy}")
    ctx.set_var("__ios_alert_policy__", pol)


@keyword("ios_alert_set_enabled", name="开关iOS弹框处理", category="Mobile")
def ios_alert_set_enabled(ctx: ExecutionContext, enabled: str = "是", **_kw) -> None:
    """运行期开关 iOS 弹框自动处理（写入 ctx，不写 settings 文件）。"""
    on = str(enabled).strip().lower() in ("是", "true", "1", "yes", "on")
    ctx.set_var("__ios_alert_enabled__", on)
    if not on:
        ctx.log("已关闭本用例 iOS 弹框自动处理")
    else:
        ctx.log("已开启本用例 iOS 弹框自动处理")
