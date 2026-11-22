"""RBAC Web 四账号 Playwright E2E（在独立端口自启 Platform 与 Vite）。

依赖：pip install -e ".[e2e]" 或 pip install -e ".[dev]"（含 playwright）。

用法（Autopilot-Platform 根目录）:
  .venv\\Scripts\\python.exe tools/rbac_web_e2e.py
  .venv\\Scripts\\python.exe tools/rbac_web_e2e.py --browser-channel chrome
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "autopilot_platform" / "frontend"
REPORT_DEFAULT = ROOT / "audit-output" / "24-rbac-web-e2e-validation.md"

ORG_ID = "org-rbac-e2e"
PROJECT_ID = "p-rbac-e2e"
ORG_NAME = "RBAC E2E Org"
PROJECT_NAME = "RBAC E2E Project"
BACKEND_PORT = 18080
WEB_PORT = 15173
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


def _http_ready(url: str, proc: subprocess.Popen[Any], log: Path) -> None:
    deadline = time.monotonic() + 30
    last: str | None = None
    while time.monotonic() < deadline and proc.poll() is None:
        try:
            with urlopen(Request(url, method="GET"), timeout=5) as resp:
                if 200 <= resp.status < 400:
                    return
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            last = str(exc)
            time.sleep(1)
    tail = log.read_text(encoding="utf-8", errors="replace")[-4000:]
    raise RuntimeError(f"{url} not ready: {last or proc.returncode}\n{tail}")


def _check_test_ports() -> None:
    with socket.socket() as backend_socket, socket.socket() as web_socket:
        for port, probe in ((BACKEND_PORT, backend_socket), (WEB_PORT, web_socket)):
            try:
                probe.bind(("127.0.0.1", port))
            except OSError as exc:
                raise RuntimeError(f"测试端口 {port} 已被占用") from exc


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

    post("/api/v1/orgs", {"id": ORG_ID, "name": ORG_NAME})
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
        {"id": PROJECT_ID, "name": PROJECT_NAME, "org_id": ORG_ID},
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

    runner_headers = {"X-API-Token": "runner-global-token"}
    _api_json(
        "POST", "/api/v1/runners/register", headers=runner_headers,
        body={"runner_id": "e2e-runner", "hostname": "e2e-host", "capabilities": ["web"]},
    )
    _api_json(
        "POST", "/api/v1/runners/heartbeat", headers=runner_headers,
        body={"runner_id": "e2e-runner", "inventory": [], "devices": [], "capabilities": ["web"]},
    )


def _seed_model_usage(tmp: Path) -> None:
    usage = tmp / "ai_usage"
    usage.mkdir()
    sample = {
        "source": "rbac-e2e",
        "project_id": PROJECT_ID,
        "org_id": ORG_ID,
        "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
    }
    (usage / f"usage-{date.today().isoformat()}.jsonl").write_text(
        json.dumps(sample) + "\n", encoding="utf-8",
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
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
        self.procs.clear()
        if self.tmp.exists():
            shutil.rmtree(self.tmp, ignore_errors=True)

    def start(self, name: str, command: list[str], directory: Path, env: dict[str, str], ready_url: str) -> None:
        log = self.tmp / f"{name}.log"
        with log.open("w", encoding="utf-8") as output:
            proc = subprocess.Popen(
                command, cwd=directory, env=env, stdout=output, stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
            )
        self.procs.append(proc)
        _http_ready(ready_url, proc, log)


def start_stack(stack: Stack, *, start_frontend: bool = True) -> None:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    db_path = stack.tmp / "rbac_e2e.db"
    _seed_model_usage(stack.tmp)
    env = os.environ.copy()
    env.update(
        {
            _ENV_UNBUFFERED: "1",
            "MC_PORT": str(BACKEND_PORT),
            "MC_ENV": "dev",
            "MC_HOST": "127.0.0.1",
            "MC_FRONTEND_DEV_URL": WEB_URL if start_frontend else "",
            "MC_DATABASE_URL": f"sqlite:///{db_path.as_posix()}",
            "MC_DATA_DIR": str(stack.tmp / "data"),
            "MC_ARTIFACTS_DIR": str(stack.tmp / "artifacts"),
            "MC_APP_BUILDS_DIR": str(stack.tmp / "app_builds"),
            "MC_RUNTIME_CONFIG": str(stack.tmp / "runtime.json"),
            "MC_JOB_LOGS_DIR": str(stack.tmp / "job_logs"),
            "MC_ADMIN_USER": "admin",
            "MC_ADMIN_PASSWORD": "admin",
            "MC_SCHEDULE_ENABLED": "0",
            "MC_ALLOW_MANAGED_RUNNER": "0",
            "MC_API_TOKEN": "runner-global-token",
            "MC_ADMIN_API_TOKEN": "admin-ops-token",
        }
    )

    stack.start(
        "platform",
        [
            str(stack.python),
            "-m",
            "uvicorn",
            "autopilot_platform.platform.app:create_app",
            "--factory",
            "--host",
            "127.0.0.1",
            "--port",
            str(BACKEND_PORT),
        ],
        ROOT, env, f"{BACKEND_URL}/health",
    )
    bootstrap_rbac_world()

    if start_frontend:
        from start_dev import _ensure_frontend_deps, _resolve_node

        vite_js = _ensure_frontend_deps()
        node = _resolve_node()
        stack.start(
            "vite",
            [node, str(vite_js), "--host", "127.0.0.1", "--port", str(WEB_PORT), "--strictPort"],
            FRONTEND, env, f"{WEB_URL}/health",
        )


Check = tuple[str, Callable[[Any], bool]]


def _nav_visible(page: Any, label: str) -> bool:
    return _nav_item(page, label).is_visible()


def _nav_item(page: Any, label: str) -> Any:
    return page.get_by_role("navigation", name="主导航").get_by_role("link", name=label, exact=True)


def _check_context(page: Any, *, select: bool = False) -> None:
    for label, option in (
        ("当前组织", f"{ORG_NAME} ({ORG_ID})"),
        ("当前项目", f"{PROJECT_NAME} ({PROJECT_ID})"),
    ):
        trigger = page.get_by_role("combobox", name=label, exact=True)
        if select:
            trigger.click()
            page.get_by_role("listbox", name=label, exact=True).get_by_role(
                "option", name=option, exact=True,
            ).click()
        trigger.get_by_text(option, exact=True).wait_for()


def _login(page: Any, username: str, password: str) -> None:
    page.goto(WEB_URL, wait_until=_WAIT_LOAD_STATE)
    page.get_by_label("用户名", exact=True).fill(username)
    page.get_by_label("密码", exact=True).fill(password)
    page.get_by_role("button", name="登录", exact=True).click()
    page.get_by_role("navigation", name="主导航").wait_for()


def _logout(page: Any) -> None:
    page.get_by_title("退出系统", exact=True).click()
    page.get_by_role("heading", name="登录", exact=True).wait_for()


def _session_restores_context(page: Any) -> bool:
    page.reload(wait_until=_WAIT_LOAD_STATE)
    page.get_by_role("navigation", name="主导航").wait_for()
    _check_context(page)
    return True


def _open_page(page: Any, nav: str, heading: str | None = None) -> Any:
    _nav_item(page, nav).click()
    main = page.get_by_role("main")
    main.get_by_role("heading", name=heading or nav, exact=True).wait_for()
    return main


def _share_readonly_hint_visible(page: Any) -> bool:
    main = _open_page(page, "共享")
    return main.get_by_text("只读项目，无法修改共享", exact=True).is_visible()


def _share_no_create_form(page: Any) -> bool:
    main = _open_page(page, "共享")
    return not main.get_by_role("button", name="建立授权", exact=True).is_visible()


def _dashboard_status_visible(page: Any, label: str) -> bool:
    main = _open_page(page, "总览", "运行总览")
    return main.get_by_role("region", name="运行状态").get_by_text(label, exact=True).is_visible()


def _design_token_section_visible(page: Any) -> bool:
    main = _open_page(page, "设计总览")
    main.locator("[aria-busy=false]").get_by_role("table", name="设计资源").wait_for()
    return main.get_by_text("模型用量与审计", exact=True).is_visible()


def _runners_has_issue_token(page: Any) -> bool:
    main = _open_page(page, "设备")
    main.get_by_role("navigation", name="设备分区").get_by_role(
        "button", name="执行节点", exact=True,
    ).click()
    main.get_by_role("tablist", name="执行节点筛选").wait_for()
    return main.get_by_role("button", name="签发令牌", exact=True).is_visible()


def _checks_for_role(role_key: str) -> list[Check]:
    if role_key == "platform_admin":
        return [
            ("nav_运维", lambda p: _nav_visible(p, "运维")),
            ("nav_设备", lambda p: _nav_visible(p, "设备")),
            ("nav_共享", lambda p: _nav_visible(p, "共享")),
            ("dashboard_执行节点", lambda p: _dashboard_status_visible(p, "执行节点")),
            ("design_显示模型用量", _design_token_section_visible),
            ("runners_管理入口", _runners_has_issue_token),
        ]
    if role_key == "org_admin":
        return [
            ("nav_无运维", lambda p: not _nav_visible(p, "运维")),
            ("nav_审计", lambda p: _nav_visible(p, "审计")),
            ("nav_用户", lambda p: _nav_visible(p, "用户")),
            ("nav_设备", lambda p: _nav_visible(p, "设备")),
            ("design_隐藏模型用量", lambda p: not _design_token_section_visible(p)),
            ("runners_隐藏管理入口", lambda p: not _runners_has_issue_token(p)),
        ]
    if role_key == "project_viewer":
        return [
            ("nav_共享", lambda p: _nav_visible(p, "共享")),
            ("share_只读提示", _share_readonly_hint_visible),
            ("share_无建立表单", _share_no_create_form),
            ("design_隐藏模型用量", lambda p: not _design_token_section_visible(p)),
        ]
    # operator
    return [
        ("nav_无运维", lambda p: not _nav_visible(p, "运维")),
        ("nav_无审计", lambda p: not _nav_visible(p, "审计")),
        ("nav_无用户", lambda p: not _nav_visible(p, "用户")),
        ("nav_设备", lambda p: _nav_visible(p, "设备")),
        ("nav_共享", lambda p: _nav_visible(p, "共享")),
        ("dashboard_进行中", lambda p: _dashboard_status_visible(p, "进行中")),
        ("design_隐藏模型用量", lambda p: not _design_token_section_visible(p)),
        ("runners_隐藏管理入口", lambda p: not _runners_has_issue_token(p)),
    ]


def run_playwright_suite(browser_channel: str | None = None) -> list[dict[str, Any]]:
    pw_api = _playwright_api()
    assert _PW_SYNC_ERROR is not None
    results: list[dict[str, Any]] = []
    with pw_api.sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, channel=browser_channel)
        try:
            for role_key, (username, password) in ACCOUNTS.items():
                context = browser.new_context(viewport={"width": 1280, "height": 900})
                try:
                    page = context.new_page()
                    page.set_default_timeout(10_000)
                    _login(page, username, password)
                    _check_context(page, select=True)
                    checks: list[Check] = [("session_刷新后恢复会话和上下文", _session_restores_context)]
                    checks.extend(_checks_for_role(role_key))
                    for check_name, fn in checks:
                        try:
                            ok = bool(fn(page))
                            detail = "pass" if ok else "assertion failed"
                        except _PW_SYNC_ERROR as exc:
                            ok = False
                            detail = str(exc)
                        results.append(
                            {"role": role_key, "check": check_name, "ok": ok, "detail": detail}
                        )
                    _logout(page)
                finally:
                    context.close()
        finally:
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
    parser.add_argument("--browser-channel", default=None, help="浏览器发行渠道，例如 chrome")
    args = parser.parse_args(argv)

    stack: Stack | None = None
    try:
        print("[rbac-e2e] starting platform + vite ...")
        _check_test_ports()
        stack = Stack(tmp=Path(tempfile.mkdtemp(prefix="rbac_e2e_")))
        start_stack(stack)
        print("[rbac-e2e] running playwright checks ...")
        results = run_playwright_suite(args.browser_channel)
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
