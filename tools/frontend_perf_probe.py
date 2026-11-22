"""Measure first task visibility and polling on two local SPA builds."""

from __future__ import annotations

import argparse
import asyncio
import base64
import gzip
import json
import re
import socket
import sys
import tempfile
import threading
import time
from collections import Counter
from contextlib import contextmanager, suppress
from datetime import datetime, timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from statistics import median
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
ROUTES = ("/dashboard", "/exec/jobs")
AUTH_CHECK_ROUTES = ("/admin/users", "/admin/ops", "/exec/artifacts", "/login")
TASK_NAME = "Acceptance web batch"
ORG = {"id": "probe-org", "name": "Probe organization", "my_role": "owner"}
PROJECT = {"id": "probe-project", "name": "Probe project", "org_id": ORG["id"], "my_role": "owner"}
USER = {"id": "probe-user", "username": "probe-admin", "role": "admin"}


def page_result(rows, query):
    size = int(query.get("page_size", ["50"])[0])
    page = int(query.get("page", ["1"])[0])
    start = (page - 1) * size
    return {"items": rows[start : start + size], "total": len(rows), "page": page, "page_size": size}


def fixture(token, job_count):
    now = datetime.now(timezone.utc).isoformat()
    jobs = [
        {
            "id": f"probe-job-{number:03}",
            "name": TASK_NAME if number == 0 else f"Acceptance task {number:03}",
            "status": "running" if number == job_count - 1 else "succeeded",
            "project_id": PROJECT["id"],
            "project_dir": "fixture",
            "platform": "web",
            "created_at": now,
            "runner_id": "probe-runner",
        }
        for number in range(job_count)
    ]
    statuses = dict(Counter(job["status"] for job in jobs))
    return {
        "/health": {"status": "ok", "platform_boot_id": "performance-probe"},
        "/api/v1/auth/refresh": {"access_token": token, "token_type": "bearer", "user": USER},
        "/api/v1/auth/me": USER,
        "/api/v1/auth/oidc/status": {"enabled": False},
        "/api/v1/auth/saml/status": {"enabled": False},
        "/api/v1/public/bootstrap": {},
        "/api/v1/orgs": [ORG],
        "/api/v1/projects": [PROJECT],
        "/api/v1/jobs": jobs,
        "/api/v1/runners": [{"id": "probe-runner", "name": "Probe node", "online": True}],
        "/api/v1/devices/board": {
            "devices": [],
            "summary": {"online": 0, "free": 0, "busy": 0, "by_platform": {}, "by_runner": {}},
        },
        "/api/v1/ops/summary": {
            "runners_online": 1,
            "runners_total": 1,
            "runners_offline": 0,
            "devices_total": 0,
            "devices_busy": 0,
            "jobs_by_status": statuses,
        },
        "/api/v1/ops/job-quality": {
            "days": 14, "jobs_scanned": job_count, "status_counts": statuses,
            "terminal_jobs": job_count - 1, "failed_jobs": 0, "fail_rate": 0,
            "trend": [], "error_prefix_top": {}, "fail_reason_top": {},
        },
        "/api/v1/ops/agentops": {"trace": {}, "tokens": {}},
        "/api/v1/design/stats": {},
        "/api/v1/design/chat/options": {
            "provider": "", "default_model": "", "available_models": [],
            "key_configured": False, "templates": [],
        },
        "/api/v1/design/chat/suggestions": {"suggestions": []},
    }


