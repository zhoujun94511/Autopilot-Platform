"""跨领域 SQLAlchemy 列表分页、排序辅助。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Select, asc, desc, func, select
from sqlalchemy.orm import Session

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


def clamp_page(page: int | None, page_size: int | None) -> tuple[int | None, int]:
    size = int(page_size if page_size is not None else DEFAULT_PAGE_SIZE)
    size = max(1, min(MAX_PAGE_SIZE, size))
    if page is None:
        return None, size
    return max(1, int(page)), size


def apply_sort(stmt: Select[Any], column: Any, *, order: str = "desc") -> Select[Any]:
    return stmt.order_by(
        asc(column) if (order or "desc").strip().lower() == "asc" else desc(column)
    )


def sort_column(mapping: dict[str, Any], sort_by: str | None, default_key: str) -> Any:
    key = (sort_by or default_key).strip() or default_key
    return mapping.get(key, mapping[default_key])


def select_count(stmt: Select[Any]) -> Select[Any]:
    return select(func.count()).select_from(stmt.order_by(None).subquery())


def paginate(
    db: Session,
    stmt: Select[Any],
    *,
    page: int | None,
    page_size: int,
) -> tuple[list[Any], int]:
    total = int(db.scalar(select_count(stmt)) or 0)
    if page is None:
        return list(db.scalars(stmt).all()), total
    offset = (page - 1) * page_size
    return list(db.scalars(stmt.offset(offset).limit(page_size)).all()), total
