"""Runner 侧 scrcpy 配置（对齐 AutoPilot SERVER_VERSION=4.0）。"""

from __future__ import annotations

from pathlib import Path

# autopilot_platform/runner/remote/config.py → 仓库根 Autopilot-Platform/
_REPO_ROOT = Path(__file__).resolve().parents[3]
# 统一放在仓库根 resources/，避免 runner/remote/resources 路径过深不便管理
_RESOURCES = _REPO_ROOT / "resources" / "re_scrcpy"

SCRCPY_SERVER_VERSION = "4.0"
SCRCPY_SERVER_PATH = str(_RESOURCES / "scrcpy-server.jar")
