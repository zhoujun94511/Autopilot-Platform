"""轻量加载仓库 / 工程根 `.env`（不依赖 python-dotenv）。"""

from __future__ import annotations

import os
from pathlib import Path


def load_env_file(path: str | Path, *, override: bool = False) -> bool:
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


def dotenv_disabled() -> bool:
    """``AUTOPILOT_NO_DOTENV=1`` 时跳过自动加载。

    测试与 CI 用它隔离开发机 `.env`：否则本机的 Vision 开关、厂商 Key 会漏进
    进程环境，既让用例结果依赖机器，也可能触发真实 AI 调用。
    """
    raw = (os.environ.get("AUTOPILOT_NO_DOTENV") or "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def load_project_dotenv(
    start: str | Path | None = None,
    *,
    filename: str = ".env",
    override: bool = False,
) -> Path | None:
    if dotenv_disabled():
        return None
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
