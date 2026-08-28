"""OpenAPI 3.x / Postman Collection v2.1 → 确定性 HTTP `.tc.yaml`（路线图 C2 / ImportBridge）。

不做双向同步、不做 Postman 脚本引擎；仅生成可跑关键字步骤：
  http_session_begin → http_{method} → http_assert_status → http_session_end
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

# noinspection PyUnresolvedReferences
import yaml

from ..intent.bindings import upsert_step_binding

_HTTP_METHODS = ("get", "post", "put", "patch", "delete", "head", "options")


def _safe_name(text: str, fallback: str = "api") -> str:
    base = re.sub(r"[^\w.\-\u4e00-\u9fff]+", "_", (text or "").strip()).strip("._")
    return (base or fallback)[:80]


def _load_spec(path: Path) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8")
    if path.suffix.lower() in (".yaml", ".yml"):
        data = yaml.safe_load(raw)
    else:
        data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("规格根节点必须是对象")
    return data


def _detect_kind(spec: dict[str, Any]) -> str:
    if str(spec.get("openapi") or "").startswith("3"):
        return "openapi"
    if "swagger" in spec and str(spec.get("swagger") or "").startswith("2"):
        return "openapi"  # 最小兼容：当 OpenAPI paths 用
    info = spec.get("info") if isinstance(spec.get("info"), dict) else {}
    schema = str(info.get("schema") or spec.get("schema") or "")
    if "collection" in schema.lower() or (
        isinstance(spec.get("item"), list) and info.get("name")
    ):
        return "postman"
    if isinstance(spec.get("paths"), dict):
        return "openapi"
    raise ValueError("无法识别规格：需要 OpenAPI 3.x（paths）或 Postman Collection v2.x（item）")


def _openapi_base_url(spec: dict[str, Any]) -> str:
    servers = spec.get("servers") if isinstance(spec.get("servers"), list) else []
    for s in servers:
        if isinstance(s, dict):
            url = str(s.get("url") or "").strip()
            if url:
                return url.rstrip("/")
    # swagger2
    host = str(spec.get("host") or "").strip()
    base = str(spec.get("basePath") or "").strip()
    schemes = spec.get("schemes") if isinstance(spec.get("schemes"), list) else []
    scheme = str(schemes[0] if schemes else "https")
    if host:
        return f"{scheme}://{host}{base}".rstrip("/")
    return "${base_url}"


def _iter_openapi_ops(spec: dict[str, Any]) -> list[dict[str, Any]]:
    paths = spec.get("paths") if isinstance(spec.get("paths"), dict) else {}
    ops: list[dict[str, Any]] = []
    for path, item in paths.items():
        if not isinstance(item, dict):
            continue
        for method in _HTTP_METHODS:
            op = item.get(method)
            if not isinstance(op, dict):
                continue
            op_id = str(op.get("operationId") or "").strip()
            summary = str(op.get("summary") or op.get("description") or "").strip()
            # 成功响应码启发
            responses = op.get("responses") if isinstance(op.get("responses"), dict) else {}
            status_expected = "200-299"
            for code in ("200", "201", "204", "2XX", "default"):
                if code in responses:
                    if code.isdigit():
                        status_expected = code
                    break
            ops.append(
                {
                    "method": method.upper(),
                    "path": str(path),
                    "operation_id": op_id,
                    "summary": summary or f"{method.upper()} {path}",
                    "status_expected": status_expected,
                }
            )
    return ops


def _postman_url(raw: Any) -> str:
    if isinstance(raw, str):
        return raw.strip()
    if isinstance(raw, dict):
        raw_s = str(raw.get("raw") or "").strip()
        if raw_s:
            return raw_s
        host = raw.get("host") or []
        path = raw.get("path") or []
        if isinstance(host, list):
            host_s = ".".join(str(x) for x in host)
        else:
            host_s = str(host)
        if isinstance(path, list):
            path_s = "/".join(str(x).lstrip("/") for x in path)
        else:
            path_s = str(path).lstrip("/")
        protocol = str(raw.get("protocol") or "https")
        if host_s:
            return f"{protocol}://{host_s}/{path_s}".rstrip("/")
    return ""


def _iter_postman_ops(spec: dict[str, Any], prefix: str = "") -> list[dict[str, Any]]:
    items = spec.get("item") if isinstance(spec.get("item"), list) else []
    ops: list[dict[str, Any]] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        name = str(it.get("name") or "").strip()
        if isinstance(it.get("item"), list):
            ops.extend(_iter_postman_ops(it, prefix=f"{prefix}{name}/" if name else prefix))
            continue
        req = it.get("request")
        if isinstance(req, str):
            ops.append(
                {
                    "method": "GET",
                    "path": req,
                    "operation_id": "",
                    "summary": f"{prefix}{name}" or req,
                    "status_expected": "200-299",
                }
            )
            continue
        if not isinstance(req, dict):
            continue
        method = str(req.get("method") or "GET").upper()
        url = _postman_url(req.get("url"))
        if not url:
            continue
        parsed = urlparse(url if "://" in url else f"http://local{url}")
        path = parsed.path or url
        ops.append(
            {
                "method": method if method.lower() in _HTTP_METHODS else "GET",
                "path": path if path.startswith("/") else url,
                "operation_id": "",
                "summary": f"{prefix}{name}" or f"{method} {path}",
                "status_expected": "200-299",
                "absolute_url": url if "://" in url else "",
            }
        )
    return ops


def _method_keyword(method: str) -> str:
    m = (method or "GET").strip().lower()
    if m not in _HTTP_METHODS:
        m = "get"
    return f"http_{m}"


def op_to_tc_dict(
    op: dict[str, Any],
    *,
    base_url: str,
    case_key: str = "",
    index: int = 1,
    with_intent_shell: bool = False,
) -> dict[str, Any]:
    method = str(op.get("method") or "GET").upper()
    path = str(op.get("path") or "/").strip() or "/"
    abs_url = str(op.get("absolute_url") or "").strip()
    url = abs_url or path
    summary = str(op.get("summary") or f"{method} {path}").strip()
    status_expected = str(op.get("status_expected") or "200-299")
    kid = _method_keyword(method)
    key = case_key or _safe_name(str(op.get("operation_id") or summary), f"api_{index:03d}")
    lid = f"oa-{key}"[:64]
    case_steps: list[dict[str, Any]] = []
    if with_intent_shell:
        case_steps.append(
            {
                "step": "intent_act",
                "comment": summary[:120],
                "remark": f"intent:s1|openapi:{method}:{path}",
                "is_run": True,
                "params": {
                    "intent_id": "s1",
                    "action": method.lower(),
                    "target": path,
                    "value": url,
                    "text": summary,
                    "channel": "http",
                    "logical_case_id": lid,
                },
            }
        )
    case_steps.extend(
        [
            {
                "step": kid,
                "comment": f"{method} {path}",
                "remark": f"openapi:{method}:{path}",
                "is_run": True,
                "params": {
                    "url": url,
                    "resp_code": "__http_code__",
                    "resp_body": "__http_body__",
                },
            },
            {
                "step": "http_assert_status",
                "comment": f"断言状态 {status_expected}",
                "is_run": True,
                "params": {"expected": status_expected},
            },
        ]
    )
    tc: dict[str, Any] = {
        "type": "testcase",
        "format_version": 2,
        "schema_version": "2.0",
        "logical_case_id": lid,
        "case_key": key,
        "name": summary[:120],
        "tag": "API",
        "platform": "http",
        "is_execute": True,
        "able_invoked": False,
        "datapool": "DATATABLE(NONE,false)",
        "desc": {
            "description": f"Imported {method} {path}",
        },
        "shells": {
            "before": [
                {
                    "step": "http_session_begin",
                    "comment": "开启 HTTP 会话",
                    "is_run": True,
                    "params": {
                        "base_url": base_url or "${base_url}",
                        "timeout": "20",
                    },
                }
            ],
            "case": case_steps,
            "after": [
                {
                    "step": "http_session_end",
                    "comment": "关闭 HTTP 会话",
                    "is_run": True,
                }
            ],
            "fault": [],
        },
    }
    if with_intent_shell:
        tc["_intent_binding"] = {
            "logical_case_id": lid,
            "intent_id": "s1",
            "platform": "http",
            "channel": "http",
            "method": method,
            "path": path,
            "keyword_id": kid,
            "params": {
                "url": url,
                "resp_code": "__http_code__",
                "resp_body": "__http_body__",
            },
            "resolver": "openapi_import",
        }
    return tc


def import_spec_to_cases(
    spec_path: str | Path,
    *,
    base_url: str = "",
    methods: list[str] | None = None,
    limit: int = 0,
    with_intent_shell: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """解析规格 → TC dict 列表 + meta。"""
    path = Path(spec_path)
    spec = _load_spec(path)
    kind = _detect_kind(spec)
    if kind == "openapi":
        ops = _iter_openapi_ops(spec)
        default_base = _openapi_base_url(spec)
    else:
        ops = _iter_postman_ops(spec)
        default_base = base_url or "${base_url}"
    allow = {m.lower() for m in (methods or []) if m} or set(_HTTP_METHODS)
    ops = [o for o in ops if str(o.get("method") or "").lower() in allow]
    if limit and limit > 0:
        ops = ops[: int(limit)]
    base = (base_url or default_base or "${base_url}").rstrip("/")
    cases = [
        op_to_tc_dict(
            op,
            base_url=base,
            index=i + 1,
            with_intent_shell=with_intent_shell,
        )
        for i, op in enumerate(ops)
    ]
    meta = {
        "kind": kind,
        "source": str(path),
        "base_url": base,
        "operations": len(ops),
        "cases": len(cases),
        "with_intent_shell": bool(with_intent_shell),
    }
    return cases, meta


def write_cases(
    project_dir: str | Path,
    cases: list[dict[str, Any]],
    *,
    subdir: str = "imported_api",
    write_bindings: bool = True,
) -> list[Path]:
    root = Path(project_dir)
    if not root.is_dir():
        raise NotADirectoryError(f"工程目录不存在: {root}")
    out_dir = root / subdir
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for case in cases:
        bind_meta = case.pop("_intent_binding", None) if isinstance(case, dict) else None
        name = _safe_name(str(case.get("case_key") or case.get("name") or "api"), "api")
        path = out_dir / f"{name}.tc.yaml"
        if path.exists():
            path = out_dir / f"{path.stem}_{str(case.get('logical_case_id') or '')[-8:]}{path.suffix}"
        path.write_text(
            yaml.safe_dump(case, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        written.append(path)
        if write_bindings and isinstance(bind_meta, dict) and bind_meta.get("keyword_id"):
            try:
                upsert_step_binding(
                    root,
                    str(bind_meta.get("logical_case_id") or ""),
                    str(bind_meta.get("intent_id") or "s1"),
                    platform=str(bind_meta.get("platform") or "http"),
                    keyword_id=str(bind_meta["keyword_id"]),
                    params=dict(bind_meta.get("params") or {}),
                    resolver=str(bind_meta.get("resolver") or "openapi_import"),
                    channel=str(bind_meta.get("channel") or "http"),
                    method=str(bind_meta.get("method") or ""),
                    path=str(bind_meta.get("path") or ""),
                    keep_previous=False,
                )
            except (OSError, TypeError, ValueError, ImportError):
                pass
    return written


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="autopilot.mgmt.openapi_import",
        description="OpenAPI / Postman → 确定性 HTTP .tc.yaml",
    )
    p.add_argument("--spec", required=True, help="openapi.json/.yaml 或 postman collection")
    p.add_argument("--project", required=True, help="本地工程根目录")
    p.add_argument("--subdir", default="imported_api", help="输出子目录（默认 imported_api）")
    p.add_argument("--base-url", default="", help="覆盖 servers[0] / 默认 ${base_url}")
    p.add_argument(
        "--methods",
        default="",
        help="逗号分隔方法过滤，如 get,post（默认全部）",
    )
    p.add_argument("--limit", type=int, default=0, help="最多导入条数（0=不限）")
    p.add_argument(
        "--with-intent-shell",
        action="store_true",
        help="在 HTTP 步前插入 intent_act(channel=http) 并写 Binding 占位",
    )
    p.add_argument("--dry-run", action="store_true", help="只打印统计不写文件")
    args = p.parse_args(argv)

    methods = [x.strip() for x in (args.methods or "").split(",") if x.strip()]
    try:
        cases, meta = import_spec_to_cases(
            args.spec,
            base_url=args.base_url,
            methods=methods or None,
            limit=int(args.limit or 0),
            with_intent_shell=bool(args.with_intent_shell),
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError, yaml.YAMLError) as exc:
        print(f"导入失败: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(meta, ensure_ascii=False, indent=2))
    if args.dry_run:
        for c in cases[:20]:
            print(f"  - {c.get('name')} ({c.get('case_key')})")
        if len(cases) > 20:
            print(f"  … 共 {len(cases)} 条")
        return 0

    paths = write_cases(args.project, cases, subdir=args.subdir)
    print(f"写入 {len(paths)} 个用例 → {Path(args.project) / args.subdir}")
    for path in paths[:30]:
        print(f"  {path}")
    if len(paths) > 30:
        print(f"  … 其余 {len(paths) - 30} 个省略")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
