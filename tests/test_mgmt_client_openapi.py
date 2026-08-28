"""MgmtClient 操作清单 ↔ OpenAPI 契约（ARCH-002）。"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "contracts" / "mgmt_client_ops.json"
EXTRACT = ROOT / "tools" / "extract_mgmt_client_ops.py"
CLIENT = ROOT / "autopilot_platform" / "ap" / "mgmt" / "client.py"


def _normalize(path: str) -> str:
    return re.sub(r"\{[^}]+}", "{param}", path)


def _openapi_paths(spec: dict) -> set[tuple[str, str]]:
    out: set[tuple[str, str]] = set()
    for p, methods in spec.get("paths", {}).items():
        for m in methods:
            if m.upper() in ("GET", "POST", "PUT", "PATCH", "DELETE"):
                out.add((m.upper(), _normalize(p)))
    return out


def _load_openapi() -> dict:
    import tempfile

    tmp = Path(tempfile.mkdtemp()) / "o.json"
    subprocess.run(
        [sys.executable, str(ROOT / "tools" / "export_openapi.py"), "--out", str(tmp)],
        cwd=str(ROOT),
        check=True,
    )
    return json.loads(tmp.read_text(encoding="utf-8"))


def test_manifest_matches_live_client_source():
    proc = subprocess.run(
        [sys.executable, str(EXTRACT), "--client", str(CLIENT)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=True,
    )
    live = json.loads(proc.stdout)
    on_disk = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert live["operations"] == on_disk["operations"], (
        "contracts/mgmt_client_ops.json 过期；请运行: "
        "python tools/extract_mgmt_client_ops.py --write contracts/mgmt_client_ops.json"
    )


def test_mgmt_client_ops_exist_in_openapi():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    paths = _openapi_paths(_load_openapi())
    missing: list[str] = []
    for op in manifest.get("operations") or []:
        key = (op["method"], _normalize(op["path"]))
        if key not in paths:
            missing.append(f"{op['method']} {op['path']}")
    assert not missing, "MgmtClient 操作在 OpenAPI 中缺失:\n" + "\n".join(missing)
