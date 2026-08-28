"""停止后精简版 after 清理：仅执行白名单内的收尾关键字。"""

from __future__ import annotations

from typing import Iterable

# 停止后允许执行的 after 关键字（关会话/停服务/关连接类，跳过报告/上传等）
TEARDOWN_KEYWORD_IDS: frozenset[str] = frozenset({
    "mobile_app_close",
    "appium_stop",
    "mobile_browser_close",
    "web_browser_close",
    "web_browser_close_andSwitch",
    "http_stopMockStubServer",
    "http_session_end",
    "database_close",
    "linux_ssh_close",
    "ftp_ftpclient_closeFtp",
})


def is_teardown_keyword(keyword_id: str) -> bool:
    return str(keyword_id or "") in TEARDOWN_KEYWORD_IDS


def iter_teardown_steps(nodes: Iterable) -> list:
    """深度遍历步骤树，收集白名单内的普通步骤（不含条件/循环控制）。"""
    from ..model.testcase import Step

    out: list = []

    def visit(items) -> None:
        for node in items or []:
            if isinstance(node, Step):
                if not node.is_condition and is_teardown_keyword(node.keyword_id):
                    out.append(node)
            children = getattr(node, "children", None)
            if children:
                visit(children)

    visit(nodes)
    return out
