"""ARCH-002：OpenAPI 导出与 capability 审计脚本 smoke。"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_export_openapi_writes_json(tmp_path):
    out = tmp_path / "openapi.json"
    proc = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "export_openapi.py"), "--out", str(out), "--pretty"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    spec = json.loads(out.read_text(encoding="utf-8"))
    assert len(spec.get("paths", {})) > 50
    assert "/api/v1/runners/{runner_id}/scoped-token" in spec["paths"]


def test_audit_capability_routes_against_export(tmp_path):
    out = tmp_path / "openapi.json"
    subprocess.run(
        [sys.executable, str(ROOT / "tools" / "export_openapi.py"), "--out", str(out)],
        cwd=str(ROOT),
        check=True,
    )
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "audit_capability_routes.py"),
            "--openapi",
            str(out),
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout


def test_openapi_contract_check_passes_when_in_sync():
    """AUD-2026-11：已提交 contracts/openapi 须与现场 OpenAPI 一致（不写盘）。"""
    contract = ROOT / "contracts" / "openapi" / "openapi.v1.json"
    assert contract.is_file(), "缺少契约文件，请先 tools/export_openapi.py --pretty"
    proc = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "export_openapi.py"), "--check"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, (
        (proc.stderr or proc.stdout)
        + "\n契约过期时请运行: python tools/export_openapi.py --pretty 并提交"
    )


def test_openapi_contract_check_detects_drift(tmp_path):
    import importlib.util

    bad = tmp_path / "openapi.v1.json"
    bad.write_text('{"openapi":"3.1.0","paths":{}}', encoding="utf-8")
    loc = ROOT / "tools" / "export_openapi.py"
    spec = importlib.util.spec_from_file_location("export_openapi_mod", loc)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.check_contract(contract_path=bad) == 1
