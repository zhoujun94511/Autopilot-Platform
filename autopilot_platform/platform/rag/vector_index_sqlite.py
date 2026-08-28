"""知识向量索引：本地 SQLite + FTS5 +（可选）sqlite-vec。

- 向量 float32 BLOB；FTS5 召回；sqlite-vec / Python 精排
- 单库多项目（``project_id``）
- 嵌入器本地/远程由 ``embedder_factory`` 决定（hashing | openai | auto）
"""

from __future__ import annotations

import logging
import math
import os
import re
import sqlite3
import struct
import threading
from pathlib import Path
from typing import Any, Sequence

logger = logging.getLogger(__name__)
_lock = threading.RLock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS project_meta (
  project_id TEXT PRIMARY KEY,
  embedder TEXT NOT NULL DEFAULT '',
  embedding_dim INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS index_items (
  project_id TEXT NOT NULL,
  item_id TEXT NOT NULL,
  content_hash TEXT NOT NULL DEFAULT '',
  title TEXT NOT NULL DEFAULT '',
  category TEXT NOT NULL DEFAULT '',
  content TEXT NOT NULL DEFAULT '',
  embedding BLOB,
  PRIMARY KEY (project_id, item_id)
);
CREATE INDEX IF NOT EXISTS idx_items_project ON index_items(project_id);
"""


from ..core.settings import data_dir


def db_path() -> Path:
    d = data_dir() / "rag_index"
    d.mkdir(parents=True, exist_ok=True)
    return d / "vectors.sqlite"


def _cfg_bool(name: str, default: str = "1") -> bool:
    return (os.environ.get(name) or default).strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
        "",
    )


def _cfg_int(name: str, default: int) -> int:
    try:
        return int((os.environ.get(name) or str(default)).strip())
    except ValueError:
        return default


def hybrid_enabled() -> bool:
    try:
        from ..ops.runtime_config import cfg_bool

        return cfg_bool("AP_RAG_HYBRID", "1")
    except (ImportError, AttributeError, TypeError, ValueError, RuntimeError):
        return _cfg_bool("AP_RAG_HYBRID", "1")


def fts_candidate_k(top_k: int, query: str) -> int:
    try:
        from ..ops.runtime_config import cfg_int

        factor = cfg_int("AP_RAG_FTS_FACTOR", "40", minimum=5)
        max_k = cfg_int("AP_RAG_FTS_MAX_CANDIDATES", "800", minimum=50)
    except (ImportError, AttributeError, TypeError, ValueError, RuntimeError):
        factor = _cfg_int("AP_RAG_FTS_FACTOR", 40)
        max_k = _cfg_int("AP_RAG_FTS_MAX_CANDIDATES", 800)
    tokens = max(1, len(re.findall(r"\w+", query or "", flags=re.UNICODE)))
    # 长查询略增候选
    if tokens >= 8:
        factor = int(factor * 1.25)
    return max(int(top_k), min(int(top_k) * int(factor), int(max_k)))


def embedding_to_blob(vec: Sequence[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *[float(x) for x in vec])


def blob_to_embedding(buf: bytes | None) -> list[float]:
    if not buf:
        return []
    n = len(buf) // 4
    if n <= 0:
        return []
    return list(struct.unpack(f"{n}f", buf[: n * 4]))


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += float(x) * float(y)
        na += float(x) * float(x)
        nb += float(y) * float(y)
    denom = math.sqrt(na) * math.sqrt(nb)
    return (dot / denom) if denom else 0.0


def escape_fts5_query(query: str) -> str:
    """参照 TestPilot：特殊字符 / 操作符时改为短语查询。"""
    q = (query or "").strip()
    if not q:
        return '""'
    specials = set('-#:*^+@(){}"[]~')
    ops = (" AND ", " OR ", " NOT ", " NEAR ")
    q_upper = f" {q.upper()} "
    if any(ch in q for ch in specials) or any(op in q_upper for op in ops):
        inner = q.replace('"', " ")
        return f'"{inner}"'
    return q


def load_sqlite_vec(conn: sqlite3.Connection) -> bool:
    """尝试加载 sqlite-vec；成功返回 True（可调用 vec_distance_cosine）。"""
    try:
        conn.enable_load_extension(True)
    except (AttributeError, sqlite3.Error):
        return False

    path = (
        os.environ.get("AP_SQLITE_VEC_PATH")
        or os.environ.get("SQLITE_VEC_EXTENSION_PATH")
        or ""
    ).strip()
    if path and os.path.isfile(path):
        try:
            conn.load_extension(path)
        except (OSError, sqlite3.Error, AttributeError) as exc:
            logger.debug("load sqlite-vec path failed: %s", exc)

    try:
        import sqlite_vec

        if hasattr(sqlite_vec, "load"):
            sqlite_vec.load(conn)
    except (ImportError, AttributeError, OSError, sqlite3.Error):
        pass

    try:
        conn.execute("SELECT vec_version()").fetchone()
        return True
    except sqlite3.OperationalError:
        try:
            # 某些版本无 vec_version，用距离函数探测
            buf = embedding_to_blob([0.0, 1.0])
            conn.execute("SELECT vec_distance_cosine(?, ?)", (buf, buf)).fetchone()
            return True
        except sqlite3.OperationalError:
            return False


def _ensure_fts(conn: sqlite3.Connection) -> bool:
    try:
        conn.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts
            USING fts5(
                project_id UNINDEXED,
                item_id UNINDEXED,
                content,
                tokenize = 'porter unicode61'
            )
            """
        )
        return True
    except sqlite3.OperationalError as exc:
        logger.warning("FTS5 unavailable: %s", exc)
        return False


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path()), timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    _ensure_fts(conn)
    conn.commit()
    return conn


