"""Intent 导入 CLI。

入口：
  IDE:      python -m autopilot.intent import|watch|review|bind …
  Platform: python -m autopilot_platform.ap.intent import|watch|review|bind …

与 IDE「导入逻辑用例」共用 write_logical_cases_as_drafts。
可选：对质量分足够的 AI_DRAFT 半自动标 APPROVED（需 --auto-approve）；
``watch`` 轮询 APPROVED 增量导入。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from .config import (
    intent_auto_approve_min_quality,
    intent_import_subdir,
    intent_watch_interval_sec,
    intent_webhook_host,
    intent_webhook_port,
    intent_webhook_secret,
)
from .watch import filter_new_cases, load_seen_ids, save_seen_ids
from ..runtime import settings
from ..runtime.env_file import load_project_dotenv


def _cmd_import(args: argparse.Namespace) -> int:
    project_dir = Path(args.project).resolve()
    if not project_dir.is_dir():
        print(f"工程目录不存在: {project_dir}", file=sys.stderr)
        return 2

    if args.from_file:
        raw = json.loads(Path(args.from_file).read_text(encoding="utf-8"))
        if isinstance(raw, dict) and "cases" in raw:
            cases: list[dict] = list(raw.get("cases") or [])
        elif isinstance(raw, list):
            cases = raw
        elif isinstance(raw, dict):
            cases = [raw]
        else:
            print("无法解析 --from-file JSON", file=sys.stderr)
            return 2
    else:
        # 延迟：mgmt 会话只在从 Platform 拉取、不走 --from-file 时需要
        from ..mgmt.auth_api import ensure_user_session

        pid = (args.project_id or settings.mc_project_id() or "").strip()
        if not pid:
            print("需要 --project-id 或已配置 mc_project_id", file=sys.stderr)
            return 2
        client, _ = ensure_user_session(require=True)
        try:
            if args.auto_approve:
                min_q = float(args.min_quality)
                if min_q < 0:
                    min_q = intent_auto_approve_min_quality()
                _maybe_auto_approve(client, pid, min_score=min_q)
            bundle = client.export_approved_logical_cases(pid)
            cases = list((bundle or {}).get("cases") or [])
        finally:
            client.close()

    return _write_cases(args, project_dir, cases)


def _write_cases(args: argparse.Namespace, project_dir: Path, cases: list[dict]) -> int:
    # 延迟：写草稿/回写 automation_status 只在导入子命令命中时需要
    from ..mgmt.logical_import import write_logical_cases_as_drafts
    from ..mgmt.status_sync import collect_logical_case_ids, patch_automation_status

    if getattr(args, "only_new", False):
        seen = load_seen_ids(project_dir)

        before = len(cases)
        cases = filter_new_cases(cases, seen)
        print(f"增量过滤：{before} → {len(cases)} 条新 APPROVED")

    subdir = (getattr(args, "subdir", None) or "").strip() or intent_import_subdir()
    pkg = (getattr(args, "package", None) or "").strip()
    if pkg:
        session = {
            "platform": (getattr(args, "platform", None) or "android").strip() or "android",
            "package_name": pkg,
            "main_activity": (getattr(args, "activity", None) or "").strip(),
        }
    else:
        # 延迟：未给 --package 时才从环境读 webhook 导入会话
        from .webhook_server import _import_session_from_env

        session = _import_session_from_env()
    paths = write_logical_cases_as_drafts(
        project_dir,
        cases,
        project_id=getattr(args, "project_id", "") or "",
        subdir=subdir,
        session=session,
    )
    print(f"写入 {len(paths)} 个可跑意图用例 → {project_dir / subdir}")
    for p in paths:
        print(f"  {p}")

    if cases:
        seen = load_seen_ids(project_dir)
        for c in cases:
            cid = str(c.get("logical_case_id") or c.get("id") or "").strip()
            if cid:
                seen.add(cid)
        save_seen_ids(project_dir, seen)

    if getattr(args, "sync_status", False) and not getattr(args, "from_file", "") and cases:
        # 延迟：仅 --sync-status 且未指定 --from-file 时需要 Platform 会话
        from ..mgmt.auth_api import ensure_user_session

        client, _ = ensure_user_session(require=True)
        try:
            ids = collect_logical_case_ids(cases)
            ok, bad = patch_automation_status(client, ids, "INTENT_READY")
            print(f"automation_status→INTENT_READY：成功 {ok}，失败 {bad}")
        finally:
            client.close()
    return 0


def _maybe_auto_approve(client, project_id: str, *, min_score: float) -> None:
    """半自动审批：AI_DRAFT 且 quality.score >= min_score → APPROVED。"""
    rows = client.list_logical_cases(project_id=project_id) or []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("review_status") or "") != "AI_DRAFT":
            continue
        meta = row.get("generation_metadata") or {}
        quality = meta.get("quality") if isinstance(meta, dict) else {}
        score = None
        if isinstance(quality, dict):
            score = quality.get("score")
        try:
            sc = float(score) if score is not None else -1.0
        except (TypeError, ValueError):
            sc = -1.0
        if sc < min_score:
            continue
        cid = str(row.get("logical_case_id") or row.get("id") or "")
        if not cid:
            continue
        client.update_logical_case(cid, {"review_status": "APPROVED"})
        print(f"auto-approve {cid} (score={sc})")


def _cmd_watch(args: argparse.Namespace) -> int:
    """轮询 Platform APPROVED 并增量导入。"""
    # 延迟：watch 子命令才需要 Platform 会话
    from ..mgmt.auth_api import ensure_user_session

    project_dir = Path(args.project).resolve()
    if not project_dir.is_dir():
        print(f"工程目录不存在: {project_dir}", file=sys.stderr)
        return 2
    pid = (args.project_id or settings.mc_project_id() or "").strip()
    if not pid:
        print("需要 --project-id 或已配置 mc_project_id", file=sys.stderr)
        return 2
    interval = int(args.interval or 0) or intent_watch_interval_sec()
    interval = max(5, interval)
    once = bool(args.once)
    print(f"watch project={project_dir} platform_project={pid} interval={interval}s")
    while True:
        client, _ = ensure_user_session(require=True)
        try:
            if args.auto_approve:
                min_q = float(args.min_quality)
                if min_q < 0:
                    min_q = intent_auto_approve_min_quality()
                _maybe_auto_approve(client, pid, min_score=min_q)
            bundle = client.export_approved_logical_cases(pid)
            cases = list((bundle or {}).get("cases") or [])
        finally:
            client.close()
        args.only_new = True
        args.from_file = ""
        _write_cases(args, project_dir, cases)
        if once:
            return 0
        time.sleep(interval)


def _cmd_review(args: argparse.Namespace) -> int:
    # 延迟：review 子命令才扫 result.json
    from .review import collect_failed_intents

    path, rows = collect_failed_intents(args.project, result_path=args.result)
    if path is None:
        print("未找到 result.json", file=sys.stderr)
        return 1
    print(f"来源: {path}")
    print(f"失败意图: {len(rows)}")
    for r in rows:
        print(
            f"- [{r.get('intent_id')}] {r.get('case_name')}: "
            f"{r.get('name')} | {r.get('binding_hit')} | heal={r.get('heal_count', 0)} | "
            f"{r.get('error_message')}"
        )
    return 0


def _cmd_bind(args: argparse.Namespace) -> int:
    # 延迟：bind 子命令才写手工绑定
    from .manual_bind import apply_manual_binding

    try:
        entry = apply_manual_binding(
            args.project,
            args.logical_case_id,
            args.intent_id,
            locator=args.locator,
            keyword_id=args.keyword or "",
            platform=args.platform,
            action=args.action,
            value=args.value or "",
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(entry, ensure_ascii=False, indent=2))
    return 0


def _cmd_serve_webhook(args: argparse.Namespace) -> int:
    # 延迟：serve 子命令才起 HTTP webhook
    from .webhook_server import serve_webhook

    host = (args.host or intent_webhook_host()).strip() or intent_webhook_host()
    port = int(args.port or intent_webhook_port())
    secret = (args.secret or "").strip() or intent_webhook_secret()
    allow_insecure = bool(getattr(args, "allow_insecure", False))
    subdir = (args.subdir or intent_import_subdir()).strip() or intent_import_subdir()
    print(
        f"listening http://{host}:{port}/hooks/intent "
        f"(project={args.project}, secret={'yes' if secret else 'no'}, "
        f"allow_insecure={allow_insecure})"
    )
    serve_webhook(
        project_dir=args.project,
        host=host,
        port=port,
        secret=secret,
        subdir=subdir,
        blocking=True,
        allow_insecure=allow_insecure,
    )
    return 0


CLI_WEBHOOK_EPILOG = """
Webhook 自动导入（Platform APPROVED → IDE 工程）：
  1) IDE: python -m autopilot.intent serve-webhook --project <工程目录> [--secret <与 MC_WEBHOOK_SECRET 相同>]
  2) Platform: MC_DESIGN_WEBHOOK_URL=http://127.0.0.1:8765/hooks/intent（运维配置或 .env）
  3) Web 审核通过即 POST /hooks/intent；写入 <工程>/imported_logical/
  4) 建议 import/watch 加 --sync-status 回写 automation_status=INTENT_READY

