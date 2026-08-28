"""页面状态 hash 与卡住检测。"""

from __future__ import annotations

import hashlib

from .element import MonkeyElement


def build_state_hash(bundle_id: str, elements: list[MonkeyElement]) -> str:
    parts = [bundle_id or ""]
    for e in elements[:50]:
        parts.append(f"{e.type}|{e.name}|{e.label}|{e.x}|{e.y}|{e.width}|{e.height}")
    raw = "\n".join(parts)
    return hashlib.md5(raw.encode("utf-8", errors="ignore")).hexdigest()[:12]


class StuckTracker:
    def __init__(self, limit: int = 8):
        self.limit = max(2, int(limit))
        self._last = ""
        self._same = 0

    def observe(self, state_hash: str) -> int:
        if state_hash == self._last:
            self._same += 1
        else:
            self._last = state_hash
            self._same = 1
        return self._same

    @property
    def same_count(self) -> int:
        return self._same

    def is_stuck(self) -> bool:
        return self._same >= self.limit
