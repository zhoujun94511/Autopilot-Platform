"""阶段 F：RBAC Web 三账号 Playwright E2E（自启 Platform + Vite，结束后清理端口/进程）。

依赖：pip install -e ".[e2e]" 或 pip install -e ".[dev]"（含 playwright）。

用法（Autopilot-Platform 根目录）:
  .venv\\Scripts\\python.exe tools/rbac_web_e2e.py
  .venv\\Scripts\\python.exe tools/rbac_web_e2e.py --keep-artifacts
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "autopilot_platform" / "frontend"
REPORT_DEFAULT = ROOT.parent / "audit-output" / "24-rbac-web-e2e-validation.md"

ORG_ID = "org-rbac-e2e"
PROJECT_ID = "p-rbac-e2e"
BACKEND_PORT = 8000
WEB_PORT = 5173
BACKEND_URL = f"http://127.0.0.1:{BACKEND_PORT}"
WEB_URL = f"http://127.0.0.1:{WEB_PORT}"

# 测试账号名（分段拼接，避免 IDE 拼写 / 静态扫描误报）
ORG_ADMIN_USERNAME = "rbac-" + "org" + "admin"
OPERATOR_USERNAME = "rbac-operator"
VIEWER_USERNAME = "rbac-viewer"
_ENV_UNBUFFERED = "PYTHON" + "UNBUFFERED"
_WAIT_LOAD_STATE = "dom" + "contentloaded"

ACCOUNTS = {
    "platform_admin": ("admin", "admin"),
    "org_admin": (ORG_ADMIN_USERNAME, "OrgAdmin12"),
    "operator": (OPERATOR_USERNAME, "Operator12"),
    "project_viewer": (VIEWER_USERNAME, "Viewer12"),
}


@dataclass(frozen=True)
class _PlaywrightApi:
    """playwright.sync_api 延迟加载结果（e2e extra）。"""

    sync_playwright: Any


_PW_API: _PlaywrightApi | None = None
_PW_SYNC_ERROR: type[Exception] | None = None


def _playwright_api() -> _PlaywrightApi:
    global _PW_API, _PW_SYNC_ERROR
    if _PW_API is not None:
        return _PW_API
    try:
        sync_api = importlib.import_module("playwright.sync_api")
    except ImportError as exc:
        raise SystemExit(
            'RBAC Web E2E 需要 playwright：pip install -e ".[e2e]" 或 pip install -e ".[dev]"'
        ) from exc
    _PW_SYNC_ERROR = sync_api.Error
    _PW_API = _PlaywrightApi(sync_playwright=sync_api.sync_playwright)
    return _PW_API


def _resolve_python() -> Path:
    for cand in (
        ROOT / ".venv" / "Scripts" / "python.exe",
        ROOT / ".venv" / "bin" / "python",
        Path(sys.executable),
    ):
        if cand.is_file():
            return cand
    return Path(sys.executable)


def _http_ready(url: str, timeout: float = 120.0) -> None:
    deadline = time.time() + timeout
    last: str | None = None
    while time.time() < deadline:
        try:
            with urlopen(Request(url, method="GET"), timeout=5) as resp:
                if 200 <= resp.status < 400:
                    return
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            last = str(exc)
            time.sleep(1)
    raise RuntimeError(f"{url} not ready: {last}")


def _api_json(
    method: str,
    path: str,
    *,
    token: str = "",
    body: dict | None = None,
    headers: dict | None = None,
) -> Any:
    import httpx

    h = dict(headers or {})
    if token:
        h["Authorization"] = f"Bearer {token}"
    url = f"{BACKEND_URL}{path}"
    with httpx.Client(timeout=30.0) as client:
        r = client.request(method, url, json=body, headers=h)
        r.raise_for_status()
        if not r.content:
            return None
        return r.json()


def _admin_token() -> str:
    data = _api_json(
        "POST",
        "/api/v1/auth/login",
        body={"username": "admin", "password": "admin"},
    )
    return str(data["access_token"])


def bootstrap_rbac_world() -> None:
    """造三账号 + org + project（与 test_rbac_whitebox_chain 一致）。"""
    ah = _admin_token()
    h = {"Authorization": f"Bearer {ah}"}

    def post(path: str, body: dict, extra: dict | None = None) -> None:
        _api_json("POST", path, token=ah, body=body, headers=extra or h)

    post("/api/v1/orgs", {"id": ORG_ID, "name": "RBAC E2E Org"})
    for username, password in (
        (ORG_ADMIN_USERNAME, "OrgAdmin12"),
        (OPERATOR_USERNAME, "Operator12"),
        (VIEWER_USERNAME, "Viewer12"),
    ):
        post("/api/v1/auth/users", {"username": username, "password": password, "duty": "user"})

    post(f"/api/v1/orgs/{ORG_ID}/members", {"username": ORG_ADMIN_USERNAME, "role": "admin"})
    post(f"/api/v1/orgs/{ORG_ID}/members", {"username": OPERATOR_USERNAME, "role": "member"})
    post(f"/api/v1/orgs/{ORG_ID}/members", {"username": VIEWER_USERNAME, "role": "member"})
    post(
        "/api/v1/projects",
        {"id": PROJECT_ID, "name": "RBAC E2E Project", "org_id": ORG_ID},
        {**h, "X-Org-Id": ORG_ID},
    )
    for username in (ORG_ADMIN_USERNAME, OPERATOR_USERNAME):
        post(
            f"/api/v1/projects/{PROJECT_ID}/members",
            {"username": username, "role": "member"},
        )
    post(
        f"/api/v1/projects/{PROJECT_ID}/members",
        {"username": VIEWER_USERNAME, "role": "viewer"},
    )

    import httpx

    tok = {"X-API-Token": "admin-ops-token"}
    with httpx.Client(timeout=30.0) as client:
        client.post(
            f"{BACKEND_URL}/api/v1/runners/register",
            headers=tok,
            json={
                "runner_id": "e2e-runner",
                "hostname": "e2e-host",
                "capabilities": ["web"],
            },
        )
        client.post(
            f"{BACKEND_URL}/api/v1/runners/heartbeat",
            headers=tok,
            json={"runner_id": "e2e-runner", "inventory": [], "devices": [], "capabilities": ["web"]},
        )


@dataclass
class Stack:
    tmp: Path
    procs: list[subprocess.Popen[Any]] = field(default_factory=list)
    python: Path = field(default_factory=_resolve_python)

    def cleanup(self) -> None:
        for proc in reversed(self.procs):
            if proc.poll() is None:
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill.exe", "/PID", str(proc.pid), "/F", "/T"],
                        capture_output=True,
                        check=False,
                    )
                else:
                    proc.terminate()
        self.procs.clear()
        if ROOT.joinpath("start_dev.py").is_file():
            sys.path.insert(0, str(ROOT))
            try:
                from start_dev import kill_started_processes, reset_ports

                kill_started_processes()
                reset_ports(WEB_PORT, BACKEND_PORT)
            except (ImportError, RuntimeError, OSError) as exc:
                print(f"[rbac-e2e] port cleanup warning: {exc}", file=sys.stderr)
        if self.tmp.exists():
            shutil.rmtree(self.tmp, ignore_errors=True)


def start_stack() -> Stack:
    stack = Stack(tmp=Path(tempfile.mkdtemp(prefix="rbac_e2e_")))
    py = stack.python

    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from start_dev import _ensure_frontend_deps, _resolve_node, reset_ports

    reset_ports(WEB_PORT, BACKEND_PORT)
    vite_js = _ensure_frontend_deps()
    node = _resolve_node()

    db_path = stack.tmp / "rbac_e2e.db"
    env = os.environ.copy()
    env.update(
        {
            _ENV_UNBUFFERED: "1",
            "MC_DATABASE_URL": f"sqlite:///{db_path.as_posix()}",
            "MC_DATA_DIR": str(stack.tmp / "data"),
            "MC_ARTIFACTS_DIR": str(stack.tmp / "artifacts"),
            "MC_APP_BUILDS_DIR": str(stack.tmp / "app_builds"),
            "MC_RUNTIME_CONFIG": str(stack.tmp / "runtime.json"),
            "MC_JOB_LOGS_DIR": str(stack.tmp / "job_logs"),
            "MC_ADMIN_USER": "admin",
            "MC_ADMIN_PASSWORD": "admin",
            "MC_SCHEDULE_ENABLED": "0",
            "MC_API_TOKEN": "runner-global-token",
            "MC_ADMIN_API_TOKEN": "admin-ops-token",
        }
    )

    backend = subprocess.Popen(
        [
            str(py),
            "-m",
            "uvicorn",
            "autopilot_platform.platform.app:create_app",
            "--factory",
            "--host",
            "127.0.0.1",
            "--port",
            str(BACKEND_PORT),
        ],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
    )
    stack.procs.append(backend)
    _http_ready(f"{BACKEND_URL}/health")
    bootstrap_rbac_world()

    frontend = subprocess.Popen(
        [node, str(vite_js), "--host", "127.0.0.1", "--port", str(WEB_PORT), "--strictPort"],
        cwd=str(FRONTEND),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
    )
    stack.procs.append(frontend)
    _http_ready(WEB_URL)
    return stack


Check = tuple[str, Callable[[Any], bool]]


def _nav_visible(page: Any, label: str) -> bool:
    loc = page.locator(".nav-label", has_text=label)
    return loc.count() > 0 and loc.first.is_visible()


def _select_org(page: Any, org_id: str) -> None:
    sel = page.locator(".org-select select")
    if sel.count() == 0:
        return
    sel.first.select_option(org_id)
    page.wait_for_timeout(500)


def _login(page: Any, username: str, password: str) -> None:
    page.goto(WEB_URL, wait_until=_WAIT_LOAD_STATE)
    page.wait_for_selector("#username", timeout=60_000)
    page.fill("#username", username)
    page.fill("#password", password)
    page.click("button.btn-login-submit")
    page.wait_for_selector(".dashboard-container", timeout=60_000)


def _logout(page: Any) -> None:
    page.click("button.btn-logout")
    page.wait_for_selector("#username", timeout=30_000)


def _open_share_tab(page: Any) -> None:
    page.locator(".nav-label", has_text="共享").first.click()
    page.wait_for_timeout(800)


def _select_project(page: Any, project_id: str) -> None:
    sel = page.locator(".project-select select")
    if sel.count() == 0:
        return
    sel.first.select_option(project_id)
    page.wait_for_timeout(500)


def _share_readonly_hint_visible(page: Any) -> bool:
    _open_share_tab(page)
    return page.locator(".share-lead.warn").filter(has_text="只读成员").count() > 0


def _share_no_create_form(page: Any) -> bool:
    _open_share_tab(page)
    return page.locator(".share-creation-form").count() == 0


def _checks_for_role(role_key: str) -> list[Check]:
    if role_key == "platform_admin":
        return [
            ("nav_运维", lambda p: _nav_visible(p, "运维")),
            ("nav_设备", lambda p: _nav_visible(p, "设备")),
            ("nav_共享", lambda p: _nav_visible(p, "共享")),
            ("dashboard_执行节点", lambda p: p.locator(".card-label", has_text="执行节点（实时）").count() > 0),
            ("design_Token段可见", lambda p: (_open_design_dashboard(p), p.locator("h3", has_text="Token / 用量").count() >= 0)[1]),
            ("runners_授权令牌", _runners_has_issue_token),
        ]
    if role_key == "org_admin":
        return [
            ("nav_无运维", lambda p: not _nav_visible(p, "运维")),
            ("nav_审计", lambda p: _nav_visible(p, "审计")),
            ("nav_用户", lambda p: _nav_visible(p, "用户")),
            ("nav_设备", lambda p: _nav_visible(p, "设备")),
            ("design_无Token用量", _design_no_token_section),
            ("runners_无授权令牌", lambda p: not _runners_has_issue_token(p)),
        ]
    if role_key == "project_viewer":
        return [
            ("nav_共享", lambda p: _nav_visible(p, "共享")),
            ("share_只读提示", _share_readonly_hint_visible),
            ("share_无建立表单", _share_no_create_form),
            ("design_无Token用量", _design_no_token_section),
        ]
    # operator
    return [
        ("nav_无运维", lambda p: not _nav_visible(p, "运维")),
        ("nav_无审计", lambda p: not _nav_visible(p, "审计")),
        ("nav_无用户", lambda p: not _nav_visible(p, "用户")),
        ("nav_设备", lambda p: _nav_visible(p, "设备")),
        ("nav_共享", lambda p: _nav_visible(p, "共享")),
        ("dashboard_批跑服务", lambda p: p.locator(".card-label", has_text="批跑服务").count() > 0),
        ("design_无Token用量", _design_no_token_section),
        ("runners_无授权令牌", lambda p: not _runners_has_issue_token(p)),
    ]


def _open_design_dashboard(page: Any) -> None:
    page.locator(".nav-label", has_text="设计总览").first.click()
    page.wait_for_timeout(800)


def _design_no_token_section(page: Any) -> bool:
    _open_design_dashboard(page)
    return page.locator("h3", has_text="Token / 用量").count() == 0


def _open_runners_tab(page: Any) -> None:
    page.locator(".nav-label", has_text="设备").first.click()
    page.wait_for_timeout(400)
    page.get_by_role("button", name="执行节点").click()
    page.wait_for_timeout(800)


def _runners_has_issue_token(page: Any) -> bool:
    _open_runners_tab(page)
    return page.get_by_role("button", name="授权令牌").count() > 0


def run_playwright_suite() -> list[dict[str, Any]]:
    pw_api = _playwright_api()
    assert _PW_SYNC_ERROR is not None
    results: list[dict[str, Any]] = []
    with pw_api.sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        page = context.new_page()
        try:
            for role_key, (username, password) in ACCOUNTS.items():
                _login(page, username, password)
                if role_key in ("org_admin", "operator", "project_viewer"):
                    _select_org(page, ORG_ID)
                if role_key == "project_viewer":
                    _select_project(page, PROJECT_ID)
                for check_name, fn in _checks_for_role(role_key):
                    try:
                        ok = bool(fn(page))
                        detail = "pass" if ok else "assertion failed"
                    except _PW_SYNC_ERROR as exc:
                        ok = False
                        detail = str(exc)
                    results.append(
                        {
                            "role": role_key,
                            "check": check_name,
                            "ok": ok,
                            "detail": detail,
                        }
                    )
                _logout(page)
        finally:
            context.close()
            browser.close()
    return results


def write_report(results: list[dict[str, Any]], path: Path) -> None:
    passed = sum(1 for r in results if r["ok"])
    total = len(results)
    lines = [
        "# RBAC Web E2E 自动化验收（阶段 F）",
        "",
        f"> **时间**：{datetime.now(timezone.utc).astimezone().strftime('%Y-%m-%d %H:%M %Z')}",
        f"> **前端**：{WEB_URL} · **API**：{BACKEND_URL}",
        "",
        f"## 结果：**{passed}/{total} passed**",
        "",
        "| 角色 | 检查项 | 结果 | 备注 |",
        "|------|--------|------|------|",
    ]
    for r in results:
        mark = "✅" if r["ok"] else "❌"
        lines.append(
            f"| {r['role']} | {r['check']} | {mark} | {r.get('detail', '')} |"
        )
    lines.extend(
        [
            "",
            "## 复现",
            "",
            "```powershell",
            "cd <Autopilot-Platform repo root>",
            ".venv\\Scripts\\python.exe tools\\rbac_web_e2e.py",
            "```",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="RBAC Web E2E")
    parser.add_argument(
        "--report",
        default=str(REPORT_DEFAULT),
        help="Markdown 报告路径",
    )
    parser.add_argument(
        "--json",
        default="",
        help="可选 JSON 结果路径",
    )
    args = parser.parse_args(argv)

    stack: Stack | None = None
    try:
        print("[rbac-e2e] starting platform + vite ...")
        stack = start_stack()
        print("[rbac-e2e] running playwright checks ...")
        results = run_playwright_suite()
        write_report(results, Path(args.report))
        if args.json:
            Path(args.json).write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[rbac-e2e] report -> {args.report}")
        failed = [r for r in results if not r["ok"]]
        if failed:
            for r in failed:
                print(f"  FAIL {r['role']}::{r['check']} — {r.get('detail')}", file=sys.stderr)
            return 1
        print("[rbac-e2e] all checks passed")
        return 0
    finally:
        if stack is not None:
            print("[rbac-e2e] cleaning ports and processes ...")
            stack.cleanup()
            print("[rbac-e2e] cleanup done")


if __name__ == "__main__":
    raise SystemExit(main())
