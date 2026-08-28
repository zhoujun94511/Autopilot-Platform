"""PROD-P0-001 回归：Platform Runner 执行链不得 import 顶层 autopilot 包。"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER_DIR = ROOT / "autopilot_platform" / "runner"
AP_META = ROOT / "autopilot_platform" / "ap" / "metadata" / "keyword_meta.py"

_FORBIDDEN = re.compile(r"""(?:^|\n)\s*(?:from|import)\s+autopilot(?:\.|\s|$)""", re.M)


def _assert_no_autopilot_import(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    hits = _FORBIDDEN.findall(text)
    assert not hits, f"{path.relative_to(ROOT)} 仍引用 autopilot 包: {hits!r}"


def test_runner_execute_py_uses_ap_package_only():
    _assert_no_autopilot_import(RUNNER_DIR / "execute.py")


def test_runner_agent_py_uses_ap_package_only():
    _assert_no_autopilot_import(RUNNER_DIR / "agent.py")


def test_keyword_meta_py_uses_ap_keywords():
    text = AP_META.read_text(encoding="utf-8")
    assert "autopilot_platform.ap.keywords" in text
    _assert_no_autopilot_import(AP_META)


def test_execute_job_lazy_imports_ap_engine(tmp_path, monkeypatch):
    """运行时懒 import 路径可解析（无需用户本机 autopilot 包）。"""
    monkeypatch.chdir(tmp_path)
    import autopilot_platform.runner.execute as execute_mod

    import autopilot_platform.ap.engine as eng
    import autopilot_platform.ap.report as rep

    assert hasattr(execute_mod, "execute_job")
    assert hasattr(eng, "run_project_directory")
    assert hasattr(rep, "write_report")