def ensure_db() -> Path:
    """Create vector index directory/file and apply schema if missing."""
    conn = _connect()
    conn.close()
    return db_path()


def load_project(project_id: str) -> dict[str, Any]:
    pid = (project_id or "").strip() or "default"
    with _lock:
        conn = _connect()
        try:
            meta = conn.execute(
                "SELECT embedder, embedding_dim FROM project_meta WHERE project_id=?",
                (pid,),
            ).fetchone()
            embedder = str(meta["embedder"]) if meta else ""
            dim = int(meta["embedding_dim"] or 0) if meta else 0
            rows = conn.execute(
                "SELECT item_id, content_hash, title, category, content, embedding "
                "FROM index_items WHERE project_id=?",
                (pid,),
            ).fetchall()
            items: dict[str, Any] = {}
            for row in rows:
                vec = blob_to_embedding(row["embedding"])
                items[str(row["item_id"])] = {
                    "content_hash": str(row["content_hash"] or ""),
                    "title": str(row["title"] or ""),
                    "category": str(row["category"] or ""),
                    "content": str(row["content"] or ""),
                    "vector": vec,
                }
                if not dim and vec:
                    dim = len(vec)
            return {
                "schema_version": 2,
                "project_id": pid,
                "embedder": embedder,
                "embedding_dim": dim,
                "items": items,
            }
        finally:
            conn.close()


def save_project(project_id: str, data: dict[str, Any]) -> Path:
    pid = (project_id or "").strip() or "default"
    embedder = str(data.get("embedder") or "")
    items = dict(data.get("items") or {})
    dim = int(data.get("embedding_dim") or 0)
    if not dim:
        for info in items.values():
            if isinstance(info, dict) and info.get("vector"):
                dim = len(info["vector"])
                break
    path = db_path()
    with _lock:
        conn = _connect()
        try:
            fts_ok = _ensure_fts(conn)
            conn.execute(
                "INSERT INTO project_meta(project_id, embedder, embedding_dim) VALUES(?,?,?) "
                "ON CONFLICT(project_id) DO UPDATE SET "
                "embedder=excluded.embedder, embedding_dim=excluded.embedding_dim",
                (pid, embedder, dim),
            )
            conn.execute("DELETE FROM index_items WHERE project_id=?", (pid,))
            if fts_ok:
                try:
                    conn.execute("DELETE FROM knowledge_fts WHERE project_id=?", (pid,))
                except sqlite3.OperationalError:
                    pass

            for rid, info in items.items():
                if not isinstance(info, dict):
                    continue
                vec = info.get("vector") or []
                title = str(info.get("title") or "")
                category = str(info.get("category") or "")
                content = str(info.get("content") or "")
                blob = embedding_to_blob(vec) if vec else None
                conn.execute(
                    "INSERT INTO index_items"
                    "(project_id, item_id, content_hash, title, category, content, embedding) "
                    "VALUES(?,?,?,?,?,?,?)",
                    (
                        pid,
                        str(rid),
                        str(info.get("content_hash") or ""),
                        title,
                        category,
                        content,
                        blob,
                    ),
                )
                if fts_ok:
                    fts_body = f"{title}\n{content}\n{category}".strip()
                    try:
                        conn.execute(
                            "INSERT INTO knowledge_fts(project_id, item_id, content) VALUES(?,?,?)",
                            (pid, str(rid), fts_body),
                        )
                    except sqlite3.OperationalError as exc:
                        logger.debug("fts insert skip: %s", exc)

            conn.commit()
        finally:
            conn.close()
    return path


def clear_project(project_id: str) -> None:
    pid = (project_id or "").strip() or "default"
    with _lock:
        conn = _connect()
        try:
            conn.execute("DELETE FROM index_items WHERE project_id=?", (pid,))
            conn.execute("DELETE FROM project_meta WHERE project_id=?", (pid,))
            try:
                conn.execute("DELETE FROM knowledge_fts WHERE project_id=?", (pid,))
            except sqlite3.OperationalError:
                pass
            conn.commit()
        finally:
            conn.close()


