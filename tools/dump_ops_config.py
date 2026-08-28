#!/usr/bin/env python3
"""只读导出 / 查看运维配置中心（改造自 TestPilot query_config_center）。

默认走 HTTP（密钥已掩码）；``--export`` 调用 /ops/config/export（需平台运维账号）。

用法：
  .venv/Scripts/python.exe tools/dump_ops_config.py
  .venv/Scripts/python.exe tools/dump_ops_config.py --category vector_rag
  .venv/Scripts/python.exe tools/dump_ops_config.py --export -o ops_export.json
  .venv/Scripts/python.exe tools/dump_ops_config.py --providers

环境变量：AP_SMOKE_BASE_URL / AP_SMOKE_USER / AP_SMOKE_PASSWORD
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.smoke_http import DEFAULT_BASE, SmokeContext, _request  # noqa: E402


def login(ctx: SmokeContext) -> None:
    code, body, _ = _request(
        ctx,
        "POST",
        "/api/v1/auth/login",
        body={"username": ctx.user, "password": ctx.password},
        auth=False,
    )
    if code != 200 or not isinstance(body, dict) or not body.get("access_token"):
        raise SystemExit(f"login failed: status={code} body={body!r}")
    ctx.token = str(body["access_token"])


def _print_json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def filter_by_category(payload: dict[str, Any], category: str) -> dict[str, Any]:
    cat = (category or "").strip()
    if not cat:
        return payload
    cats = payload.get("categories") or payload.get("groups") or []
    if isinstance(cats, list):
        matched = [
            c
            for c in cats
            if isinstance(c, dict)
            and (
                str(c.get("id") or "") == cat
                or str(c.get("name") or "") == cat
                or cat.lower() in str(c.get("id") or "").lower()
            )
        ]
        out = dict(payload)
        out["categories"] = matched
        # 若 values 带分类前缀，尽量收窄
        values = payload.get("values") or payload.get("effective") or {}
        if isinstance(values, dict) and matched:
            keys: set[str] = set()
            for c in matched:
                for k in c.get("keys") or c.get("fields") or []:
                    if isinstance(k, str):
                        keys.add(k)
                    elif isinstance(k, dict) and k.get("key"):
                        keys.add(str(k["key"]))
            if keys:
                out["values"] = {k: v for k, v in values.items() if k in keys}
        return out
    return payload


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="导出 / 查看 Platform 运维配置")
    ap.add_argument("--base-url", default=DEFAULT_BASE)
    ap.add_argument("--user", default=os.environ.get("AP_SMOKE_USER", "admin"))
    ap.add_argument("--password", default=os.environ.get("AP_SMOKE_PASSWORD", "admin"))
    ap.add_argument("--category", default="", help="仅显示某分类（如 vector_rag / ai）")
    ap.add_argument("--providers", action="store_true", help="只拉 AI providers")
    ap.add_argument("--export", action="store_true", help="调用 /ops/config/export（运维）")
    ap.add_argument("-o", "--output", default="", help="写入 JSON 文件")
    args = ap.parse_args(argv)

    ctx = SmokeContext(base_url=args.base_url.rstrip("/"), user=args.user, password=args.password)
    login(ctx)

    if args.providers:
        code, body, _ = _request(ctx, "GET", "/api/v1/ops/config/ai-providers")
    elif args.export:
        code, body, _ = _request(ctx, "GET", "/api/v1/ops/config/export")
    else:
        code, body, _ = _request(ctx, "GET", "/api/v1/ops/config")

    if code != 200:
        print(f"HTTP {code}")
        _print_json(body)
        return 1

    if isinstance(body, dict) and args.category and not args.providers:
        body = filter_by_category(body, args.category)

    if args.output:
        Path(args.output).write_text(
            json.dumps(body, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"written {args.output}")
    else:
        _print_json(body)
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError, ValueError):
        pass
    raise SystemExit(main())
