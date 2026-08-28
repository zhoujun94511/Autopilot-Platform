"""Android 文件浏览与操作（ADB sync + shell）。"""

from __future__ import annotations

import base64
import io
import posixpath
import shlex
import stat as stat_lib
from typing import Any

# noinspection PyPackageRequirements
from adbutils import adb  # type: ignore[import-untyped]

_PROTECTED_DELETE = {"/", "/system", "/vendor", "/data", "/sdcard", "/storage"}


def normalize_path(path: str) -> str:
    value = (path or "/").replace("\\", "/")
    if not value.startswith("/"):
        value = "/" + value
    return posixpath.normpath(value) or "/"


def _device(device_id: str) -> Any:
    return adb.device(device_id)


def _entry(path: str, info: Any) -> dict[str, Any]:
    mode = int(getattr(info, "mode", 0) or 0)
    mtime = getattr(info, "mtime", None)
    return {
        "name": posixpath.basename(path) or path,
        "path": path,
        "is_dir": stat_lib.S_ISDIR(mode),
        "is_link": stat_lib.S_ISLNK(mode),
        "size": int(getattr(info, "size", 0) or 0),
        "mtime": int(mtime.timestamp()) if mtime else 0,
        "mode": mode,
    }


def list_directory(device_id: str, path: str = "/sdcard") -> dict[str, Any]:
    target = normalize_path(path)
    sync = _device(device_id).sync
    entries: list[dict[str, Any]] = []
    if target == "/":
        names = str(_device(device_id).shell("ls -1 /") or "").splitlines()
        for name in names:
            clean = name.strip()
            if not clean or clean.startswith("ls:"):
                continue
            full = "/" + clean
            try:
                entries.append(_entry(full, sync.stat(full)))
            except (OSError, RuntimeError):
                entries.append(
                    {
                        "name": clean,
                        "path": full,
                        "is_dir": True,
                        "is_link": False,
                        "size": 0,
                        "mtime": 0,
                        "mode": 0,
                    }
                )
    else:
        for item in sync.list(target):
            item_path = str(item.path)
            full = (
                item_path
                if item_path.startswith("/")
                else posixpath.join(target, item_path)
            )
            entries.append(_entry(full, item))
    entries.sort(
        key=lambda entry: (not entry["is_dir"], entry["name"].lower())
    )
    return {
        "ok": True,
        "path": target,
        "parent": posixpath.dirname(target) if target != "/" else "/",
        "entries": entries,
    }


def stat_path(device_id: str, path: str) -> dict[str, Any] | None:
    target = normalize_path(path)
    info = _device(device_id).sync.stat(target)
    if not info or not getattr(info, "mode", 0):
        return None
    return _entry(target, info)


def mkdir(device_id: str, path: str) -> dict[str, Any]:
    target = normalize_path(path)
    if target == "/":
        raise ValueError("不能创建根目录")
    _device(device_id).shell(f"mkdir -p {shlex.quote(target)}")
    return {"ok": True, "path": target}


def rename(device_id: str, src: str, dst: str) -> dict[str, Any]:
    source = normalize_path(src)
    target = normalize_path(dst)
    if source == "/" or target == "/":
        raise ValueError("不能重命名根目录")
    _device(device_id).shell(
        f"mv {shlex.quote(source)} {shlex.quote(target)}"
    )
    return {"ok": True, "path": target}


def delete(device_id: str, path: str, recursive: bool = False) -> dict[str, Any]:
    target = normalize_path(path)
    if target in _PROTECTED_DELETE:
        raise PermissionError(f"拒绝删除受保护路径 {target}")
    flag = "-rf" if recursive else "-f"
    _device(device_id).shell(f"rm {flag} {shlex.quote(target)}")
    return {"ok": True, "path": target}


def pull_bytes(
    device_id: str,
    path: str,
    *,
    max_bytes: int = 256 * 1024 * 1024,
) -> bytes:
    target = normalize_path(path)
    info = stat_path(device_id, target)
    if info is None or info["is_dir"]:
        raise FileNotFoundError(target)
    if int(info["size"]) > max_bytes:
        raise ValueError(f"文件超过下载上限 {max_bytes} bytes")
    return bytes(_device(device_id).sync.read_bytes(target))


def pull_chunks(
    device_id: str,
    path: str,
    *,
    chunk_size: int = 48 * 1024,
) -> list[str]:
    data = pull_bytes(device_id, path)
    return [
        base64.b64encode(data[offset : offset + chunk_size]).decode("ascii")
        for offset in range(0, len(data), chunk_size)
    ]


def push_bytes(device_id: str, path: str, data: bytes) -> dict[str, Any]:
    target = normalize_path(path)
    if target == "/" or target.endswith("/"):
        raise ValueError("目标必须是文件路径")
    _device(device_id).sync.push(io.BytesIO(data), target)
    return {"ok": True, "path": target, "size": len(data)}
