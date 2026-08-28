#!/usr/bin/env python3
"""批量导入知识库文件到 Platform（HTTP），改造自 TestPilot batch_import_knowledge。

调用 POST /api/v1/design/knowledge/import（multipart），按项目写入 KnowledgeItem。

用法：
  .venv/Scripts/python.exe tools/batch_import_knowledge.py --project-id demo --dir ./kb
  .venv/Scripts/python.exe tools/batch_import_knowledge.py --project-id demo --dir ./kb --dry-run
  .venv/Scripts/python.exe tools/batch_import_knowledge.py --project-id demo --file a.md --file b.txt
  .venv/Scripts/python.exe tools/batch_import_knowledge.py --project-id demo --dir ./kb --pattern \"API\"

环境变量：AP_SMOKE_BASE_URL / AP_SMOKE_USER / AP_SMOKE_PASSWORD（与 smoke_http 共用）
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.smoke_http import DEFAULT_BASE, SmokeContext, _request  # noqa: E402

ALLOWED_EXT = {".txt", ".md", ".csv", ".json", ".docx", ".pdf", ".yaml", ".yml"}


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


def collect_files(paths: list[Path], pattern: str) -> list[Path]:
    out: list[Path] = []
    for p in paths:
        if p.is_file():
            out.append(p)
            continue
        if not p.is_dir():
            continue
        for f in sorted(p.rglob("*")):
            if not f.is_file():
                continue
            if f.suffix.lower() not in ALLOWED_EXT:
                continue
            if pattern and pattern.lower() not in f.name.lower() and pattern.lower() not in str(f).lower():
                continue
            out.append(f)
    # 去重
    seen: set[str] = set()
    uniq: list[Path] = []
    for f in out:
        key = str(f.resolve())
        if key in seen:
            continue
        seen.add(key)
        uniq.append(f)
    return uniq


def build_multipart(
    *,
    project_id: str,
    category: str,
    confirmed: bool,
    description: str,
    files: list[Path],
) -> tuple[bytes, str]:
    boundary = f"----apImport{uuid.uuid4().hex}"
    chunks: list[bytes] = []

    def add_field(name: str, value: str) -> None:
        chunks.append(f"--{boundary}\r\n".encode())
        chunks.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        chunks.append(value.encode("utf-8"))
        chunks.append(b"\r\n")

    add_field("project_id", project_id)
    add_field("category", category)
    add_field("confirmed", "true" if confirmed else "false")
    add_field("description", description)

    for f in files:
        raw = f.read_bytes()
        ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
        chunks.append(f"--{boundary}\r\n".encode())
        disp = f'Content-Disposition: form-data; name="files"; filename="{f.name}"\r\n'
        chunks.append(disp.encode("utf-8"))
        chunks.append(f"Content-Type: {ctype}\r\n\r\n".encode())
        chunks.append(raw)
        chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), boundary


def post_import(ctx: SmokeContext, body: bytes, boundary: str) -> tuple[int, object]:
    import urllib.request

    url = f"{ctx.base_url}/api/v1/design/knowledge/import"
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {ctx.token}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return resp.status, json.loads(raw) if raw else None
    except Exception as e:  # noqa: BLE001
        if hasattr(e, "code"):
            raw = e.read().decode("utf-8", errors="replace") if hasattr(e, "read") else ""
            try:
                payload = json.loads(raw) if raw else str(e)
            except json.JSONDecodeError:
                payload = raw or str(e)
            return int(e.code), payload  # type: ignore[arg-type]
        raise


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="批量导入知识库到 Platform")
    ap.add_argument("--base-url", default=DEFAULT_BASE)
    ap.add_argument("--user", default=os.environ.get("AP_SMOKE_USER", "admin"))
    ap.add_argument("--password", default=os.environ.get("AP_SMOKE_PASSWORD", "admin"))
    ap.add_argument("--project-id", required=True)
    ap.add_argument("--dir", action="append", default=[], help="知识文件目录（可多次）")
    ap.add_argument("--file", action="append", default=[], help="单文件（可多次）")
    ap.add_argument("--pattern", default="", help="文件名/路径包含该关键字才导入")
    ap.add_argument("--category", default="other")
    ap.add_argument("--description", default="")
    ap.add_argument("--unconfirmed", action="store_true", help="导入为未确认")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--list", action="store_true", help="仅列出将导入的文件")
    args = ap.parse_args(argv)

    paths = [Path(p) for p in (args.dir or [])] + [Path(p) for p in (args.file or [])]
    if not paths:
        print("请指定 --dir 或 --file", file=sys.stderr)
        return 2

    files = collect_files(paths, args.pattern.strip())
    print(f"候选文件: {len(files)}")
    for f in files:
        print(f"  - {f}")
    if args.list or args.dry_run:
        print("dry-run/list：未调用导入 API")
        return 0
    if not files:
        print("无文件可导入")
        return 1

    ctx = SmokeContext(base_url=args.base_url.rstrip("/"), user=args.user, password=args.password)
    login(ctx)
    body, boundary = build_multipart(
        project_id=args.project_id.strip(),
        category=args.category,
        confirmed=not args.unconfirmed,
        description=args.description,
        files=files,
    )
    code, payload = post_import(ctx, body, boundary)
    print(f"HTTP {code}")
    print(json.dumps(payload, ensure_ascii=False, indent=2) if not isinstance(payload, str) else payload)
    return 0 if code in (200, 201) else 1


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError, ValueError):
        pass
    raise SystemExit(main())
