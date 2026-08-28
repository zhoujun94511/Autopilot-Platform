"""存储路径解析：拒绝 DB 中 stored_uri 指向制品根目录之外。"""

from __future__ import annotations

from pathlib import Path


def resolve_file_under_root(stored_uri: str, root: Path) -> Path:
    """解析本地文件路径并确保落在 *root* 内（含符号链接解析后）。"""
    if not (stored_uri or "").strip():
        raise FileNotFoundError(stored_uri)
    p = Path(stored_uri).expanduser()
    if not p.is_file():
        raise FileNotFoundError(stored_uri)
    resolved = p.resolve()
    root_resolved = root.expanduser().resolve()
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise PermissionError(f"path outside storage root: {stored_uri}") from exc
    return resolved