class ProbeHandler(SimpleHTTPRequestHandler):
    extensions_map = {**SimpleHTTPRequestHandler.extensions_map, ".js": "text/javascript"}

    def __init__(self, *args, folder, responses, api_delay, platform_api, **kwargs):
        self.responses = responses
        self.api_delay = api_delay
        self.platform_api = platform_api
        super().__init__(*args, directory=folder, **kwargs)

    def log_message(self, *_args):
        pass

    def do_GET(self):
        target = urlsplit(self.path)
        if target.path == "/health" or target.path.startswith("/api/"):
            if self.platform_api:
                self.proxy_api()
            else:
                self.send_fixture(target)
            return
        if target.path in ROUTES or target.path in AUTH_CHECK_ROUTES or target.path == "/":
            self.path = "/index.html"
        super().do_GET()

    def do_POST(self):
        target = urlsplit(self.path)
        if self.platform_api and target.path in {
            "/api/v1/auth/login", "/api/v1/auth/logout", "/api/v1/auth/refresh", "/api/v1/auth/ide-handoff/consume",
        }:
            self.proxy_api()
        elif target.path == "/api/v1/auth/refresh":
            self.send_fixture(target)
        else:
            self.send_error(405)

    def proxy_api(self):
        headers = {key: self.headers[key] for key in ("Authorization", "X-Org-Id", "Cookie", "Content-Type")
                   if key in self.headers}
        body = self.rfile.read(int(self.headers.get("Content-Length", 0))) if self.command == "POST" else None
        request = Request(self.platform_api + self.path, data=body, headers=headers, method=self.command)
        try:
            response = urlopen(request, timeout=15)
        except HTTPError as error:
            response = error
        with response:
            payload = response.read()
            self.send_response(response.status)
            for key, value in response.headers.items():
                if key.lower() in {"content-type", "set-cookie", "cache-control"}:
                    self.send_header(key, value)
            self.send_header("Content-Length", str(len(payload)))
            with suppress(ConnectionError):
                self.end_headers()
                self.wfile.write(payload)

    def send_fixture(self, target):
        query = parse_qs(target.query)
        data = self.responses.get(target.path, [])
        if isinstance(data, list):
            if target.path == "/api/v1/jobs" and "status" in query:
                data = [job for job in data if job["status"] == query["status"][0]]
            data = page_result(data, query)
        stream = json.dumps(data, ensure_ascii=False).encode()
        time.sleep(self.api_delay)
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(stream)))
        with suppress(ConnectionError):
            self.end_headers()
            self.wfile.write(stream)


@contextmanager
def serve(folder, responses, api_delay, platform_api=""):
    handler = partial(ProbeHandler, folder=folder, responses=responses, api_delay=api_delay, platform_api=platform_api)
    with ThreadingHTTPServer(("127.0.0.1", 0), handler) as server:
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}"
        finally:
            server.shutdown()
            worker.join()


INIT = """
    ({ origin, storage, taskName }) => {
      if (location.origin !== origin) return;
      Object.entries(storage).forEach(([key, value]) => localStorage.setItem(key, value));
      const findVisibleTask = () => {
        const main = document.querySelector('main');
        if (!main?.textContent.includes(taskName)) return false;
        return Array.from(main.querySelectorAll('td, li')).some(node =>
          node.textContent.includes(taskName) && node.getClientRects().length > 0
        );
      };
      const measurePaint = () => {
        if (!findVisibleTask()) return;
        observer.disconnect();
        requestAnimationFrame(() => requestAnimationFrame(() => {
          performance.mark('probe-first-task');
        }));
      };
      const observer = new MutationObserver(measurePaint);
      observer.observe(document, {childList: true, subtree: true, characterData: true});
    }
"""