无 Webhook 时轮询：
  python -m autopilot.intent watch --project <工程> --project-id <id> --sync-status
"""


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="autopilot.intent.cli",
        description="Intent 导入与失败审阅",
        epilog=CLI_WEBHOOK_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    def _add_import_flags(cmd: argparse.ArgumentParser) -> None:
        cmd.add_argument("--project", required=True, help="本地工程根目录")
        cmd.add_argument("--project-id", default="", help="Platform 项目 id")
        cmd.add_argument("--subdir", default="", help="默认 imported_logical / AUTOPILOT_INTENT_IMPORT_SUBDIR")
        cmd.add_argument(
            "--sync-status",
            action="store_true",
            help=(
                "导入后回写 automation_status=INTENT_READY。"
                "注意：仅「从 Platform 拉取」时生效；--from-file 本地导入不会回写。"
                "若不加本开关，APPROVED 导入后设计域可能仍停留在 LOGICAL/旧状态。"
            ),
        )
        cmd.add_argument(
            "--auto-approve",
            action="store_true",
            help="导入前将高质量 AI_DRAFT 标为 APPROVED（半自动）",
        )
        cmd.add_argument(
            "--min-quality",
            type=float,
            default=-1.0,
            help="--auto-approve 最低 quality.score（默认 env 或 0.8）",
        )
        cmd.add_argument(
            "--package",
            default="",
            help="目标应用包名；写入 mobile_app_start（也可用 AUTOPILOT_IMPORT_PACKAGE）",
        )
        cmd.add_argument(
            "--platform",
            default="android",
            help="转化平台（配合 --package）",
        )
        cmd.add_argument(
            "--activity",
            default="",
            help="可选 activityName（Android）",
        )

    imp = sub.add_parser("import", help="导入 APPROVED 意图用例为可跑 .tc.yaml")
    _add_import_flags(imp)
    imp.add_argument(
        "--from-file",
        default="",
        help="从本地 JSON（export bundle 或 cases[]）导入，不连网",
    )
    imp.add_argument(
        "--only-new",
        action="store_true",
        help="仅导入尚未写入过的 logical_case_id",
    )
    imp.set_defaults(func=_cmd_import)

    wat = sub.add_parser("watch", help="轮询 APPROVED 并增量导入工程")
    _add_import_flags(wat)
    wat.add_argument("--interval", type=int, default=0, help="轮询间隔秒（默认 env 或 30）")
    wat.add_argument("--once", action="store_true", help="只拉取一轮后退出")
    wat.set_defaults(func=_cmd_watch, only_new=True, from_file="")

    srv = sub.add_parser(
        "serve-webhook",
        help="接收 Platform APPROVED webhook 并导入（须与 MC_DESIGN_WEBHOOK_URL 配对）",
        description=(
            "在本机监听 /hooks/intent（与 MC_DESIGN_WEBHOOK_URL 配对）。"
            "Platform 审核通过时 POST 事件，自动写入工程 imported_logical/。"
            "无 secret 时仅 loopback 且需 --allow-insecure。"
        ),
    )
    srv.add_argument("--project", required=True, help="本地工程根目录")
    srv.add_argument("--host", default="", help="默认 AUTOPILOT_INTENT_WEBHOOK_HOST 或 127.0.0.1")
    srv.add_argument("--port", type=int, default=0, help="默认 AUTOPILOT_INTENT_WEBHOOK_PORT 或 8765")
    srv.add_argument("--secret", default="", help="校验 X-MC-Signature（默认同 MC_WEBHOOK_SECRET）")
    srv.add_argument(
        "--allow-insecure",
        action="store_true",
        help="无 secret 时仅允许 loopback 监听（显式不安全模式）",
    )
    srv.add_argument("--subdir", default="", help="默认 imported_logical")
    srv.set_defaults(func=_cmd_serve_webhook)

    rev = sub.add_parser("review", help="列出最近一次运行的失败意图")
    rev.add_argument("--project", required=True, help="本地工程根目录")
    rev.add_argument("--result", default="", help="指定 result.json 路径")
    rev.set_defaults(func=_cmd_review)

    bind = sub.add_parser("bind", help="人工写入单步 Binding")
    bind.add_argument("--project", required=True)
    bind.add_argument("--logical-case-id", required=True)
    bind.add_argument("--intent-id", required=True)
    bind.add_argument("--locator", required=True)
    bind.add_argument("--platform", default="web")
    bind.add_argument("--action", default="click")
    bind.add_argument("--keyword", default="")
    bind.add_argument("--value", default="")
    bind.set_defaults(func=_cmd_bind)

    sol = sub.add_parser(
        "solidify",
        help="将 Binding 已固化的 intent_act 降级为确定性关键字步骤（D2）",
    )
    sol.add_argument("--project", required=True, help="本地工程根目录")
    sol.add_argument(
        "--logical-case-id",
        default="",
        help="单步固化时必填；与 --stable-min 互斥",
    )
    sol.add_argument(
        "--intent-id",
        default="",
        help="单步固化时必填；与 --stable-min 互斥",
    )
    sol.add_argument(
        "--stable-min",
        type=int,
        default=0,
        help="批量固化：success_streak>=N 的步（默认 0=单步模式）",
    )
    sol.add_argument("--dry-run", action="store_true", help="只检查不写文件")
    sol.set_defaults(func=_cmd_solidify)

    doc = sub.add_parser(
        "vision-doctor",
        help="检查 Vision 开关/Key/模型；可选 --ping 探测 Chat Completions",
    )
    doc.add_argument(
        "--ping",
        action="store_true",
        help="向配置的 base_url 发一次最小 chat 请求（消耗少量 token）",
    )
    doc.add_argument(
        "--json",
        action="store_true",
        help="输出 JSON 报告",
    )
    doc.set_defaults(func=_cmd_vision_doctor)

    return p


def _cmd_vision_doctor(args: argparse.Namespace) -> int:
    # 延迟：vision-doctor 子命令才探测 Vision 配置/可选 ping
    from .vision_doctor import format_doctor_report, run_vision_doctor

    report = run_vision_doctor(ping=bool(getattr(args, "ping", False)))
    if getattr(args, "json", False):
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(format_doctor_report(report))
    return 0 if report.get("ok") else 1


def _cmd_solidify(args: argparse.Namespace) -> int:
    # 延迟：solidify 子命令才固化绑定
    from .solidify import solidify_intent_step, solidify_stable

    dry = bool(getattr(args, "dry_run", False))
    stable_min = int(getattr(args, "stable_min", 0) or 0)
    if stable_min > 0:
        out = solidify_stable(args.project, min_streak=stable_min, dry_run=dry)
    else:
        lid = str(getattr(args, "logical_case_id", "") or "").strip()
        iid = str(getattr(args, "intent_id", "") or "").strip()
        if not lid or not iid:
            print(
                json.dumps(
                    {
                        "ok": False,
                        "message": "单步模式需要 --logical-case-id 与 --intent-id；"
                        "批量请用 --stable-min N",
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 2
        out = solidify_intent_step(args.project, lid, iid, dry_run=dry)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out.get("ok") else 1


def main(argv: list[str] | None = None) -> int:
    load_project_dotenv()
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
