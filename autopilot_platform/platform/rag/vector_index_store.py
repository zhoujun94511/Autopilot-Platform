"""项目级向量索引门面：本地 SQLite 存储 + 本地/远程嵌入器。

存储：仅 ``vector_index_sqlite``（BLOB + FTS5）。
嵌入：由 ``embedder_factory`` 选择 hashing（本地）或 OpenAI 兼容 API（远程）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import vector_index_sqlite as sqlite_store


def index_dir() -> Path:
    return sqlite_store.db_path().parent


def index_path(project_id: str) -> Path:
    """返回 SQLite 库路径（单库多项目；保留 project_id 形参兼容调用方）。"""
    _ = project_id
    return sqlite_store.db_path()


def load_index(project_id: str) -> dict[str, Any]:
    return sqlite_store.load_project(project_id)


def save_index(project_id: str, data: dict[str, Any]) -> Path:
    return sqlite_store.save_project(project_id, data)


def invalidate_project_index(project_id: str) -> None:
    sqlite_store.clear_project(project_id)


def remove_index_item(project_id: str, item_id: str) -> None:
    sqlite_store.delete_item(project_id, item_id)
