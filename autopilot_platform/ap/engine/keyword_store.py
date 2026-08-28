"""自定义关键字(.ks)仓库：扫描工程目录、按 id/db_id 索引 KeywordDef。

供执行引擎在遇到 <stepverbs id> 时按 id 查回对应的 .ks 定义并内联展开执行。
"""

from __future__ import annotations

import os
from typing import Optional

from ..model.keyworddef import KeywordDef
from ..model.loader import load_keyword


class KeywordStore:
    """按 ks_id 与 db_id 双索引的自定义关键字集合。"""

    def __init__(self) -> None:
        self.by_id: dict[str, KeywordDef] = {}
        self.by_dbid: dict[str, KeywordDef] = {}

    def add(self, kd: KeywordDef) -> None:
        if kd.ks_id:
            self.by_id[kd.ks_id] = kd
        if kd.data_id:
            self.by_dbid[kd.data_id] = kd

    def get(self, ref: str) -> Optional[KeywordDef]:
        """按调用处 stepverbs.id 查回定义：先按 ks_id，再按 db_id。"""
        return self.by_id.get(ref) or self.by_dbid.get(ref)

    def __len__(self) -> int:
        return len(self.by_id)


def discover_keyword_files(directory: str) -> list[str]:
    """递归发现目录下的自定义关键字文件（既有 .ks 与新格式 .ks.yaml）。"""
    found: list[str] = []
    for root, _dirs, files in os.walk(directory):
        for f in files:
            if f.endswith(".ks") or f.endswith(".ks.yaml") or f.endswith(".ks.yml"):
                found.append(os.path.join(root, f))
    return sorted(found)


def _load_any(path: str) -> KeywordDef:
    """按后缀加载自定义关键字：.ks.yaml 走序列化器，.ks 走既有 XML 导入器。"""
    if path.endswith((".ks.yaml", ".ks.yml")):
        from ..model import serializer
        return serializer.load(path)
    return load_keyword(path)


def discover_keywords(directory: str) -> KeywordStore:
    """扫描目录下所有自定义关键字，构建 KeywordStore（单个文件解析失败则跳过）。"""
    store = KeywordStore()
    for path in discover_keyword_files(directory):
        try:
            store.add(_load_any(path))
        except (OSError, ValueError, SyntaxError):
            continue
    return store
