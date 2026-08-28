"""测试辅助：兼容 ListPage 与 legacy 裸数组响应。"""

from __future__ import annotations

from typing import Any


def page_items(body: Any) -> list:
    if isinstance(body, dict) and isinstance(body.get("items"), list):
        return body["items"]
    if isinstance(body, list):
        return body
    return []


def page_total(body: Any, *, fallback: int | None = None) -> int:
    if isinstance(body, dict) and "total" in body:
        return int(body["total"])
    if isinstance(body, list):
        return len(body)
    return int(fallback or 0)
