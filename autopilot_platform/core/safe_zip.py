"""安全 ZIP 解压：拒绝路径穿越与解压炸弹。

Platform 安全真源（AUD-2026-19）。``ap.runtime.safe_zip`` 再导出本模块；
IDE ``autopilot.runtime.safe_zip`` 为双核副本，由双仓门禁做 AST 语义对齐。
"""

from __future__ import annotations

import zipfile
from pathlib import Path

DEFAULT_MAX_ENTRIES = 20_000
DEFAULT_MAX_TOTAL_UNCOMPRESSED = 512 * 1024 * 1024  # 512 MiB
DEFAULT_MAX_RATIO = 100


def safe_extractall(
    zf: zipfile.ZipFile,
    dest_dir: Path | str,
    *,
    max_entries: int = DEFAULT_MAX_ENTRIES,
    max_total_uncompressed: int = DEFAULT_MAX_TOTAL_UNCOMPRESSED,
    max_ratio: int = DEFAULT_MAX_RATIO,
) -> None:
    """将 zip 解压到 dest_dir；非法路径或超限时抛 ValueError。"""
    dest = Path(dest_dir).resolve()
    dest.mkdir(parents=True, exist_ok=True)
    infos = zf.infolist()
    if len(infos) > max_entries:
        raise ValueError(f"zip has too many entries ({len(infos)} > {max_entries})")

    total = 0
    for info in infos:
        name = info.filename or ""
        if not name or name.endswith("/"):
            if name and not _is_safe_member(name, dest):
                raise ValueError(f"unsafe zip path: {name!r}")
            continue

        if info.file_size < 0:
            raise ValueError(f"invalid zip entry size: {name!r}")
        total += int(info.file_size)
        if total > max_total_uncompressed:
            raise ValueError(
                f"zip uncompressed size exceeds limit ({max_total_uncompressed} bytes)"
            )
        compressed = max(1, int(info.compress_size or 0))
        if info.file_size > 0 and (info.file_size // compressed) > max_ratio:
            raise ValueError(f"zip entry compression ratio too high: {name!r}")

        if not _is_safe_member(name, dest):
            raise ValueError(f"unsafe zip path: {name!r}")

        target = (dest / name).resolve()
        parent_dir = Path(str(target.parent))
        parent_dir.mkdir(parents=True, exist_ok=True)
        with zf.open(info, "r") as src, open(target, "wb") as out:
            while True:
                chunk = src.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)


def _is_safe_member(name: str, dest: Path) -> bool:
    norm = name.replace("\\", "/")
    if norm.startswith("/") or norm.startswith("../") or "/../" in f"/{norm}/":
        return False
    if ":" in norm.split("/")[0]:
        return False
    parts = Path(norm).parts
    if ".." in parts:
        return False
    try:
        resolved = (dest / norm).resolve()
    except (OSError, ValueError):
        return False
    try:
        resolved.relative_to(dest)
    except ValueError:
        return False
    return True


__all__ = [
    "DEFAULT_MAX_ENTRIES",
    "DEFAULT_MAX_RATIO",
    "DEFAULT_MAX_TOTAL_UNCOMPRESSED",
    "safe_extractall",
]
