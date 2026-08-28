"""校验 Platform 内嵌 ap 版本与 contracts/RUNTIME_PIN 是否对齐。

公开契约 ``contracts/runtime_contract.json`` 的 ``runtime_version`` 为 canonical
semver（不加 ``-vendored``）；本脚本只检查包装层 pin ↔ ``ap.__version__``。

用法:
  .venv/Scripts/python.exe tools/check_ap_version.py
退出码: 0=对齐, 1=不齐或缺失。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    pin_path = ROOT / "contracts" / "RUNTIME_PIN"
    contract_path = ROOT / "contracts" / "runtime_contract.json"
    pin = ""
    if pin_path.is_file():
        pin = pin_path.read_text(encoding="utf-8").strip().splitlines()[0].strip()
    contract_rv = ""
    if contract_path.is_file():
        import json

        contract_rv = str(
            json.loads(contract_path.read_text(encoding="utf-8")).get("runtime_version")
            or ""
        ).strip()
    try:
        from autopilot_platform.ap import __version__ as ap_ver
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: cannot import ap: {exc}")
        return 1
    ap_ver = str(ap_ver or "").strip()
    print(f"contract.runtime_version = {contract_rv or '(missing)'}")
    print(f"ap.__version__           = {ap_ver}")
    print(f"RUNTIME_PIN              = {pin or '(missing)'}")
    if contract_rv and "-" in contract_rv:
        print(
            "FAIL: public contract runtime_version must be canonical semver "
            "(no -vendored); keep suffix only on ap/RUNTIME_PIN"
        )
        return 1
    if not pin:
        print("FAIL: contracts/RUNTIME_PIN missing")
        return 1
    if pin != ap_ver:
        print("FAIL: pin mismatch — update ap/ or RUNTIME_PIN")
        return 1
    print("OK: runtime pin matches ap")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
