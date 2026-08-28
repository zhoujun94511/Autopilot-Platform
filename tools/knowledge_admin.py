#!/usr/bin/env python3
"""知识库运维 CLI：列表 / 统计 / 检索 / 重建向量索引。

改造自 TestPilot ``check_knowledge_base`` + ``clear_and_rebuild``；通过 **已启动的 Platform HTTP API**
操作设计域知识库（``design_knowledge_items`` 主库 + ``data/rag_index/vectors.sqlite`` 向量索引）。

前置条件：
  - Platform 进程已运行（默认 ``http://127.0.0.1:8000``，HTTPS 联调时改 ``--base-url``）
  - 账号能登录且对 ``--project-id`` 有知识库读写权限（默认 admin）
  - ``rebuild`` / ``search`` 依赖 RAG 嵌入配置（``AP_RAG_EMBEDDER`` 等，见 ``.env``）

与相关工具分工：
  - ``batch_import_knowledge.py`` — 从本地目录批量 **导入** 文件到知识库
  - ``knowledge_admin.py``（本脚本）— 对已入库条目 **列表 / 检索 / 重建索引**
  - ``knowledge_vector_check.py`` — **离线** 巡检 vectors.sqlite（无需 HTTP）

用法（Windows；Linux/macOS 将路径改为 ``.venv/bin/python``）：

  # 公共参数（所有子命令必需/可选）：
  #   --project-id <pid>   项目空间 ID（必填）
  #   --base-url URL       Platform 根地址（默认 AP_SMOKE_BASE_URL 或 http://127.0.0.1:8000）
  #   --user / --password  登录账号（默认 AP_SMOKE_USER / AP_SMOKE_PASSWORD 或 admin/admin）

  # list — 分页列出该项目已入库的知识条目（id 前缀、分类、是否 confirmed、标题）
  .venv/Scripts/python.exe tools/knowledge_admin.py --project-id demo list
  .venv/Scripts/python.exe tools/knowledge_admin.py --project-id demo list --page-size 100

  # stats — 条目总数 + 尝试拉取 /api/v1/ops/rag-health（admin 可见嵌入/索引健康度）
  .venv/Scripts/python.exe tools/knowledge_admin.py --project-id demo stats

  # search — 调用混合检索 API，打印命中标题与 score（调 RAG 召回质量）
  .venv/Scripts/python.exe tools/knowledge_admin.py --project-id demo search --query "登录"
  .venv/Scripts/python.exe tools/knowledge_admin.py --project-id demo search --query "登录" --top-k 10

  # rebuild — 按主库 confirmed 条目重建该项目向量索引（默认先 clear_all 再写入）
  .venv/Scripts/python.exe tools/knowledge_admin.py --project-id demo rebuild
  .venv/Scripts/python.exe tools/knowledge_admin.py --project-id demo rebuild --no-clear
      # 增量重建：不清空现有 index_items 再写（异常时慎用，一般仍用默认全量 clear）

环境变量：
  AP_SMOKE_BASE_URL   Platform 根 URL（与 smoke_http 共用）
  AP_SMOKE_USER       登录用户名
  AP_SMOKE_PASSWORD   登录密码
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.smoke_http import DEFAULT_BASE, SmokeContext, _request  # noqa: E402


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


def cmd_list(ctx: SmokeContext, project_id: str, page_size: int) -> int:
    qs = urlencode({"project_id": project_id, "page": 1, "page_size": page_size})
    code, body, _ = _request(ctx, "GET", f"/api/v1/design/knowledge?{qs}")
    print(f"HTTP {code}")
    if code != 200:
        print(body)
        return 1
    items: list[Any]
    if isinstance(body, list):
        items = body
        total = len(body)
    elif isinstance(body, dict):
        items = list(body.get("items") or [])
        total = int(body.get("total") or len(items))
    else:
        print(body)
        return 1
    print(f"total={total} showing={len(items)}")
    for it in items:
        if not isinstance(it, dict):
            continue
        print(
            f"  - {it.get('id', '')[:8]}…  [{it.get('category')}]  "
            f"{'✓' if it.get('confirmed') else '·'}  {it.get('title')}"
        )
    return 0


def cmd_stats(ctx: SmokeContext, project_id: str) -> int:
    qs = urlencode({"project_id": project_id, "page": 1, "page_size": 1})
    code, body, _ = _request(ctx, "GET", f"/api/v1/design/knowledge?{qs}")
    if code != 200:
        print(f"HTTP {code} {body}")
        return 1
    total = 0
    if isinstance(body, dict):
        total = int(body.get("total") or 0)
    elif isinstance(body, list):
        total = len(body)
    # rag-health 可能仅 admin
    rh_code, rh_body, _ = _request(ctx, "GET", "/api/v1/ops/rag-health")
    print(f"project_id={project_id}")
    print(f"knowledge_items={total}")
    print(f"rag_health_http={rh_code}")
    if rh_code == 200:
        print(json.dumps(rh_body, ensure_ascii=False, indent=2))
    return 0


def cmd_rebuild(ctx: SmokeContext, project_id: str, clear_all: bool) -> int:
    code, body, _ = _request(
        ctx,
        "POST",
        "/api/v1/design/knowledge/rebuild",
        body={"project_id": project_id, "clear_all": clear_all},
    )
    print(f"HTTP {code}")
    print(json.dumps(body, ensure_ascii=False, indent=2) if not isinstance(body, str) else body)
    return 0 if code == 200 else 1


def cmd_search(ctx: SmokeContext, project_id: str, query: str, top_k: int) -> int:
    code, body, _ = _request(
        ctx,
        "POST",
        "/api/v1/design/knowledge/search",
        body={
            "project_id": project_id,
            "query": query,
            "top_k": top_k,
            "score_threshold": 0.0,
            "confirmed_only": False,
        },
    )
    print(f"HTTP {code}")
    if code != 200:
        print(body)
        return 1
    docs = (body or {}).get("documents") if isinstance(body, dict) else []
    print(f"engine={body.get('engine') if isinstance(body, dict) else ''} hits={len(docs or [])}")
    for d in docs or []:
        if not isinstance(d, dict):
            continue
        print(f"  - score={d.get('score')}  {d.get('title')}")
    return 0


def main(argv: list[str] | None = None) -> int:
    epilog = """
