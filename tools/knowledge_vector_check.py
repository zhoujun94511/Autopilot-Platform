#!/usr/bin/env python3
"""巡检 Platform 本地 SQLite 向量索引（BLOB + FTS5）。

默认只读 ``data/rag_index/vectors.sqlite``（可用 ``MC_DATA_DIR`` 覆盖）。
可选 ``--compare-db``：对照主库 ``design_knowledge_items``。

用法：
  .venv/Scripts/python.exe tools/knowledge_vector_check.py
  .venv/Scripts/python.exe tools/knowledge_vector_check.py --project-id demo
  .venv/Scripts/python.exe tools/knowledge_vector_check.py --compare-db
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def _platform_data_root() -> Path:
    from autopilot_platform.platform.core.settings import data_dir

    return data_dir()


def default_vector_db() -> Path:
    return _platform_data_root() / "rag_index" / "vectors.sqlite"


def default_platform_db() -> Path:
    return _platform_data_root() / "autopilot_platform.db"


def open_vec(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise SystemExit(f"向量库不存在: {path}")
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def _blob_dim(buf: bytes | None) -> int:
    if not buf:
        return 0
    return len(buf) // 4


def _table_cols(conn: sqlite3.Connection, table: str) -> set[str]:
    try:
        return {str(r[1]) for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    except sqlite3.OperationalError:
        return set()


def summarize_index(conn: sqlite3.Connection, project_id: str = "") -> dict[str, Any]:
    conn.row_factory = sqlite3.Row
    cols = _table_cols(conn, "index_items")
    if "embedding" not in cols:
        raise SystemExit("向量库 schema 非 BLOB 形态（缺少 embedding 列），请重建索引")

    where = ""
    args: list[str] = []
    if project_id.strip():
        where = " WHERE project_id=?"
        args = [project_id.strip()]

    projects = [
        str(r[0])
        for r in conn.execute(
            f"SELECT DISTINCT project_id FROM index_items{where} ORDER BY 1", args
        ).fetchall()
    ]
    meta_projects = [
        str(r[0])
        for r in conn.execute("SELECT project_id FROM project_meta ORDER BY 1").fetchall()
    ]
    if project_id.strip():
        pid = project_id.strip()
        projects = [p for p in projects if p == pid]
        meta_projects = [p for p in meta_projects if p == pid]

    all_pids = sorted(set(projects) | set(meta_projects))
    per: list[dict[str, Any]] = []
    empty_vecs = 0
    bad_vecs = 0
    total_items = 0
    fts_rows = 0

    try:
        fts_where = ""
        fts_args: list[str] = []
        if project_id.strip():
            fts_where = " WHERE project_id=?"
            fts_args = [project_id.strip()]
        fts_rows = int(
            conn.execute(
                f"SELECT COUNT(*) FROM knowledge_fts{fts_where}", fts_args
            ).fetchone()[0]
        )
        fts_ok = True
    except sqlite3.OperationalError:
        fts_ok = False

    meta_cols = _table_cols(conn, "project_meta")
    for pid in all_pids:
        rows = conn.execute(
            "SELECT item_id, title, category, content_hash, embedding, content "
            "FROM index_items WHERE project_id=?",
            (pid,),
        ).fetchall()
        if "embedding_dim" in meta_cols:
            meta = conn.execute(
                "SELECT embedder, embedding_dim FROM project_meta WHERE project_id=?",
                (pid,),
            ).fetchone()
        else:
            meta = conn.execute(
                "SELECT embedder FROM project_meta WHERE project_id=?",
                (pid,),
            ).fetchone()
        embedder = str(meta["embedder"]) if meta else ""
        meta_dim = 0
        if meta and "embedding_dim" in meta.keys():
            meta_dim = int(meta["embedding_dim"] or 0)

        empty = 0
        bad = 0
        dims: set[int] = set()
        missing_content = 0
        for row in rows:
            total_items += 1
            emb = row["embedding"]
            dim = _blob_dim(emb)
            if dim <= 0:
                empty += 1
                empty_vecs += 1
            else:
                dims.add(dim)
                if emb and len(emb) % 4 != 0:
                    bad += 1
                    bad_vecs += 1
            if not str(row["content"] or "").strip():
                missing_content += 1

        per.append(
            {
                "project_id": pid,
                "embedder": embedder,
                "embedding_dim": meta_dim or (next(iter(dims)) if len(dims) == 1 else 0),
                "items": len(rows),
                "empty_vectors": empty,
                "bad_vectors": bad,
                "dim_variants": sorted(dims),
                "missing_content": missing_content,
            }
        )

    return {
        "vector_db": str(default_vector_db()),
        "schema": "blob_v2",
        "fts5": {"available": fts_ok, "rows": fts_rows},
        "projects": len(all_pids),
        "total_items": total_items,
        "empty_vectors": empty_vecs,
        "bad_vectors": bad_vecs,
        "by_project": per,
    }


def compare_with_platform_db(
    vec: sqlite3.Connection,
    platform_db: Path,
    project_id: str = "",
) -> dict[str, Any]:
    if not platform_db.is_file():
        return {"error": f"主库不存在: {platform_db}"}
    vec.row_factory = sqlite3.Row
    pconn = sqlite3.connect(str(platform_db))
    pconn.row_factory = sqlite3.Row
    try:
        tables = {
            r[0]
            for r in pconn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if "design_knowledge_items" not in tables:
            return {"error": "主库无 design_knowledge_items 表"}

        where = ""
        args: list[str] = []
        if project_id.strip():
            where = " WHERE project_id=?"
            args = [project_id.strip()]
        kb_rows = pconn.execute(
            f"SELECT id, project_id, title FROM design_knowledge_items{where}", args
        ).fetchall()
        kb_by_proj: dict[str, set[str]] = {}
        for r in kb_rows:
            kb_by_proj.setdefault(str(r["project_id"]), set()).add(str(r["id"]))

        idx_where = ""
        idx_args: list[str] = []
        if project_id.strip():
            idx_where = " WHERE project_id=?"
            idx_args = [project_id.strip()]
        idx_rows = vec.execute(
            f"SELECT project_id, item_id FROM index_items{idx_where}", idx_args
        ).fetchall()
        idx_by_proj: dict[str, set[str]] = {}
        for r in idx_rows:
            idx_by_proj.setdefault(str(r["project_id"]), set()).add(str(r["item_id"]))

        pids = sorted(set(kb_by_proj) | set(idx_by_proj))
        orphan_index: list[dict[str, str]] = []
        missing_index: list[dict[str, str]] = []
        for pid in pids:
            kb_ids = kb_by_proj.get(pid, set())
            idx_ids = idx_by_proj.get(pid, set())
            for iid in sorted(idx_ids - kb_ids):
                orphan_index.append({"project_id": pid, "item_id": iid})
            for iid in sorted(kb_ids - idx_ids):
                missing_index.append({"project_id": pid, "item_id": iid})

        return {
            "platform_db": str(platform_db),
            "knowledge_rows": len(kb_rows),
            "index_rows": len(idx_rows),
            "orphan_in_index": orphan_index[:50],
            "orphan_in_index_total": len(orphan_index),
            "missing_from_index": missing_index[:50],
            "missing_from_index_total": len(missing_index),
        }
    finally:
        pconn.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="巡检 Platform SQLite 向量索引")
    ap.add_argument("--vector-db", default="", help="vectors.sqlite 路径")
    ap.add_argument("--project-id", default="")
    ap.add_argument("--compare-db", action="store_true", help="对照主库知识条目")
    ap.add_argument("--db", default="", help="主库 sqlite 路径（配合 --compare-db）")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    vpath = Path(args.vector_db) if args.vector_db else default_vector_db()
    report: dict[str, Any] = {}
    try:
        conn = open_vec(vpath)
    except SystemExit as e:
        if args.json:
            print(json.dumps({"error": str(e)}, ensure_ascii=False))
        else:
            print(e)
        return 1

    try:
        try:
            summary = summarize_index(conn, args.project_id)
        except SystemExit as e:
            if args.json:
                print(json.dumps({"error": str(e)}, ensure_ascii=False))
            else:
                print(e)
            return 1
        summary["vector_db"] = str(vpath.resolve())
        report["summary"] = summary
        if args.compare_db:
            pdb = Path(args.db) if args.db else default_platform_db()
            report["compare"] = compare_with_platform_db(conn, pdb, args.project_id)
    finally:
        conn.close()

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        s = report["summary"]
        print("== Knowledge vector index check ==")
        print(f"db: {s['vector_db']}")
        print(f"schema: {s['schema']}")
        fts = s.get("fts5") or {}
        print(f"fts5: available={fts.get('available')} rows={fts.get('rows')}")
        print(
            f"projects={s['projects']} items={s['total_items']} "
            f"empty_vectors={s['empty_vectors']} bad_vectors={s['bad_vectors']}"
        )
        for p in s["by_project"]:
            print(
                f"  - {p['project_id']}: items={p['items']} "
                f"empty={p['empty_vectors']} bad={p['bad_vectors']} "
                f"dim={p.get('embedding_dim') or '-'} "
                f"embedder={p['embedder'] or '-'}"
            )
        if "compare" in report:
            c = report["compare"]
            if c.get("error"):
                print(f"compare: ERROR {c['error']}")
            else:
                print(f"\ncompare vs {c['platform_db']}")
                print(
                    f"  knowledge_rows={c['knowledge_rows']} index_rows={c['index_rows']}"
                )
                print(
                    f"  orphan_in_index={c['orphan_in_index_total']} "
                    f"missing_from_index={c['missing_from_index_total']}"
                )

    if report["summary"]["bad_vectors"]:
        return 1
    if report.get("compare", {}).get("error"):
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError, ValueError):
        pass
    raise SystemExit(main())