async def sample(browser, origin, route, credentials, poll_seconds=0):
    context = await browser.new_context(
        viewport={"width": 1440, "height": 900}, locale="zh-CN", timezone_id="Asia/Shanghai",
        reduced_motion="reduce", service_workers="block",
    )
    try:
        initial = {
            "origin": origin,
            "taskName": TASK_NAME,
            "storage": {
                "mc_jwt": credentials["token"],
                "mc_user": json.dumps(credentials["user"]),
                "mc_filter_org_id": credentials["org_id"],
                "mc_filter_project_id": credentials["project_id"],
                "autopilot-mc-theme": "light",
            },
        }
        await context.add_init_script(f"({INIT})({json.dumps(initial)})")
        page = await context.new_page()
        counts = Counter()
        job_reads = []
        errors = []

        def count(request):
            path = urlsplit(request.url).path
            if path == "/health" or path.startswith("/api/"):
                key = f"{request.method} {path}"
                if path == "/api/v1/jobs" and "status" in parse_qs(urlsplit(request.url).query):
                    key += "?status"
                counts[key] += 1
                if key == "GET /api/v1/jobs":
                    job_reads.append(time.perf_counter())

        page.on("request", count)
        page.on("pageerror", lambda error: errors.append(str(error)))
        await page.goto(origin + route, wait_until="domcontentloaded")
        try:
            await page.wait_for_function(
                "Boolean(performance.getEntriesByName('probe-first-task')[0])",
                polling=50,
                timeout=15000,
            )
        except Exception as error:
            raise RuntimeError(f"{page.url} did not display a task. Requests: {dict(counts)}. Errors: {errors}") from error
        if urlsplit(page.url).path != route:
            raise RuntimeError(f"Expected {origin}{route}, browser opened {page.url}")
        if not poll_seconds:
            if errors:
                raise RuntimeError(errors)
            return await page.evaluate(
                """() => ({
                    first_task_ms: performance.getEntriesByName('probe-first-task')[0].startTime,
                    first_contentful_paint_ms: performance.getEntriesByName('first-contentful-paint')[0]?.startTime,
                    api_before_task: performance.getEntriesByType('resource').flatMap(entry => {
                      const url = new URL(entry.name);
                      if (url.origin !== location.origin ||
                          (url.pathname !== '/health' && !url.pathname.startsWith('/api/'))) return [];
                      return [{
                        path: url.pathname,
                        start_ms: Math.round(entry.startTime),
                        end_ms: Math.round(entry.responseEnd),
                      }];
                    }),
                })"""
            )
        await page.wait_for_load_state("networkidle")
        if await page.evaluate("document.visibilityState") != "visible":
            raise RuntimeError(f"{origin}{route} is hidden while measuring polling")
        if not counts["GET /api/v1/jobs"]:
            raise RuntimeError(f"{origin}{route} did not request the job list on startup")
        if route == "/exec/jobs" and not counts["GET /api/v1/artifacts"]:
            raise RuntimeError(f"{origin}{route} did not request artifacts on startup")
        before = counts.copy()
        poll_started = time.perf_counter()
        await asyncio.sleep(poll_seconds)
        if errors:
            raise RuntimeError(errors)
        return {
            "startup": dict(sorted(before.items())),
            "poll": dict(sorted((counts - before).items())),
            "poll_job_read_seconds": [round(at - poll_started, 2) for at in job_reads if at >= poll_started],
        }
    finally:
        await context.close()


def asset_sizes(folder):
    index = (folder / "index.html").read_text(encoding="utf-8")
    files = [folder / path for path in re.findall(r'["\']/(assets/index-[^"\']+\.(?:js|css))["\']', index)]
    return {
        path.suffix[1:]: {
            "file": path.name,
            "bytes": len(payload := path.read_bytes()),
            "gzip_bytes": len(gzip.compress(payload, mtime=0)),
        }
        for path in files
    }


async def measure_polling(chromium, channel, origin, route, token, seconds):
    # An independent browser keeps each measured page visible to its app polling logic.
    browser = await chromium.launch(channel=channel)
    try:
        return await sample(browser, origin, route, token, seconds)
    finally:
        await browser.close()


async def measure(origins, token, repeats, poll_seconds, browser_channel):
    async with async_playwright() as runner:
        browser = await runner.chromium.launch(channel=browser_channel)
        try:
            results = {key: {} for key in origins}
            for route in ROUTES:
                samples = {key: [] for key in origins}
                for iteration in range(repeats):
                    order = list(origins) if iteration % 2 == 0 else list(reversed(origins))
                    for key in order:
                        samples[key].append(await sample(browser, origins[key], route, token))
                for key in origins:
                    task_ms = [row["first_task_ms"] for row in samples[key]]
                    results[key][route] = {
                        "median_first_task_ms": round(median(task_ms), 1),
                        "first_task_ms": [round(value, 1) for value in task_ms],
                        "samples": samples[key],
                    }
            version = browser.version
        finally:
            await browser.close()
        for route in ROUTES:
            for key in origins:
                results[key][route]["requests"] = await measure_polling(
                    runner.chromium, browser_channel, origins[key], route, token, poll_seconds,
                )
        return version, results