def delete_item(project_id: str, item_id: str) -> None:
    pid = (project_id or "").strip() or "default"
    rid = (item_id or "").strip()
    if not rid:
        return
    with _lock:
        conn = _connect()
        try:
            conn.execute(
                "DELETE FROM index_items WHERE project_id=? AND item_id=?",
                (pid, rid),
            )
            try:
                conn.execute(
                    "DELETE FROM knowledge_fts WHERE project_id=? AND item_id=?",
                    (pid, rid),
                )
            except sqlite3.OperationalError:
                pass
            conn.commit()
        finally:
            conn.close()


def _rank_python(
    rows: list[sqlite3.Row],
    query_vec: list[float],
    *,
    top_k: int,
) -> list[tuple[str, float, str, str]]:
    scored: list[tuple[str, float, str, str]] = []
    for row in rows:
        vec = blob_to_embedding(row["embedding"])
        score = _cosine(query_vec, vec)
        scored.append(
            (
                str(row["item_id"]),
                float(score),
                str(row["title"] or ""),
                str(row["category"] or ""),
            )
        )
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[: max(1, top_k)]


def hybrid_search(
    project_id: str,
    *,
    query: str,
    query_vector: Sequence[float],
    top_k: int = 5,
) -> tuple[list[dict[str, Any]], str]:
    """FTS5 召回 → sqlite-vec/Python 精排。返回 (hits, engine_tag)。"""
    pid = (project_id or "").strip() or "default"
    q_vec = [float(x) for x in query_vector]
    k = max(1, min(int(top_k), 50))
    with _lock:
        conn = _connect()
        try:
            vec_ok = load_sqlite_vec(conn)
            try:
                conn.execute("SELECT 1 FROM knowledge_fts LIMIT 1")
                fts_ok = True
            except sqlite3.OperationalError:
                fts_ok = False

            candidate_ids: list[str] | None = None
            engine = "vector_scan"
            if hybrid_enabled() and fts_ok and (query or "").strip():
                cand_k = fts_candidate_k(k, query)
                fts_q = escape_fts5_query(query)
                try:
                    fts_rows = conn.execute(
                        """
                        SELECT item_id FROM knowledge_fts
                        WHERE knowledge_fts MATCH ? AND project_id = ?
                        LIMIT ?
                        """,
                        (fts_q, pid, cand_k),
                    ).fetchall()
                    if fts_rows:
                        candidate_ids = [str(r["item_id"]) for r in fts_rows]
                        engine = "fts5+vector"
                    else:
                        engine = "vector_scan"  # FTS 空 → 全量向量
                except sqlite3.OperationalError as exc:
                    logger.debug("fts match failed: %s", exc)
                    candidate_ids = None

            if candidate_ids is not None:
                placeholders = ",".join("?" * len(candidate_ids))
                sql = (
                    f"SELECT item_id, title, category, embedding FROM index_items "
                    f"WHERE project_id=? AND item_id IN ({placeholders})"
                )
                rows = conn.execute(sql, [pid, *candidate_ids]).fetchall()
            else:
                rows = conn.execute(
                    "SELECT item_id, title, category, embedding FROM index_items "
                    "WHERE project_id=?",
                    (pid,),
                ).fetchall()

            hits: list[dict[str, Any]] = []
            if vec_ok and rows:
                try:
                    q_blob = embedding_to_blob(q_vec)
                    # 对候选逐条算距离（sqlite-vec 函数）；大批量时仍 O(n) 但 C 侧更快
                    scored: list[tuple[str, float, str, str]] = []
                    for row in rows:
                        emb = row["embedding"]
                        if not emb:
                            continue
                        dist = conn.execute(
                            "SELECT vec_distance_cosine(?, ?)",
                            (emb, q_blob),
                        ).fetchone()[0]
                        # 假设距离 ∈ [0,2] → 相似度
                        sim = max(0.0, 1.0 - (float(dist) / 2.0))
                        scored.append(
                            (
                                str(row["item_id"]),
                                sim,
                                str(row["title"] or ""),
                                str(row["category"] or ""),
                            )
                        )
                    scored.sort(key=lambda x: x[1], reverse=True)
                    ranked = scored[:k]
                    engine = (
                        "fts5+sqlite_vec"
                        if candidate_ids is not None
                        else "sqlite_vec"
                    )
                except sqlite3.OperationalError:
                    ranked = _rank_python(rows, q_vec, top_k=k)
            else:
                ranked = _rank_python(rows, q_vec, top_k=k)

            for iid, score, title, category in ranked:
                if score <= 0:
                    continue
                hits.append(
                    {
                        "id": iid,
                        "score": score,
                        "title": title,
                        "category": category,
                    }
                )
            return hits, engine
        finally:
            conn.close()
