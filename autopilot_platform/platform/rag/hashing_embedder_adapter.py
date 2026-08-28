"""本地 hashing 嵌入器。"""

from __future__ import annotations

from typing import Sequence

from .hashing_embedder import DEFAULT_DIM, embed_many, embed_text


class HashingEmbedder:
    name = "hashing_v1"

    def __init__(self, *, dim: int = DEFAULT_DIM) -> None:
        self.dim = dim

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        return embed_many(texts, dim=self.dim)

    def embed_query(self, text: str) -> list[float]:
        return embed_text(text, dim=self.dim)
