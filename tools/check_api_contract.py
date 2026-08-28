#!/usr/bin/env python3
"""前后端 API 契约巡检（移植自 TestPilot check_api_contract，适配 FastAPI + Vue）。

检查：
1) 前端调用的 /api/v1/* 是否在 Platform 路由中存在；
2) HTTP 方法是否落在后端声明的 methods 内；
3) （信息）后端有、前端 API 层未引用的路径（Runner 协议等可忽略）。

用法：
  .venv/Scripts/python.exe tools/check_api_contract.py
  .venv/Scripts/python.exe tools/check_api_contract.py --fail-backend-only
  .venv/Scripts/python.exe tools/check_api_contract.py --json

退出码：0=前端路径/方法无硬伤；1=有缺失或方法不匹配（或 --fail-backend-only 时有未忽略的后端独占）。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "autopilot_platform" / "platform" / "api"
APP_PY = ROOT / "autopilot_platform" / "platform" / "app.py"
FRONTEND_SRC = ROOT / "autopilot_platform" / "frontend" / "src"
API_PREFIX = "/api/v1"

# Runner / 流式 / 内部协议：管理台前端通常不直接调用
IGNORED_BACKEND_ONLY: set[str] = {
    f"{API_PREFIX}/jobs/claim",
    f"{API_PREFIX}/jobs/<param>/running",
    f"{API_PREFIX}/jobs/<param>/nack",
    f"{API_PREFIX}/jobs/<param>/complete",
    f"{API_PREFIX}/jobs/<param>/report",  # Runner POST 上报；GET 管理台可能用
    f"{API_PREFIX}/jobs/<param>/result",
    f"{API_PREFIX}/jobs/<param>/logs",  # POST 上传日志
    f"{API_PREFIX}/jobs/<param>/logs/stream",
    f"{API_PREFIX}/jobs/<param>/logs/stream-token",
    f"{API_PREFIX}/runners/heartbeat",
    f"{API_PREFIX}/runners/register",
    f"{API_PREFIX}/auth/oidc/callback",
    f"{API_PREFIX}/auth/saml/acs",
    f"{API_PREFIX}/auth/saml/login",
    f"{API_PREFIX}/auth/oidc/login",
    "/health",
}

# 方法允许在这些路径上「前端未声明 POST 但后端有」等时放宽：仅作信息
ROUTER_DECORATOR_RE = re.compile(
    r"@(?:router|public_router)\.(get|post|put|patch|delete)\(\s*(?:[\"']([^\"']+)[\"']|"
    r"\s*[\"']([^\"']+)[\"'])",
    re.IGNORECASE | re.MULTILINE,
)
# 多行：@router.post(\n    "/path"
ROUTER_MULTILINE_RE = re.compile(
    r"@(?:router|public_router)\.(get|post|put|patch|delete)\(\s*\n\s*[\"']([^\"']+)[\"']",
    re.IGNORECASE,
)
APP_ROUTE_RE = re.compile(
    r"@app\.(get|post|put|patch|delete)\(\s*[\"']([^\"']+)[\"']",
    re.IGNORECASE,
)

# api("/api/v1/...") / api(`/api/v1/...${x}`) / sessionFetch(...)
FRONT_CALL_RE = re.compile(
    r"""\b(?:api|sessionFetch)\s*(?:<[^>]*>)?\s*\(\s*([`'"])(/api/v1/[^`'"]*?)\1""",
    re.IGNORECASE,
)
# fetch("/api/v1/...") 裸调用
FRONT_FETCH_RE = re.compile(
    r"""\bfetch\s*\(\s*([`'"])(/api/v1/[^`'"]*?)\1""",
    re.IGNORECASE,
)
METHOD_NEAR_RE = re.compile(
    r"""method\s*:\s*['"]([A-Za-z]+)['"]""",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class RouteDef:
    file: str
    path: str
    methods: frozenset[str]


@dataclass(frozen=True)
class FrontCall:
    file: str
    method: str
    path: str


def _norm_path(path: str) -> str:
    p = path.split("?", 1)[0].strip()
    p = re.sub(r"/\$\{[^}]+}", "/<param>", p)
    p = re.sub(r"\$\{[^}]+}", "", p)  # 查询拼接，非路径段
    p = re.sub(r"\{[^}]+}", "<param>", p)
    p = re.sub(r"<[^>]+>", "<param>", p)
    p = re.sub(r"/+$", "", p) or "/"
    return p


def _strip_front_suffix(path: str) -> str:
    """路径参数保留；查询串模板拼接去掉。"""
    p = path.split("?", 1)[0]
    p = re.sub(r"/\$\{[^}]+}", "/<param>", p)
    p = re.sub(r"\$\{[^}]+}", "", p)
    return p.rstrip("/") or "/"


def parse_backend_routes() -> list[RouteDef]:
    out: list[RouteDef] = []
    files: list[Path] = sorted(API_DIR.glob("*.py"))
    if APP_PY.is_file():
        files.append(APP_PY)

    for py in files:
        if py.name == "__init__.py":
            continue
        text = py.read_text(encoding="utf-8", errors="ignore")
        rel = str(py.relative_to(ROOT)).replace("\\", "/")
        seen: set[tuple[str, str]] = set()

        matches: list[tuple[str, str]] = []
        for m in ROUTER_DECORATOR_RE.finditer(text):
            method = m.group(1).upper()
            path = m.group(2) or m.group(3) or ""
            if path:
                matches.append((method, path))
        for m in ROUTER_MULTILINE_RE.finditer(text):
            matches.append((m.group(1).upper(), m.group(2)))
        if py == APP_PY:
            for m in APP_ROUTE_RE.finditer(text):
                matches.append((m.group(1).upper(), m.group(2)))

        by_path: dict[str, set[str]] = {}
        for method, raw in matches:
            if raw.startswith("/api/"):
                full = raw
            elif raw == "/health" or raw.startswith("/health"):
                full = raw
            else:
                full = f"{API_PREFIX}{raw if raw.startswith('/') else '/' + raw}"
            norm = _norm_path(full)
            by_path.setdefault(norm, set()).add(method)
            seen.add((norm, method))

        for path, methods in by_path.items():
            out.append(RouteDef(file=rel, path=path, methods=frozenset(methods)))
    return out


def _infer_method(text: str, end: int) -> str:
    """仅从本次调用紧随的 options 推断 method，避免吃到下一次 api()。"""
    i = end
    n = len(text)
    while i < n and text[i] in " \t\n\r":
        i += 1
    if i >= n or text[i] != ",":
        return "GET"
    window = text[i : i + 240]
    stop = re.search(r"\b(?:api|sessionFetch|fetch)\s*[<(]", window)
    if stop:
        window = window[: stop.start()]
    m = METHOD_NEAR_RE.search(window)
    if m:
        return m.group(1).upper()
    return "GET"


def parse_frontend_calls(roots: Iterable[Path] | None = None) -> list[FrontCall]:
    roots = list(roots) if roots is not None else [FRONTEND_SRC]
    out: list[FrontCall] = []
    seen: set[tuple[str, str, str]] = set()

    files: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        files.extend(root.rglob("*.ts"))
        files.extend(root.rglob("*.vue"))

    for f in files:
        if "node_modules" in f.parts:
            continue
        text = f.read_text(encoding="utf-8", errors="ignore")
        rel = str(f.relative_to(ROOT)).replace("\\", "/")
        for cre in (FRONT_CALL_RE, FRONT_FETCH_RE):
            for m in cre.finditer(text):
                raw = _strip_front_suffix(m.group(2))
                path = _norm_path(raw)
                if not path.startswith("/api/"):
                    continue
                method = _infer_method(text, m.end())
                key = (rel, method, path)
                if key in seen:
                    continue
                seen.add(key)
                out.append(FrontCall(file=rel, method=method, path=path))
    return out


def compare(
    routes: list[RouteDef],
    calls: list[FrontCall],
) -> dict:
    route_by_path: dict[str, set[str]] = {}
    for r in routes:
        route_by_path.setdefault(r.path, set()).update(r.methods)

    path_missing: list[FrontCall] = []
    method_mismatch: list[tuple[FrontCall, set[str]]] = []
    frontend_paths: set[str] = set()

    for c in calls:
        frontend_paths.add(c.path)
        allowed = route_by_path.get(c.path)
        if allowed is None:
            path_missing.append(c)
            continue
        if c.method not in allowed:
            method_mismatch.append((c, allowed))

    backend_only: list[RouteDef] = []
    for r in routes:
        if r.path in IGNORED_BACKEND_ONLY:
            continue
        if r.path not in frontend_paths:
            backend_only.append(r)

    return {
        "routes": len(routes),
        "calls": len(calls),
        "path_missing": path_missing,
        "method_mismatch": method_mismatch,
        "backend_only": backend_only,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Platform 前后端 API 契约巡检")
    ap.add_argument(
        "--fail-backend-only",
        action="store_true",
        help="后端独占路由（未忽略）也视为失败",
    )
    ap.add_argument("--json", action="store_true", help="JSON 输出")
    args = ap.parse_args(argv)

    routes = parse_backend_routes()
    calls = parse_frontend_calls()
    result = compare(routes, calls)

    path_missing: list[FrontCall] = result["path_missing"]
    method_mismatch: list[tuple[FrontCall, set[str]]] = result["method_mismatch"]
    backend_only: list[RouteDef] = result["backend_only"]

    if args.json:
        payload = {
            "routes": result["routes"],
            "calls": result["calls"],
            "path_missing": [asdict(c) for c in path_missing],
            "method_mismatch": [
                {"call": asdict(c), "allowed": sorted(a)} for c, a in method_mismatch
            ],
            "backend_only": [
                {"file": r.file, "path": r.path, "methods": sorted(r.methods)}
                for r in sorted(backend_only, key=lambda x: x.path)
            ],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print("== API Contract Check (Autopilot-Platform) ==")
        print(f"Backend routes: {result['routes']}")
        print(f"Frontend calls: {result['calls']}")
        print()
        if not path_missing and not method_mismatch:
            print("OK: no path/method mismatches on frontend calls.")
            print()
        if path_missing:
            print("[Path missing in backend]")
            for c in path_missing:
                print(f"- {c.file}: {c.method} {c.path}")
            print()
        if method_mismatch:
            print("[Method mismatch]")
            for c, exp in method_mismatch:
                print(f"- {c.file}: {c.method} {c.path} (allowed: {','.join(sorted(exp))})")
            print()
        if backend_only:
            print("[Backend routes not referenced by frontend (informational)]")
            for r in sorted(backend_only, key=lambda x: x.path):
                print(f"- {r.file}: {','.join(sorted(r.methods))} {r.path}")
            print()

    hard_fail = bool(path_missing or method_mismatch)
    if args.fail_backend_only and backend_only:
        hard_fail = True
    return 1 if hard_fail else 0


if __name__ == "__main__":
    # Windows 控制台
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (OSError, ValueError, AttributeError):
        pass
    raise SystemExit(main())
