"""嵌入器协议。"""

from __future__ import annotations

from typing import Protocol, Sequence


class Embedder(Protocol):
    name: str

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        ...

    def embed_query(self, text: str) -> list[float]:
        ...