@contextmanager
def real_platform(job_count):
    from tools import rbac_web_e2e as e2e

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        e2e.BACKEND_PORT = listener.getsockname()[1]
    e2e.BACKEND_URL = f"http://127.0.0.1:{e2e.BACKEND_PORT}"
    stack = e2e.Stack(tmp=Path(tempfile.mkdtemp(prefix="perf-platform-", dir=ROOT / "logs")))
    try:
        # The benchmark uses its own static origins rather than the Vite development host.
        e2e.start_stack(stack, start_frontend=False)
        auth = e2e._api_json("POST", "/api/v1/auth/login", body={"username": "admin", "password": "admin"})
        token = auth["access_token"]
        headers = {"X-Org-Id": e2e.ORG_ID}
        for number in range(job_count):
            final_job = number == job_count - 1
            job = e2e._api_json("POST", "/api/v1/jobs", token=token, headers=headers, body={
                "name": TASK_NAME if final_job else f"Acceptance task {number:03}",
                "project_id": e2e.PROJECT_ID,
                "project_dir": "perf-fixture",
                "platform": "web",
            })
            if not final_job:
                e2e._api_json("POST", f"/api/v1/jobs/{job['id']}/cancel", token=token, headers=headers)
        yield e2e.BACKEND_URL, {"token": token, "user": auth["user"], "org_id": e2e.ORG_ID,
                                "project_id": e2e.PROJECT_ID}
    finally:
        stack.cleanup()


@contextmanager
def mock_platform(job_count):
    encoded = base64.urlsafe_b64encode(json.dumps({"typ": "access", "exp": int(time.time()) + 3600}).encode())
    token = "probe." + encoded.decode().rstrip("=") + ".probe"
    yield "", {"token": token, "user": USER, "org_id": ORG["id"], "project_id": PROJECT["id"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, default=ROOT / "logs/frontend-redesign-baseline")
    parser.add_argument("--current", type=Path, default=ROOT / "autopilot_platform/frontend/dist")
    parser.add_argument("--output", type=Path, default=ROOT / "logs/frontend-performance.json")
    parser.add_argument("--runs", type=int, default=7)
    parser.add_argument("--poll-seconds", type=float, default=65)
    parser.add_argument("--api-delay-ms", type=float, default=20)
    parser.add_argument("--job-count", type=int, default=12)
    parser.add_argument("--browser-channel", default="chrome")
    parser.add_argument("--real-platform", action="store_true", help="start an isolated SQLite Platform API")
    args = parser.parse_args()
    if min(args.runs, args.job_count) < 1 or args.poll_seconds <= 0 or args.api_delay_ms < 0:
        parser.error("runs, job-count and poll-seconds must be positive, api-delay-ms must be nonnegative")
    paths = {"baseline": args.baseline.resolve(), "current": args.current.resolve()}
    sizes = {key: asset_sizes(path) for key, path in paths.items()}
    platform = real_platform if args.real_platform else mock_platform
    with platform(args.job_count) as (api_url, credentials):
        responses = {} if api_url else fixture(credentials["token"], args.job_count)
        delay = 0 if api_url else args.api_delay_ms / 1000
        with (
            serve(paths["baseline"], responses, delay, api_url) as baseline,
            serve(paths["current"], responses, delay, api_url) as current,
        ):
            browser, results = asyncio.run(measure(
                {"baseline": baseline, "current": current}, credentials, args.runs, args.poll_seconds,
                args.browser_channel,
            ))
    output = {
        "browser": browser,
        "viewport": [1440, 900],
        "fixture_jobs": args.job_count,
        "api": "isolated SQLite Platform" if args.real_platform else "fixture",
        "api_delay_ms": 0 if args.real_platform else args.api_delay_ms,
        "runs": args.runs,
        "poll_seconds": args.poll_seconds,
        "assets": sizes,
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for route in ROUTES:
        for key in paths:
            row = results[key][route]
            print(key, route, row["median_first_task_ms"], "ms", sum(row["requests"]["poll"].values()),
                  "poll requests")
    print(args.output)


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    main()
