#!/usr/bin/env python3
"""审计 capability_registry 与 OpenAPI / 导出 JSON 是否一致。

用法::
  .venv/Scripts/python.exe tools/audit_capability_routes.py
  .venv/Scripts/python.exe tools/audit_capability_routes.py --openapi docs/openapi.v1.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OPENAPI = ROOT / "docs" / "openapi.v1.json"


def _normalize(path: str) -> str:
    return re.sub(r"\{[^}]+}", "{param}", path)


def _load_openapi(path: Path) -> set[tuple[str, str]]:
    spec = json.loads(path.read_text(encoding="utf-8"))
    out: set[tuple[str, str]] = set()
    for p, methods in spec.get("paths", {}).items():
        for m in methods:
            if m.upper() in ("GET", "POST", "PUT", "PATCH", "DELETE"):
                out.add((m.upper(), _normalize(p)))
    return out


def audit(openapi_path: Path) -> list[str]:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from autopilot_platform.platform.tenancy.capability_registry import (
        CAPABILITY_IDS,
        CAPABILITY_ROUTE_BINDINGS,
    )

    errors: list[str] = []
    if not openapi_path.is_file():
        return [f"OpenAPI 文件不存在: {openapi_path}（先运行 tools/export_openapi.py）"]

    paths = _load_openapi(openapi_path)
    for b in CAPABILITY_ROUTE_BINDINGS:
        if b.capability_id not in CAPABILITY_IDS:
            errors.append(f"未知 capability_id: {b.capability_id}")
        key = (b.method, _normalize(b.path))
        if key not in paths:
            errors.append(f"OpenAPI 缺失路由: {b.method} {b.path} ({b.capability_id})")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit RBAC capability route bindings")
    parser.add_argument("--openapi", default=str(DEFAULT_OPENAPI))
    args = parser.parse_args(argv)
    errs = audit(Path(args.openapi))
    if errs:
        for e in errs:
            print(f"ERROR: {e}", file=sys.stderr)
        return 1
    print(f"[audit_capability_routes] OK — {Path(args.openapi).name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
