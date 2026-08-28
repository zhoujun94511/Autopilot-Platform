"""关键词检索器。"""

from __future__ import annotations

from typing import Any, Sequence

from .tokenize import tokenize_set
from .types import RagHit


def score_keyword(query: str, title: str, content: str, category: str = "") -> float:
    q_tokens = tokenize_set(query)
    blob = f"{title}\n{content}\n{category}"
    tokens = tokenize_set(blob)
    score = 0.0
    if q_tokens and tokens:
        score = len(q_tokens & tokens) / max(1, len(q_tokens))
    title_s = (title or "").strip()
    for i in range(max(0, len(title_s) - 1)):
        piece = title_s[i : i + 2]
        if piece and piece in (query or ""):
            score += 0.25
            break
    q_lower = (query or "").strip().lower()
    if q_lower and q_lower in blob.lower():
        score += 0.3
    return score


def retrieve_keyword(
    rows: Sequence[Any],
    *,
    query: str,
    top_k: int = 5,
) -> list[RagHit]:
    scored: list[RagHit] = []
    for row in rows:
        score = score_keyword(
            query,
            getattr(row, "title", "") or "",
            getattr(row, "content", "") or "",
            getattr(row, "category", "") or "",
        )
        if score <= 0:
            continue
        scored.append(
            RagHit(
                id=str(getattr(row, "id", "") or ""),
                title=str(getattr(row, "title", "") or ""),
                category=str(getattr(row, "category", "") or ""),
                score=float(score),
                confirmed=bool(getattr(row, "confirmed", False)),
            )
        )
    scored.sort(key=lambda h: h.score, reverse=True)
    return scored[: max(1, min(int(top_k), 20))]
