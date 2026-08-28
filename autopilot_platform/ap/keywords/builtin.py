"""内置/框架关键字：日志、变量、校验、逻辑控制。

这些无任何外部依赖，对应关键字分类 Logic / Verify / Common，
也是执行引擎在无浏览器环境下端到端自测的基础。
"""

from __future__ import annotations

from .registry import keyword, KeywordError
from .context import ExecutionContext


@keyword("log", name="日志输出", category="Public", legacy_impl="CommonKeyword:log")
def kw_log(ctx: ExecutionContext, message: str = "", **_kw) -> None:
    ctx.log(message)


@keyword(
    "set_var",
    name="设置变量",
    category="Public",
    out_params=["name"],
    legacy_impl="CommonKeyword:setVariable",
)
def kw_set_var(_ctx: ExecutionContext, name: str = "", value: str = "", **_kw) -> dict:
    """把 value 存入变量 name。引擎按 out_params 回写时使用返回 dict。"""
    return {name: value}


@keyword(
    "verify_equals",
    name="校验相等",
    category="Public",
    legacy_impl="VerifyKeyword:assertEquals",
)
def kw_verify_equals(_ctx: ExecutionContext, actual: str = "", expect: str = "", **_kw) -> None:
    if str(actual) != str(expect):
        raise KeywordError(f"校验失败：期望[{expect}] 实际[{actual}]")


@keyword(
    "verify_contains",
    name="校验包含",
    category="Public",
    legacy_impl="VerifyKeyword:assertContains",
)
def kw_verify_contains(_ctx: ExecutionContext, text: str = "", sub: str = "", **_kw) -> None:
    if str(sub) not in str(text):
        raise KeywordError(f"校验失败：[{text}] 不包含 [{sub}]")
