"""向量检索器：支持传入预计算向量或现场嵌入。"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .hashing_embedder import DEFAULT_DIM, embed_text
from .similarity import cosine
from .types import RagHit


def retrieve_vector(
    rows: Sequence[Any],
    *,
    query: str,
    top_k: int = 5,
    dim: int = DEFAULT_DIM,
    min_score: float = 0.01,
    query_vector: list[float] | None = None,
    row_vectors: Mapping[str, Sequence[float]] | None = None,
    embed_query_fn=None,
) -> list[RagHit]:
    if query_vector is not None:
        q_vec = list(query_vector)
    elif embed_query_fn is not None:
        q_vec = list(embed_query_fn(query))
    else:
        q_vec = embed_text(query, dim=dim)
    if not any(q_vec):
        return []

    scored: list[RagHit] = []
    for row in rows:
        rid = str(getattr(row, "id", "") or "")
        title = str(getattr(row, "title", "") or "")
        content = str(getattr(row, "content", "") or "")
        category = str(getattr(row, "category", "") or "")
        if row_vectors is not None and rid in row_vectors:
            doc_vec = list(row_vectors[rid])
        else:
            blob = f"{title}\n{content}\n{category}"
            doc_vec = embed_text(blob, dim=dim)
        if len(doc_vec) != len(q_vec):
            continue
        score = cosine(q_vec, doc_vec)
        if score < min_score:
            continue
        scored.append(
            RagHit(
                id=rid,
                title=title,
                category=category,
                score=float(score),
                confirmed=bool(getattr(row, "confirmed", False)),
            )
        )
    scored.sort(key=lambda h: h.score, reverse=True)
    return scored[: max(1, min(int(top_k), 20))]
