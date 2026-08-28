#!/usr/bin/env python3
"""从 MgmtClient 源码提取 HTTP 操作清单（ARCH-002 codegen 前置真源）。

用法::
  python tools/extract_mgmt_client_ops.py
  python tools/extract_mgmt_client_ops.py --write contracts/mgmt_client_ops.json
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CLIENT = ROOT / "autopilot_platform" / "ap" / "mgmt" / "client.py"
DEFAULT_OUT = ROOT / "contracts" / "mgmt_client_ops.json"

_HTTP_CALL = re.compile(
    r'self\._client\.(get|post|put|patch|delete)\(\s*f?"([^"]+)"',
    re.IGNORECASE,
)


def _normalize_path(path: str) -> str:
    return re.sub(r"\{[a-zA-Z_][a-zA-Z0-9_]*}", "{param}", path.strip())


def extract_ops(client_path: Path) -> list[dict[str, str]]:
    text = client_path.read_text(encoding="utf-8")
    seen: set[tuple[str, str]] = set()
    ops: list[dict[str, str]] = []
    for m in _HTTP_CALL.finditer(text):
        method = m.group(1).upper()
        path = _normalize_path(m.group(2))
        key = (method, path)
        if key in seen:
            continue
        seen.add(key)
        ops.append({"method": method, "path": path})
    ops.sort(key=lambda x: (x["path"], x["method"]))
    return ops


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract MgmtClient HTTP ops")
    parser.add_argument("--client", default=str(DEFAULT_CLIENT))
    parser.add_argument("--write", default="", help="写入 JSON（默认 stdout）")
    args = parser.parse_args(argv)

    ops = extract_ops(Path(args.client))
    payload = {"schema_version": 1, "operations": ops}
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.write:
        out = Path(args.write)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(f"[extract_mgmt_client_ops] wrote {out} ({len(ops)} ops)")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
