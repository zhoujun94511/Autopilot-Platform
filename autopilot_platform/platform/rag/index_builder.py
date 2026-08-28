"""根据知识条目增量构建 / 刷新向量索引。"""

from __future__ import annotations

import hashlib
from typing import Any, Sequence

from .vector_index_store import load_index, save_index


def _content_hash(title: str, content: str, category: str) -> str:
    blob = f"{title}\n{content}\n{category}".encode("utf-8")
    return hashlib.sha1(blob).hexdigest()


def ensure_index_vectors(
    project_id: str,
    rows: Sequence[Any],
    embedder: Any,
) -> dict[str, list[float]]:
    """返回 id -> vector；缺项或内容变更时增量嵌入并落盘（BLOB + FTS5）。"""
    idx = load_index(project_id)
    items: dict[str, Any] = dict(idx.get("items") or {})
    embedder_name = str(getattr(embedder, "name", "") or "")
    if (idx.get("embedder") or "") != embedder_name:
        items = {}

    need_ids: list[str] = []
    need_texts: list[str] = []
    meta: dict[str, dict[str, str]] = {}

    live_ids = set()
    for row in rows:
        rid = str(getattr(row, "id", "") or "")
        if not rid:
            continue
        live_ids.add(rid)
        title = str(getattr(row, "title", "") or "")
        content = str(getattr(row, "content", "") or "")
        category = str(getattr(row, "category", "") or "")
        ch = _content_hash(title, content, category)
        meta[rid] = {
            "content_hash": ch,
            "title": title,
            "category": category,
            "content": content,
        }
        old = items.get(rid) or {}
        if old.get("content_hash") != ch or not old.get("vector"):
            need_ids.append(rid)
            need_texts.append(f"{title}\n{content}\n{category}")
        else:
            # 保留正文供 FTS（旧索引可能无 content）
            old["content"] = content
            old["title"] = title
            old["category"] = category
            items[rid] = old

    for dead in [k for k in items if k not in live_ids]:
        items.pop(dead, None)

    dim = int(idx.get("embedding_dim") or 0)
    if need_texts:
        vectors = embedder.embed_texts(need_texts)
        for rid, vec in zip(need_ids, vectors):
            items[rid] = {
                "content_hash": meta[rid]["content_hash"],
                "title": meta[rid]["title"],
                "category": meta[rid]["category"],
                "content": meta[rid]["content"],
                "vector": [float(x) for x in vec],
            }
            if not dim and vec:
                dim = len(vec)

    save_index(
        project_id,
        {"embedder": embedder_name, "embedding_dim": dim, "items": items},
    )
    return {rid: list(info.get("vector") or []) for rid, info in items.items() if info.get("vector")}
