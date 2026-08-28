#!/usr/bin/env python3
"""对已启动的 Platform 做 HTTP 冒烟（移植自 TestPilot check_system，适配 /api/v1）。

不替代 pytest；用于部署后 / 本地起服后的探活。

用法：
  .venv/Scripts/python.exe tools/smoke_http.py
  .venv/Scripts/python.exe tools/smoke_http.py --base-url http://127.0.0.1:8000
  .venv/Scripts/python.exe tools/smoke_http.py --smoke
  .venv/Scripts/python.exe tools/smoke_http.py --module auth,projects
  .venv/Scripts/python.exe tools/smoke_http.py --user admin --password admin

环境变量：
  AP_SMOKE_BASE_URL / AP_SMOKE_USER / AP_SMOKE_PASSWORD
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any


DEFAULT_BASE = os.environ.get("AP_SMOKE_BASE_URL", "http://127.0.0.1:8000").rstrip("/")


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str = ""
    skipped: bool = False
    ms: float = 0.0


@dataclass
class SmokeContext:
    base_url: str
    user: str
    password: str
    token: str = ""
    results: list[CheckResult] = field(default_factory=list)

    def headers(self, auth: bool = True) -> dict[str, str]:
        h = {"Accept": "application/json", "Content-Type": "application/json"}
        if auth and self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h


def _request(
    ctx: SmokeContext,
    method: str,
    path: str,
    *,
    body: dict[str, Any] | None = None,
    auth: bool = True,
    timeout: float = 8.0,
) -> tuple[int, Any, float]:
    url = f"{ctx.base_url}{path}"
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers=ctx.headers(auth=auth),
        method=method.upper(),
    )
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            ms = (time.perf_counter() - t0) * 1000
            if not raw:
                return resp.status, None, ms
            try:
                return resp.status, json.loads(raw), ms
            except json.JSONDecodeError:
                return resp.status, raw, ms
    except urllib.error.HTTPError as e:
        ms = (time.perf_counter() - t0) * 1000
        raw = e.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            payload = raw
        return e.code, payload, ms
    except (OSError, TimeoutError, ValueError, TypeError, urllib.error.URLError) as e:
        raise RuntimeError(f"{method} {path}: {e}") from e


def _record(ctx: SmokeContext, name: str, ok: bool, detail: str = "", *, skipped: bool = False, ms: float = 0.0) -> bool:
    ctx.results.append(CheckResult(name=name, ok=ok, detail=detail, skipped=skipped, ms=ms))
    flag = "SKIP" if skipped else ("OK" if ok else "FAIL")
    extra = f" ({detail})" if detail else ""
    print(f"  [{flag}] {name}{extra}" + (f" {ms:.0f}ms" if ms else ""))
    return ok or skipped


def check_health(ctx: SmokeContext) -> bool:
    try:
        code, body, ms = _request(ctx, "GET", "/health", auth=False)
    except RuntimeError as e:
        return _record(ctx, "health", False, str(e))
    ok = code == 200
    return _record(ctx, "health", ok, f"status={code}", ms=ms)


def check_login(ctx: SmokeContext) -> bool:
    try:
        code, body, ms = _request(
            ctx,
            "POST",
            "/api/v1/auth/login",
            body={"username": ctx.user, "password": ctx.password},
            auth=False,
        )
    except RuntimeError as e:
        return _record(ctx, "auth.login", False, str(e))
    if code != 200 or not isinstance(body, dict):
        return _record(ctx, "auth.login", False, f"status={code} body={body!r}", ms=ms)
    token = str(body.get("access_token") or "").strip()
    if not token:
        return _record(ctx, "auth.login", False, "missing access_token", ms=ms)
    ctx.token = token
    return _record(ctx, "auth.login", True, f"user={body.get('user', {}).get('username', ctx.user)}", ms=ms)


def check_me(ctx: SmokeContext) -> bool:
    if not ctx.token:
        return _record(ctx, "auth.me", False, "no token", skipped=True)
    try:
        code, body, ms = _request(ctx, "GET", "/api/v1/auth/me")
    except RuntimeError as e:
        return _record(ctx, "auth.me", False, str(e))
    ok = code == 200 and isinstance(body, dict)
    return _record(ctx, "auth.me", ok, f"status={code}", ms=ms)


def check_projects(ctx: SmokeContext) -> bool:
    if not ctx.token:
        return _record(ctx, "projects.list", False, "no token", skipped=True)
    try:
        code, body, ms = _request(ctx, "GET", "/api/v1/projects")
    except RuntimeError as e:
        return _record(ctx, "projects.list", False, str(e))
    ok = code == 200 and isinstance(body, list)
    n = len(body) if isinstance(body, list) else 0
    return _record(ctx, "projects.list", ok, f"status={code} count={n}", ms=ms)


def check_jobs(ctx: SmokeContext) -> bool:
    if not ctx.token:
        return _record(ctx, "jobs.list", False, "no token", skipped=True)
    try:
        code, body, ms = _request(ctx, "GET", "/api/v1/jobs")
    except RuntimeError as e:
        return _record(ctx, "jobs.list", False, str(e))
    ok = code == 200 and isinstance(body, list)
    return _record(ctx, "jobs.list", ok, f"status={code}", ms=ms)


def check_ops_summary(ctx: SmokeContext) -> bool:
    """普通用户可能 403，仍视为探活成功（服务可达）。"""
    if not ctx.token:
        return _record(ctx, "ops.summary", False, "no token", skipped=True)
    try:
        code, _body, ms = _request(ctx, "GET", "/api/v1/ops/summary")
    except RuntimeError as e:
        return _record(ctx, "ops.summary", False, str(e))
    ok = code in (200, 403)
    return _record(ctx, "ops.summary", ok, f"status={code}", ms=ms)


def check_design_stats(ctx: SmokeContext) -> bool:
    if not ctx.token:
        return _record(ctx, "design.stats", False, "no token", skipped=True)
    try:
        code, _body, ms = _request(ctx, "GET", "/api/v1/design/stats")
    except RuntimeError as e:
        return _record(ctx, "design.stats", False, str(e))
    ok = code in (200, 400, 403, 422)  # 缺 project 也可能 4xx，但路由应存在
    return _record(ctx, "design.stats", ok, f"status={code}", ms=ms)


MODULES: dict[str, list] = {
    "core": [check_health],
    "auth": [check_login, check_me],
    "projects": [check_projects],
    "jobs": [check_jobs],
    "ops": [check_ops_summary],
    "design": [check_design_stats],
}

SMOKE_ORDER = ["core", "auth", "projects", "jobs"]
FULL_ORDER = ["core", "auth", "projects", "jobs", "ops", "design"]


def run(modules: list[str], ctx: SmokeContext) -> int:
    print(f"== Platform HTTP smoke @ {ctx.base_url} ==")
    print(f"modules: {', '.join(modules)}")
    # auth 依赖 login；若选了需 token 的模块却未含 auth，自动插入
    need_auth = any(m in modules for m in ("projects", "jobs", "ops", "design", "auth"))
    ordered: list[str] = []
    if "core" in modules:
        ordered.append("core")
    if need_auth and "auth" not in modules:
        ordered.append("auth")
    for m in modules:
        if m not in ordered:
            ordered.append(m)

    for mod in ordered:
        fns = MODULES.get(mod)
        if not fns:
            print(f"  [SKIP] unknown module {mod}")
            continue
        print(f"\n-- {mod} --")
        for fn in fns:
            fn(ctx)

    failed = [r for r in ctx.results if not r.ok and not r.skipped]
    skipped = [r for r in ctx.results if r.skipped]
    print()
    print(
        f"summary: {len(ctx.results) - len(failed) - len(skipped)} ok, "
        f"{len(failed)} fail, {len(skipped)} skip"
    )
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Autopilot-Platform HTTP 冒烟")
    ap.add_argument("--base-url", default=DEFAULT_BASE)
    ap.add_argument("--user", default=os.environ.get("AP_SMOKE_USER", "admin"))
    ap.add_argument("--password", default=os.environ.get("AP_SMOKE_PASSWORD", "admin"))
    ap.add_argument("--smoke", action="store_true", help="仅 core+auth+projects+jobs")
    ap.add_argument(
        "--module",
        default="",
        help="逗号分隔：core,auth,projects,jobs,ops,design",
    )
    args = ap.parse_args(argv)

    if args.module.strip():
        modules = [m.strip() for m in args.module.split(",") if m.strip()]
    elif args.smoke:
        modules = list(SMOKE_ORDER)
    else:
        modules = list(FULL_ORDER)

    ctx = SmokeContext(base_url=args.base_url.rstrip("/"), user=args.user, password=args.password)
    try:
        return run(modules, ctx)
    except KeyboardInterrupt:
        print("interrupted")
        return 130


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError, ValueError):
        pass
    raise SystemExit(main())
