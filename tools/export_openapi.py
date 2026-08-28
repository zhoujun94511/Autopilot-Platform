#!/usr/bin/env python3
"""导出 Platform OpenAPI JSON（AUD-2026-11 / ARCH-002 codegen 前置）。

用法::
  .venv/Scripts/python.exe tools/export_openapi.py
  .venv/Scripts/python.exe tools/export_openapi.py --out docs/openapi.json

默认同时写入：
  - docs/openapi.v1.json（文档/浏览）
  - contracts/openapi/openapi.v1.json（契约权威，供 CI / IDE 对齐）
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "docs" / "openapi.v1.json"
CONTRACT_OUT = ROOT / "contracts" / "openapi" / "openapi.v1.json"


def export_openapi(*, database_url: str | None = None) -> dict:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    os.environ.setdefault("MC_ADMIN_USER", "admin")
    os.environ.setdefault("MC_ADMIN_PASSWORD", "admin")
    os.environ.setdefault("MC_SCHEDULE_ENABLED", "0")
    if database_url:
        os.environ["MC_DATABASE_URL"] = database_url
    from autopilot_platform.platform.app import create_app

    db = database_url or f"sqlite:///{Path(tempfile.mkdtemp()) / 'openapi_export.db'}"
    app = create_app(database_url=db)
    return app.openapi()


def _write_spec(spec: dict, out: Path, *, pretty: bool) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(spec, ensure_ascii=False, indent=2 if pretty else None)
    out.write_text(payload + ("\n" if pretty else ""), encoding="utf-8")
    paths = len(spec.get("paths", {}))
    print(f"[export_openapi] wrote {out} ({paths} paths)")


def _canonical(spec: dict) -> str:
    """稳定序列化，供契约 diff（忽略键序 / 空白差异）。"""
    return json.dumps(spec, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def check_contract(*, contract_path: Path | None = None) -> int:
    """AUD-2026-11：现场 OpenAPI 须与已提交契约一致（不写盘）。"""
    path = contract_path or CONTRACT_OUT
    if not path.is_file():
        print(
            f"[export_openapi] MISSING contract {path}\n"
            "  Run: python tools/export_openapi.py --pretty",
            file=sys.stderr,
        )
        return 1
    try:
        committed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[export_openapi] invalid contract {path}: {exc}", file=sys.stderr)
        return 1
    live = export_openapi()
    if _canonical(committed) != _canonical(live):
        live_paths = len(live.get("paths") or {})
        old_paths = len(committed.get("paths") or {})
        print(
            f"[export_openapi] DRIFT: {path} is stale "
            f"(committed paths={old_paths}, live paths={live_paths}).\n"
            "  Re-export and commit:\n"
            "    python tools/export_openapi.py --pretty",
            file=sys.stderr,
        )
        return 1
    print(f"[export_openapi] OK contract in sync ({path}, {len(live.get('paths') or {})} paths)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export Platform OpenAPI JSON")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="主输出路径")
    parser.add_argument(
        "--no-contract",
        action="store_true",
        help="不写入 contracts/openapi/openapi.v1.json",
    )
    parser.add_argument("--pretty", action="store_true", help="缩进格式化")
    parser.add_argument(
        "--check",
        action="store_true",
        help="仅校验 contracts/openapi/openapi.v1.json 与现场一致（AUD-2026-11）",
    )
    args = parser.parse_args(argv)

    if args.check:
        return check_contract()

    spec = export_openapi()
    _write_spec(spec, Path(args.out), pretty=args.pretty)
    if not args.no_contract:
        # 显式 --out 指向契约路径时避免写两次
        if Path(args.out).resolve() != CONTRACT_OUT.resolve():
            _write_spec(spec, CONTRACT_OUT, pretty=args.pretty)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
