"""Crash 列表解析与增量 diff（纯函数）。"""

from __future__ import annotations

import os
import re


def parse_crash_ls(text: str) -> set[str]:
    """从 go-ios ``crash ls`` 或 pmd3 列表文本提取文件名。"""
    names: set[str] = set()
    for line in (text or "").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        for token in re.split(r"[\s,]+", s):
            tok = token.strip().strip("'\"")
            if tok and (".ips" in tok.lower() or ".crash" in tok.lower() or ".synced" in tok.lower()):
                names.add(os.path.basename(tok))
    return names


def diff_new(before: set[str], after: set[str]) -> list[str]:
    return sorted(after - before)


def is_relevant_crash(name: str, bundle_id: str) -> bool:
    if not name:
        return False
    hay = name.lower()
    bid = (bundle_id or "").lower()
    if bid and bid in hay:
        return True
    if bid and bid.replace(".", "-") in hay:
        return True
    if bid:
        short = bid.split(".")[-1]
        if len(short) >= 4 and short in hay:
            return True
    return False


def list_crash_files(directory: str) -> list[str]:
    if not directory or not os.path.isdir(directory):
        return []
    out: list[str] = []
    for name in os.listdir(directory):
        low = name.lower()
        if low.endswith((".ips", ".crash", ".synced")):
            out.append(name)
    return sorted(out)
