"""缓存 page_source 解析结果，降低长跑 dump 频率。"""

from __future__ import annotations

from dataclasses import dataclass, field

from .element import MonkeyElement, parse_elements


@dataclass
class PageStateCache:
    xml: str = ""
    elements: list[MonkeyElement] = field(default_factory=list)
    state_hash: str = ""
    last_index: int = 0

    def refresh(self, driver, bundle_id: str, *, index: int, w: int, h: int,
                build_hash) -> tuple[list[MonkeyElement], str]:
        self.xml = driver.page_source()
        self.elements = parse_elements(self.xml, screen_w=w, screen_h=h)
        self.state_hash = build_hash(bundle_id, self.elements)
        self.last_index = index
        return self.elements, self.state_hash

    def reuse(self) -> tuple[list[MonkeyElement], str]:
        return self.elements, self.state_hash
