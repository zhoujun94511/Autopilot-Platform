"""Platform 仓 CI / 运维：触发批跑 Job（B1-C 镜像，无需 IDE 仓）。

用法：
  python -m autopilot_platform.platform.cli_create_job --artifact-id … --dry-run
  ap-create-job --artifact-id … --platform ios
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any

from autopilot_platform.ap.mgmt.client import MgmtClient, MgmtClientError
from autopilot_platform.platform.core.urls import platform_base_url


def build_job_body(args: argparse.Namespace) -> dict[str, Any]:
    udids = [x.strip() for x in (args.device_udids or "").split(",") if x.strip()]
    entries = [x.strip() for x in (args.entry_paths or "").split(",") if x.strip()]
    body: dict[str, Any] = {
        "name": (args.name or "CI Suite").strip() or "CI Suite",
        "platform": (args.platform or "android").strip().lower() or "android",
        "project_id": (args.project_id or "").strip(),
        "artifact_id": (args.artifact_id or "").strip() or None,
        "app_build_id": (args.app_build_id or "").strip() or None,
        "project_dir": (args.project_dir or "").strip(),
        "device_udids": udids,
        "entry_paths": entries,
        "parallel": bool(args.parallel),
        "parallel_workers": int(args.parallel_workers or 0),
        "backend_mode": (args.backend_mode or "auto").strip() or "auto",
        "web_engine": (args.web_engine or "selenium").strip() or "selenium",
        "wda_bundle": (args.wda_bundle or "").strip(),
        "preferred_runner_id": (args.preferred_runner_id or "").strip() or None,
        "webhook_url": (args.webhook_url or "").strip(),
    }
    if not body["artifact_id"] and not body["project_dir"]:
        raise ValueError("必须提供 --artifact-id 或 --project-dir（至少一项）")
    return body


def _add_job_args(ap: argparse.ArgumentParser) -> None:
    ap.add_argument(
        "--server",
        default=os.environ.get("MC_SERVER", platform_base_url()),
        help="Platform base URL（默认 MC_SERVER / 内置地址）",
    )
    auth = ap.add_mutually_exclusive_group()
    auth.add_argument(
        "--token",
        default=os.environ.get("MC_API_TOKEN", ""),
        help="运维 X-API-Token（默认 MC_API_TOKEN）",
    )
    auth.add_argument(
        "--jwt",
        default=os.environ.get("MC_JWT", ""),
        help="用户 Bearer JWT（默认 MC_JWT）",
    )
    ap.add_argument("--username", default=os.environ.get("MC_USERNAME", ""))
    ap.add_argument("--password", default=os.environ.get("MC_PASSWORD", ""))
    ap.add_argument("--org-id", default=os.environ.get("MC_ORG_ID", ""))
    ap.add_argument("--name", default="CI Suite")
    ap.add_argument("--platform", default="android", help="android|ios|web|http")
    ap.add_argument("--project-id", default="")
    ap.add_argument("--artifact-id", default="")
    ap.add_argument("--app-build-id", default="")
    ap.add_argument("--project-dir", default="")
    ap.add_argument("--device-udids", default="")
    ap.add_argument("--entry-paths", default="")
    ap.add_argument("--parallel", action="store_true")
    ap.add_argument("--parallel-workers", type=int, default=0)
    ap.add_argument("--backend-mode", default="auto")
    ap.add_argument("--web-engine", default="selenium")
    ap.add_argument("--wda-bundle", default="")
    ap.add_argument("--preferred-runner-id", default="")
    ap.add_argument("--webhook-url", default="")
    ap.add_argument("--wait", action="store_true")
    ap.add_argument("--wait-timeout", type=float, default=3600.0)
    ap.add_argument("--poll-interval", type=float, default=5.0)
    ap.add_argument("--dry-run", action="store_true")


def _client_from_args(args: argparse.Namespace) -> MgmtClient:
    jwt = (args.jwt or "").strip()
    token = (args.token or "").strip()
    user = (args.username or "").strip()
    password = args.password or ""
    if not jwt and user and password:
        with MgmtClient(
            args.server, api_token="", jwt="", org_id=args.org_id
        ) as probe:
            out = probe.login(user, password)
            jwt = str(out.get("access_token") or out.get("token") or "").strip()
            if not jwt:
                raise MgmtClientError("登录成功但未返回 access_token")
    if not jwt and not token:
        raise MgmtClientError(
            "请提供 --token / MC_API_TOKEN，或 --jwt / 用户名密码登录"
        )
    return MgmtClient(
        args.server,
        api_token="" if jwt else token,
        jwt=jwt,
        org_id=args.org_id,
    )


_TERMINAL = frozenset({"succeeded", "failed", "cancelled", "error"})


def _wait_job(
    client: MgmtClient, job_id: str, *, timeout: float, interval: float
) -> dict:
    deadline = time.monotonic() + max(1.0, timeout)
    last: dict = {}
    while time.monotonic() < deadline:
        last = client.get_job(job_id) or {}
        st = str(last.get("status") or "").strip().lower()
        if st in _TERMINAL:
            return last
        time.sleep(max(0.5, interval))
    raise MgmtClientError(
        f"等待 Job {job_id} 超时（最后状态={last.get('status')!r}）"
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="触发 Platform 批跑 Job（本仓 CLI）")
    _add_job_args(ap)
    args = ap.parse_args(argv)
    try:
        body = build_job_body(args)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.dry_run:
        print(json.dumps(body, ensure_ascii=False, indent=2))
        return 0
    try:
        with _client_from_args(args) as client:
            job = client.create_job(body)
            jid = str(job.get("id") or "").strip()
            print(json.dumps(job, ensure_ascii=False, indent=2))
            if args.wait:
                if not jid:
                    raise MgmtClientError("create_job 未返回 id")
                final = _wait_job(
                    client,
                    jid,
                    timeout=float(args.wait_timeout),
                    interval=float(args.poll_interval),
                )
                print(json.dumps(final, ensure_ascii=False, indent=2))
                st = str(final.get("status") or "").strip().lower()
                return 0 if st == "succeeded" else 1
    except MgmtClientError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
