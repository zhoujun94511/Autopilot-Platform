"""跨平台路径约定：存盘用 POSIX 分隔符，读盘时再落到本机 sep。

用例 / picture:: / YAML 里的相对路径应可在 Win / Linux / macOS 间共用。
禁止只按某一平台的 ``\\`` 或盘符习惯写死解析逻辑。
"""

from __future__ import annotations

import os

_SKIP_WALK_DIRS = {
    ".git",
    ".svn",
    "__pycache__",
    ".venv",
    "venv",
    "node_modules",
    ".idea",
    ".pytest_cache",
    ".ruff_cache",
    "reports",
}


def to_posix(path: str) -> str:
    """序列化用：统一为正斜杠（相对路径可跨平台共享）。"""
    return (path or "").replace("\\", "/")


def to_native(path: str) -> str:
    """文件系统用：同时接受 ``/`` 与 ``\\``，再规范为本机分隔符。

    这样在 Linux/macOS 上也能打开 Windows 侧写入的 ``images\\\\a.png`` 相对路径；
    Windows 上同样接受 ``images/a.png``。
    """
    s = (path or "").strip().replace("\\", "/")
    if not s:
        return ""
    if os.sep != "/":
        s = s.replace("/", os.sep)
    return os.path.normpath(s)


def join_project(project_dir: str, rel_or_abs: str) -> str:
    """相对路径拼到工程根；已是绝对路径则直接规范化返回。"""
    p = to_native(rel_or_abs)
    if not p:
        return to_native(project_dir) if project_dir else ""
    if os.path.isabs(p):
        return p
    base = to_native(project_dir or "")
    return os.path.normpath(os.path.join(base, p)) if base else p


def project_relative_or_abs(project_dir: str, abs_path: str) -> str:
    """若 abs_path 落在工程内，返回 POSIX 相对路径；否则返回原绝对路径。"""
    proj = to_native(project_dir or "")
    full = to_native(abs_path)
    if not proj or not full or not os.path.isdir(proj):
        return full
    try:
        rel = os.path.relpath(full, proj)
    except ValueError:
        return full
    if rel.startswith("..") or os.path.isabs(rel):
        return full
    return to_posix(rel)


def resolve_project_file(project_dir: str, raw_path: str) -> str:
    """把用例里的文件路径落到本机可读路径（远程制品关键）。

    优先级：
    1. 相对路径 → 拼到 ``project_dir``；
    2. 绝对路径且存在 → 原样（本机 IDE 直接跑）；
    3. 绝对路径不存在（跨机）→ 用尾段相对路径 / 常见 apps/ 目录 / 工程内同名文件重定位。
    """
    p = to_native((raw_path or "").strip().strip('"'))
    if not p:
        return ""
    proj = to_native(project_dir or "")

    if not os.path.isabs(p):
        return join_project(proj, p) if proj else p

    if os.path.exists(p):
        return p

    if not proj or not os.path.isdir(proj):
        return p

    base_name = os.path.basename(p)
    for cand in (
        os.path.join(proj, base_name),
        os.path.join(proj, "apps", base_name),
        os.path.join(proj, "app", base_name),
        os.path.join(proj, "packages", base_name),
        os.path.join(proj, "package", base_name),
        os.path.join(proj, "ipa", base_name),
        os.path.join(proj, "apk", base_name),
    ):
        if os.path.exists(cand):
            return os.path.normpath(cand)

    parts = p.replace("\\", "/").split("/")
    for i in range(len(parts) - 1):
        rel = "/".join(parts[i:])
        if not rel or rel.endswith(":"):
            continue
        cand = join_project(proj, rel)
        if os.path.exists(cand):
            return cand

    hits: list[str] = []
    for root, dirs, files in os.walk(proj):
        dirs[:] = [d for d in dirs if d not in _SKIP_WALK_DIRS]
        if base_name in files:
            hits.append(os.path.join(root, base_name))
            if len(hits) > 1:
                break
    if len(hits) == 1:
        return os.path.normpath(hits[0])
    return p
