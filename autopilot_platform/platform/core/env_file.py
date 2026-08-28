"""轻量加载仓库根 `.env`（不依赖 python-dotenv）。

已存在的环境变量默认不覆盖（shell/CI 优先）。
"""

from __future__ import annotations

import os
from pathlib import Path


def load_env_file(path: str | Path, *, override: bool = False) -> bool:
    """解析 KEY=VALUE；成功加载返回 True。"""
    p = Path(path)
    if not p.is_file():
        return False
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return False
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        if not key:
            continue
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
            val = val[1:-1]
        if override or key not in os.environ:
            os.environ[key] = val
    return True


def load_project_dotenv(
    start: str | Path | None = None,
    *,
    filename: str = ".env",
    override: bool = False,
) -> Path | None:
    """自 start 向上查找 filename，找到则加载；返回路径或 None。"""
    cur = Path(start or Path.cwd()).resolve()
    for _ in range(8):
        candidate = cur / filename
        if candidate.is_file():
            load_env_file(candidate, override=override)
            return candidate
        if cur.parent == cur:
            break
        cur = cur.parent
    return None
