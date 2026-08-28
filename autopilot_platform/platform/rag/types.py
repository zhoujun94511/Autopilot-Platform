"""RAG 检索结果类型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RagHit:
    id: str
    title: str
    category: str = ""
    score: float = 0.0
    confirmed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "category": self.category,
            "score": round(float(self.score), 4),
            "confirmed": bool(self.confirmed),
        }


@dataclass
class RagResult:
    context_text: str = ""
    hits: list[RagHit] = field(default_factory=list)
    engine: str = "none"

    def to_dict(self) -> dict[str, Any]:
        return {
            "context_text": self.context_text,
            "hits": [h.to_dict() for h in self.hits],
            "engine": self.engine,
        }
