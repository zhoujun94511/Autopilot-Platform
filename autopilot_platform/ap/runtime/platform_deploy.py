"""企业部署：Platform 通信地址单一真源（IT 配一次，用户只登录）。

运维 / 安装包在下列**任选其一**写入即可（推荐前两项）：

1. 机器环境变量 ``AUTOPILOT_PLATFORM_URL=https://autopilot.company.com``
2. 安装目录或 ``%ProgramData%\\AutoPilot\\platform.url``（单行 URL，无注释）
3. 开发：未配置时回落 ``http://127.0.0.1:8000``（见 ``platform_url``）

用户级 ``settings.json`` 的 ``mc_server_url`` 在**已部署**时默认不再生效，
除非设置 ``AUTOPILOT_ALLOW_PLATFORM_URL_OVERRIDE=1``（联调专用）。
"""

from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path

DEPLOY_ENV_KEY = "AUTOPILOT_PLATFORM_URL"
OVERRIDE_ENV_KEY = "AUTOPILOT_ALLOW_PLATFORM_URL_OVERRIDE"
URL_FILE_NAME = "platform.url"


def install_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def _machine_platform_url_paths() -> list[Path]:
    paths: list[Path] = []
    custom = (os.environ.get("AUTOPILOT_PLATFORM_URL_FILE") or "").strip()
    if custom:
        paths.append(Path(custom))
    paths.append(install_dir() / URL_FILE_NAME)
    if sys.platform == "win32":
        pd = (os.environ.get("ProgramData") or r"C:\ProgramData").strip()
        paths.append(Path(pd) / "AutoPilot" / URL_FILE_NAME)
    elif sys.platform == "darwin":
        paths.append(Path("/Library/Application Support/AutoPilot") / URL_FILE_NAME)
    else:
        paths.append(Path("/etc/autopilot") / URL_FILE_NAME)
    return paths


def _normalize_url(raw: str) -> str:
    return (raw or "").strip().rstrip("/")


def _read_url_file(path: Path) -> str:
    if not path.is_file():
        return ""
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            text = line.strip()
            if not text or text.startswith("#"):
                continue
            return _normalize_url(text)
    except OSError:
        return ""
    return ""


@lru_cache(maxsize=1)
def deploy_platform_url() -> str:
    """IT 部署写入的 Platform 根 URL；空表示未部署（开发模式）。"""
    env = _normalize_url(os.environ.get(DEPLOY_ENV_KEY, ""))
    if env:
        return env
    for path in _machine_platform_url_paths():
        url = _read_url_file(path)
        if url:
            return url
    return ""


def deploy_platform_url_source() -> str:
    """说明当前 deploy URL 来自哪里（doctor / 关于页）。"""
    if _normalize_url(os.environ.get(DEPLOY_ENV_KEY, "")):
        return DEPLOY_ENV_KEY
    for path in _machine_platform_url_paths():
        if _read_url_file(path):
            return str(path)
    return ""


def allow_user_platform_url_override() -> bool:
    raw = (os.environ.get(OVERRIDE_ENV_KEY) or "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return not bool(deploy_platform_url())


def platform_url_locked() -> bool:
    return bool(deploy_platform_url()) and not allow_user_platform_url_override()
