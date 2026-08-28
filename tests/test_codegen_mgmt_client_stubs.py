"""ARCH-002：MgmtClient codegen stub 与 OpenAPI/manifest 对齐。"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "contracts" / "mgmt_client_ops.json"
GENERATED = ROOT / "autopilot_platform" / "ap" / "mgmt" / "client_ops_generated.py"
CODEGEN = ROOT / "tools" / "codegen_mgmt_client_stubs.py"
CLIENT = ROOT / "autopilot_platform" / "ap" / "mgmt" / "client.py"
EXTRACT = ROOT / "tools" / "extract_mgmt_client_ops.py"


def test_generated_ops_match_manifest():
    from autopilot_platform.ap.mgmt.client_ops_generated import MGMT_CLIENT_OPERATIONS

    on_disk = json.loads(MANIFEST.read_text(encoding="utf-8"))
    expected = [(op["method"], op["path"]) for op in on_disk.get("operations") or []]
    assert list(MGMT_CLIENT_OPERATIONS) == expected


def test_codegen_output_is_fresh():
    proc = subprocess.run(
        [sys.executable, str(CODEGEN), "--manifest", str(MANIFEST)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        # 生成物含中文注释；Windows 默认 gbk 会解码失败
        encoding="utf-8",
        check=True,
    )
    live = proc.stdout
    on_disk = GENERATED.read_text(encoding="utf-8")
    assert live == on_disk, (
        "client_ops_generated.py 过期；请运行: "
        "python tools/codegen_mgmt_client_stubs.py --write "
        "autopilot_platform/ap/mgmt/client_ops_generated.py"
    )


def test_manifest_matches_live_client_source():
    proc = subprocess.run(
        [sys.executable, str(EXTRACT), "--client", str(CLIENT)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    live = json.loads(proc.stdout)
    on_disk = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert live["operations"] == on_disk["operations"]
