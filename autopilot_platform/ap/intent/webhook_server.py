"""IDE / 本地 Runner 接收 Platform 设计域 webhook（logical_case.approved）。

Quickstart（G8）::

  # 1) IDE 工程目录
  python -m autopilot.intent serve-webhook --project <工程> --port 8765

  # 2) Platform 运维或 .env
  MC_DESIGN_WEBHOOK_URL=http://127.0.0.1:8765/hooks/intent
  MC_WEBHOOK_SECRET=<可选，与 --secret 一致>

  # 3) Web APPROVED → 写入 <工程>/imported_logical/
  # 4) import/watch 建议 --sync-status 回写 INTENT_READY

无 Webhook：``python -m autopilot.intent watch --project <工程> --project-id <id> --sync-status``
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, cast
from urllib.parse import urlparse

log = logging.getLogger(__name__)


def _import_session_from_env() -> dict[str, str] | None:
    """可选：AUTOPILOT_IMPORT_PACKAGE / AUTOPILOT_IMPORT_PLATFORM 注入会话前置。"""

    pkg = (os.environ.get("AUTOPILOT_IMPORT_PACKAGE") or "").strip()
    if not pkg:
        return None
    plat = (os.environ.get("AUTOPILOT_IMPORT_PLATFORM") or "android").strip() or "android"
    act = (os.environ.get("AUTOPILOT_IMPORT_ACTIVITY") or "").strip()
    out: dict[str, str] = {"platform": plat, "package_name": pkg}
    if act:
        out["main_activity"] = act
    return out


def verify_signature(
    body: bytes,
    secret: str,
    header_value: str,
    *,
    allow_insecure: bool = False,
) -> bool:
    """校验 X-MC-Signature。无 secret 时默认拒绝；仅显式 allow_insecure 才放行。"""
    if not secret:
        return bool(allow_insecure)
    expected = "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    got = (header_value or "").strip()
    return hmac.compare_digest(expected, got)


def handle_design_event(
    payload: dict[str, Any],
    *,
    project_dir: str,
    subdir: str = "imported_logical",
    on_imported: Callable[[list[Path]], None] | None = None,
) -> dict[str, Any]:
    """处理 logical_case.approved：写入可跑草稿。"""
    event = str(payload.get("event") or "")
    if event not in ("logical_case.approved", "design.logical_case.approved"):
        return {"ok": True, "skipped": True, "reason": f"ignored event {event}"}

    case = payload.get("case")
    if not isinstance(case, dict):
        return {"ok": False, "error": "missing case"}

    from ..mgmt.logical_import import write_logical_cases_as_drafts
    from .watch import load_seen_ids, save_seen_ids

    session = _import_session_from_env()
    paths = write_logical_cases_as_drafts(
        project_dir,
        [case],
        project_id=str(payload.get("project_id") or case.get("project_id") or ""),
        subdir=subdir,
        session=session,
    )
    cid = str(case.get("logical_case_id") or case.get("id") or "").strip()
    if cid:
        seen = load_seen_ids(project_dir)
        seen.add(cid)
        save_seen_ids(project_dir, seen)
    if on_imported:
        on_imported(paths)
    return {
        "ok": True,
        "imported": len(paths),
        "paths": [str(p) for p in paths],
        "logical_case_id": cid,
    }


def make_handler(
    *,
    project_dir: str,
    secret: str = "",
    subdir: str = "imported_logical",
    on_imported: Callable[[list[Path]], None] | None = None,
    allow_insecure: bool = False,
):
    root = str(Path(project_dir).resolve())
    insecure_ok = bool(allow_insecure) and not (secret or "").strip()

    # noinspection PyPep8Naming
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args) -> None:  # noqa: A003
            log.info("%s - %s", self.address_string(), fmt % args)

        def _json(self, code: int, obj: dict[str, Any]) -> None:
            raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path in ("/", "/health", "/hooks/intent"):
                self._json(200, {"ok": True, "service": "autopilot-intent-webhook"})
                return
            self._json(404, {"ok": False, "error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path not in ("/hooks/intent", "/webhook", "/"):
                self._json(404, {"ok": False, "error": "not found"})
                return
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length > 0 else b"{}"
            sig = self.headers.get("X-MC-Signature") or self.headers.get("x-mc-signature") or ""
            if not verify_signature(body, secret, sig, allow_insecure=insecure_ok):
                self._json(401, {"ok": False, "error": "invalid signature"})
                return
            try:
                payload = json.loads(body.decode("utf-8") or "{}")
            except json.JSONDecodeError:
                self._json(400, {"ok": False, "error": "invalid json"})
                return
            if not isinstance(payload, dict):
                self._json(400, {"ok": False, "error": "payload must be object"})
                return
            try:
                result = handle_design_event(
                    payload,
                    project_dir=root,
                    subdir=subdir,
                    on_imported=on_imported,
                )
            except (OSError, RuntimeError, TypeError, ValueError, KeyError) as exc:
                log.exception("handle design event failed")
                self._json(500, {"ok": False, "error": str(exc)})
                return
            code = 200 if result.get("ok") else 400
            self._json(code, result)

    return Handler


def serve_webhook(
    *,
    project_dir: str,
    host: str = "127.0.0.1",
    port: int = 8765,
    secret: str = "",
    subdir: str = "imported_logical",
    blocking: bool = True,
    allow_insecure: bool = False,
) -> ThreadingHTTPServer:
    loopback = (host or "").strip().lower() in ("127.0.0.1", "::1", "localhost")
    sec = (secret or "").strip()
    if not sec:
        if not (allow_insecure and loopback):
            raise ValueError(
                "webhook 需要 --secret；仅 loopback 且显式 --allow-insecure 时可无密钥"
            )
        log.warning(
            "intent webhook running without secret on %s (allow_insecure); "
            "do not expose beyond localhost",
            host,
        )
    handler = cast(
        type[BaseHTTPRequestHandler],
        make_handler(
            project_dir=project_dir,
            secret=sec,
            subdir=subdir,
            allow_insecure=bool(allow_insecure and loopback and not sec),
        ),
    )
    # noinspection PyTypeChecker
    server = ThreadingHTTPServer((host, int(port)), handler)
    log.info("intent webhook listening on http://%s:%s/hooks/intent", host, port)
    if blocking:
        server.serve_forever()
    else:
        t = threading.Thread(target=server.serve_forever, daemon=True, name="intent-webhook")
        t.start()
    return server
