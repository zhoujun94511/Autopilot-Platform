"""注册 intent_act 关键字（薄封装 → IntentRuntime）。"""

from __future__ import annotations

from ..keywords.registry import keyword
from ..keywords.context import ExecutionContext


@keyword(
    "intent_act",
    name="意图动作",
    category="Public",
)
def intent_act(
    ctx: ExecutionContext,
    intent_id: str = "",
    action: str = "custom",
    target: str = "",
    value: str = "",
    text: str = "",
    logical_case_id: str = "",
    revision_id: str = "",
    channel: str = "ui",
    **_kw,
) -> None:
    from .runtime import run_intent_act  # 延迟：执行时再加载；intent 包 PEP 562 亦不急切导出 runtime

    run_intent_act(
        ctx,
        intent_id=intent_id,
        action=action,
        target=target,
        value=value,
        text=text,
        logical_case_id=logical_case_id,
        revision_id=revision_id,
        channel=channel,
    )
