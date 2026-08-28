"""移动端设备层共享路径（仓库根 resources/）。"""

from __future__ import annotations

from pathlib import Path

# autopilot_platform/ap/mobile/_paths.py → 上溯四级到 Console 仓库根
REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
