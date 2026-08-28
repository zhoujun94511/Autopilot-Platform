"""本地 hashing 嵌入：无需外部模型/API，固定维度稀疏向量。"""

from __future__ import annotations

import hashlib
import math
from typing import Sequence

from .tokenize import tokenize


DEFAULT_DIM = 256


def _bucket(token: str, dim: int) -> int:
    digest = hashlib.sha1(token.encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") % dim


def embed_text(text: str, *, dim: int = DEFAULT_DIM) -> list[float]:
    """词频 hashing → L2 归一化向量。"""
    vec = [0.0] * max(8, int(dim))
    tokens = tokenize(text)
    if not tokens:
        return vec
    for tok in tokens:
        i = _bucket(tok, len(vec))
        vec[i] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def embed_many(texts: Sequence[str], *, dim: int = DEFAULT_DIM) -> list[list[float]]:
    return [embed_text(t, dim=dim) for t in texts]