子命令速查（详见脚本顶部 docstring）：
  list     GET  /design/knowledge — 分页列条目
  stats    条目 total + GET /ops/rag-health（admin）
  search   POST /design/knowledge/search — 混合检索试跑
  rebuild  POST /design/knowledge/rebuild — 重建 vectors.sqlite 中该项目索引

相关：batch_import_knowledge.py（导入）| knowledge_vector_check.py（离线向量库巡检）
"""
    ap = argparse.ArgumentParser(
        description="Platform 设计域知识库运维（HTTP API；需 Platform 已启动）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=epilog,
    )
    ap.add_argument(
        "--base-url",
        default=DEFAULT_BASE,
        help="Platform 根 URL（默认 AP_SMOKE_BASE_URL 或 http://127.0.0.1:8000）",
    )
    ap.add_argument(
        "--user",
        default=os.environ.get("AP_SMOKE_USER", "admin"),
        help="登录用户名（默认 AP_SMOKE_USER 或 admin）",
    )
    ap.add_argument(
        "--password",
        default=os.environ.get("AP_SMOKE_PASSWORD", "admin"),
        help="登录密码（默认 AP_SMOKE_PASSWORD 或 admin）",
    )
    ap.add_argument(
        "--project-id",
        required=True,
        help="项目空间 ID（所有子命令作用于该项目知识库）",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser(
        "list",
        help="GET /design/knowledge — 分页列出知识条目",
    )
    p_list.add_argument(
        "--page-size",
        type=int,
        default=50,
        help="每页条数（默认 50）",
    )

    sub.add_parser(
        "stats",
        help="条目 total + GET /ops/rag-health（需 admin 才返回 200）",
    )

    p_rebuild = sub.add_parser(
        "rebuild",
        help="POST /design/knowledge/rebuild — 重建该项目向量索引",
    )
    p_rebuild.add_argument(
        "--no-clear",
        action="store_true",
        help="rebuild 时不清空现有 index_items（默认 clear_all=true 全量重建）",
    )

    p_search = sub.add_parser(
        "search",
        help="POST /design/knowledge/search — 混合检索试跑",
    )
    p_search.add_argument("--query", required=True, help="检索问句/关键词")
    p_search.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="返回条数上限（默认 5）",
    )

    args = ap.parse_args(argv)
    ctx = SmokeContext(base_url=args.base_url.rstrip("/"), user=args.user, password=args.password)
    login(ctx)
    pid = args.project_id.strip()
    if args.cmd == "list":
        return cmd_list(ctx, pid, args.page_size)
    if args.cmd == "stats":
        return cmd_stats(ctx, pid)
    if args.cmd == "rebuild":
        return cmd_rebuild(ctx, pid, clear_all=not args.no_clear)
    if args.cmd == "search":
        return cmd_search(ctx, pid, args.query, args.top_k)
    return 2


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError, ValueError):
        pass
    raise SystemExit(main())
