"""运维列表统一分页：page/page_size 与 legacy limit/offset 互转。"""

from __future__ import annotations


def normalize_page_params(
    *,
    page: int | None = None,
    page_size: int | None = None,
    limit: int | None = None,
    offset: int | None = None,
    default_size: int = 50,
    max_size: int = 200,
) -> tuple[int, int]:
    """返回 (page, page_size)。"""
    if page_size is not None:
        size = int(page_size)
    elif limit is not None:
        size = int(limit)
    else:
        size = default_size
    size = max(1, min(max_size, size))

    if page is not None:
        pg = max(1, int(page))
    elif offset is not None:
        pg = max(1, int(offset) // size + 1)
    else:
        pg = 1
    return pg, size


def page_offset(page: int, page_size: int) -> int:
    return max(0, (max(1, int(page)) - 1) * max(1, int(page_size)))


def slice_page(items: list, *, page: int, page_size: int) -> tuple[list, int]:
    """内存列表分页（已过滤全集）。"""
    total = len(items)
    start = page_offset(page, page_size)
    end = start + max(1, int(page_size))
    return items[start:end], total


def unwrap_items(body) -> list:
    """兼容 ListPage 与 legacy 裸数组。"""
    if isinstance(body, dict) and isinstance(body.get("items"), list):
        return body["items"]
    if isinstance(body, list):
        return body
    return []
