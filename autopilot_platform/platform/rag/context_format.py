"""把命中条目格式化为可注入 prompt 的上下文。"""

from __future__ import annotations

from typing import Any, Sequence

from .types import RagHit


def build_context_text(hits: Sequence[RagHit], rows_by_id: dict[str, Any]) -> str:
    chunks: list[str] = []
    for hit in hits:
        row = rows_by_id.get(hit.id)
        content = str(getattr(row, "content", "") or "") if row is not None else ""
        title = hit.title or (str(getattr(row, "title", "") or "") if row else "")
        if not title and not content:
            continue
        chunks.append(f"### {title}\n{content[:1200]}")
    if not chunks:
        return ""
    return (
        "以下为项目知识库检索到的相关条目，生成用例时优先遵循（仍须可判定、可自动化评估）：\n\n"
        + "\n\n".join(chunks)
    )
