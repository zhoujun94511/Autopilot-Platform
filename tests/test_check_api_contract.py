"""tools/check_api_contract.py 白盒。"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "check_api_contract.py"


def test_check_api_contract_module_helpers():
    sys.path.insert(0, str(ROOT))
    from tools import check_api_contract as m

    assert m._norm_path("/api/v1/jobs${q}") == "/api/v1/jobs"
    assert m._norm_path("/api/v1/jobs/${id}/cancel") == "/api/v1/jobs/<param>/cancel"
    assert m._norm_path("/api/v1/jobs/{job_id}") == "/api/v1/jobs/<param>"

    routes = m.parse_backend_routes()
    assert len(routes) > 50
    assert any(r.path == "/api/v1/auth/login" for r in routes)
    assert any(r.path == "/health" for r in routes)

    calls = m.parse_frontend_calls()
    assert len(calls) > 30
    assert any(c.path.startswith("/api/v1/") for c in calls)

    result = m.compare(routes, calls)
    assert result["path_missing"] == []
    assert result["method_mismatch"] == []


def test_check_api_contract_cli_ok():
    proc = subprocess.run(
        [sys.executable, str(TOOL)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "OK:" in proc.stdout or "no path/method mismatches" in proc.stdout
