"""文本分词（中英混排轻量切分）。"""

from __future__ import annotations

import re


def tokenize(text: str) -> list[str]:
    """中英混排：抽词 + 中文二字窗，增强短句向量召回。"""
    raw = (text or "").lower()
    tokens = re.findall(r"[\w\u4e00-\u9fff]{2,}", raw)
    # 中文连续段再切二字窗
    for seg in re.findall(r"[\u4e00-\u9fff]{2,}", raw):
        for i in range(len(seg) - 1):
            tokens.append(seg[i : i + 2])
    return tokens


def tokenize_set(text: str) -> set[str]:
    return set(tokenize(text))
