"""Platform 一键安装脚本：默认全部安装，本仓库 resources 已有则跳过。"""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


def test_install_deps_scripts_exist_and_skip_bundled_resources():
    bat = (_ROOT / "install_deps.bat").read_text(encoding="utf-8")
    ps1 = (_ROOT / "scripts" / "install_deps.ps1").read_text(encoding="utf-8")
    sh = (_ROOT / "scripts" / "install_deps.sh").read_text(encoding="utf-8")

    assert "scripts\\install_deps.ps1" in bat or "scripts/install_deps.ps1" in bat
    for text in (ps1, sh):
        assert "re_adb" in text
        assert "re_go_ios" in text
        assert "uiautomator2" in text
        assert "init_platform" in text
        assert "frontend" in text
        assert "start_dev.py" in text
        assert "autopilot_platform.runner" in text
        assert "跳过" in text or "SKIP" in text
        assert "不重复下载" in text
        assert "兄弟仓" not in text
        assert "NEED-COPY" not in text
        assert "--role" not in text
        assert "-Role" not in text
        assert "NeedPlatform" not in text
        assert "NEED_PLATFORM" not in text
