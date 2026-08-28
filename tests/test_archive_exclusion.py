"""AUD-2026-18：archive/ 遗留源码保持排除，禁止接入运行时包。"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "autopilot_platform"
ARCHIVE = ROOT / "archive"
LEGACY = ARCHIVE / "testpilot_design_legacy"

# 禁止从运行时包导入归档树（字符串常量 / 注释除外）
_FORBIDDEN_IMPORT_ROOTS = frozenset(
    {
        "archive",
        "testpilot_design_legacy",
    }
)


def _iter_runtime_py() -> list[Path]:
    return sorted(p for p in PKG.rglob("*.py") if "__pycache__" not in p.parts)


def _imported_roots(tree: ast.AST) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".", 1)[0])
                roots.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".", 1)[0])
            roots.add(node.module)
    return roots


def test_packaging_excludes_archive():
    """setuptools 仅打包 autopilot_platform*；工具链 exclude archive。"""
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'include = ["autopilot_platform*"]' in pyproject
    assert re.search(r'(?m)^\s*"archive"\s*,?\s*$', pyproject), (
        "ruff/basedpyright 须 exclude archive（AUD-2026-18）"
    )


def test_design_package_is_stub_not_legacy_import():
    from autopilot_platform import design

    assert getattr(design, "LEGACY_ARCHIVE", False) is True
    assert "archive/" in getattr(design, "LEGACY_PATH", "")
    src = Path(design.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    bad = _imported_roots(tree) & _FORBIDDEN_IMPORT_ROOTS
    assert not bad, f"design 占位包不得 import 归档: {bad}"


def test_runtime_package_does_not_import_archive():
    violations: list[str] = []
    for path in _iter_runtime_py():
        text = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(text)
        except SyntaxError as exc:
            violations.append(f"{path.relative_to(ROOT)}: syntax {exc}")
            continue
        hit = _imported_roots(tree) & _FORBIDDEN_IMPORT_ROOTS
        if hit:
            violations.append(f"{path.relative_to(ROOT)}: {sorted(hit)}")
    assert not violations, "运行时包不得接线 archive/:\n" + "\n".join(violations)


def test_vscode_and_docs_keep_archive_excluded():
    settings = ROOT / ".vscode" / "settings.json"
    assert settings.is_file()
    body = settings.read_text(encoding="utf-8")
    assert "**/archive/**" in body
    legacy_md = PKG / "design" / "LEGACY.md"
    assert legacy_md.is_file()
    assert "AUD-2026-18" in legacy_md.read_text(encoding="utf-8")
    # archive 可整目录删除；若仍在仓内则须有排除说明
    if ARCHIVE.is_dir():
        readme = LEGACY / "README.md"
        assert readme.is_file()
        text = readme.read_text(encoding="utf-8")
        assert "Excluded" in text or "排除" in text
        assert "AUD-2026-18" in text


def test_spent_converge_scripts_are_archived_and_refused():
    spent = ARCHIVE / "platform_package_converge"
    readme = spent / "README.md"
    assert readme.is_file()
    text = readme.read_text(encoding="utf-8")
    assert "禁止再执行" in text
    assert "services.execution" in text
    assert not (ROOT / "tools" / "converge_platform_packages.py").exists()
    for name in (
        "converge_platform_packages.py",
        "converge_platform_phase6.py",
        "rewrite_platform_shims.py",
        "fix_package_imports.py",
        "fix_services_sibling_imports.py",
        "fix_phase6_leftover_imports.py",
        "fix_session_factory_access.py",
    ):
        archived = spent / name
        body = archived.read_text(encoding="utf-8")
        compile(body, name, "exec")
        assert "spent one-shot" in body
        assert not (ROOT / "tools" / name).exists()
    archived_entry = spent / "converge_platform_packages.py"
    refused = subprocess.run(
        [sys.executable, str(archived_entry)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert refused.returncode == 2


def test_pyright_gate_is_platform_only():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'include = ["autopilot_platform/platform"]' in pyproject
    checker = (ROOT / "tools" / "check_types.py").read_text(encoding="utf-8")
    assert "--runtime" in checker
    assert '"autopilot_platform"' in checker and '"platform"' in checker


def test_no_sys_path_hack_into_archive():
    """禁止把 archive 塞进 sys.path 伪装成可导入包。"""
    bad: list[str] = []
    for path in _iter_runtime_py():
        text = path.read_text(encoding="utf-8")
        if "sys.path" not in text:
            continue
        if re.search(r"archive[/\\]testpilot|testpilot_design_legacy", text):
            bad.append(str(path.relative_to(ROOT)))
    assert not bad, f"疑似将 archive 注入 sys.path: {bad}"
