"""关键字注册表与 @keyword 装饰器。

核心机制：用 Python 装饰器自动注册——每个关键字一个函数，签名 fn(ctx, **params) -> Any。
执行引擎按 keyword_id 在 REGISTRY 中派发。

关键字函数约定：
- 第一个参数恒为 ExecutionContext（变量池、对象库、driver 等运行期资源）。
- 其余参数即关键字定义里的 param id（值已由 context 解析过变量/列绑定）。
- 返回值若关键字定义了 OUT 输出变量，由引擎写回 context。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional


class KeywordError(Exception):
    """关键字执行期错误。"""


class NotImplementedKeyword(KeywordError):
    """该关键字在当前版本被有意砍掉/缓做（SAP、内部 RSF/ESB 等）。

    导入旧工程时这类步骤照样进树，执行到时抛此异常并按容错策略处理，而非崩溃。
    """


@dataclass
class KeywordDef:
    keyword_id: str
    func: Callable
    name: str = ""              # 中文名（可由 config/*.xml 元数据补充）
    category: str = ""          # WebUI / Http / Mobile / Public ...
    out_params: list[str] = field(default_factory=list)  # 输出变量参数 id
    legacy_impl: str = ""       # 实现「类:方法」标识，便于回溯对照
    risk_level: str = ""        # read | write | irreversible（可选，来自 XML/装饰器）


REGISTRY: dict[str, KeywordDef] = {}


def keyword(
    keyword_id: str,
    *,
    name: str = "",
    category: str = "",
    out_params: Optional[list[str]] = None,
    legacy_impl: str = "",
    risk_level: str = "",
):
    """注册一个关键字实现。"""

    def deco(func: Callable) -> Callable:
        if keyword_id in REGISTRY:
            raise ValueError(f"关键字 id 重复注册: {keyword_id}")
        REGISTRY[keyword_id] = KeywordDef(
            keyword_id=keyword_id,
            func=func,
            name=name,
            category=category,
            out_params=list(out_params or []),
            legacy_impl=legacy_impl,
            risk_level=(risk_level or "").strip().lower(),
        )
        return func

    return deco


def get(keyword_id: str) -> Optional[KeywordDef]:
    return REGISTRY.get(keyword_id)


def apply_risk_levels(levels: dict[str, str]) -> None:
    """将元数据 risk_level 合并进已注册 KeywordDef（不覆盖装饰器显式非空值）。"""
    for kid, level in (levels or {}).items():
        lv = (level or "").strip().lower()
        if lv not in ("read", "write", "irreversible"):
            continue
        kd = REGISTRY.get(kid)
        if kd is None:
            continue
        if not (kd.risk_level or "").strip():
            kd.risk_level = lv
