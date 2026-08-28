"""对象库（.map）内存模型。

解析 .map 工程文件格式：<map> → <element name> (可嵌套) → <locator type>。
文件中通常会写出全部 8 种定位子节点，type 指明实际生效的那一种。
我们的模型只保留生效的那一种，导入时按 type 取值，其余空节点丢弃。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

IOS_APPIUM_SLOT = "ios_appium"
IOS_WDA_SLOT = "ios_wda"


# locator type 取值
LOCATOR_TYPES = {"ID", "WAP_ID", "NAME", "TEXT", "CLASS", "XPATH", "CSS", "AND", "OR"}


@dataclass
class Locator:
    """元素定位方式。

    简单定位（ID/NAME/TEXT/CLASS/XPATH/CSS）用 value(+mode)；
    复合定位（AND/OR）用 tag + properties。
    """

    type: str = "XPATH"
    value: str = ""
    mode: int = 0  # MatchMode 序号（精确/包含/正则…），原样保留
    tag: str = ""
    properties: list[dict] = field(default_factory=list)  # [{name, mode, value}]


@dataclass
class MapElement:
    name: str = ""
    comment: str = ""
    locator: Optional[Locator] = None       # 默认/通用定位符
    # 按平台绑定的定位符(对标 Appium @AndroidFindBy/@iOSXCUITFindBy)：键 "android"/"ios"，
    # 运行时按当前设备平台优先取对应那套，缺则回退 locator。一条用例两端自动适配。
    locators_by_platform: dict = field(default_factory=dict)
    children: list["MapElement"] = field(default_factory=list)

    def locator_for_target(self, platform: str, backend: str = "") -> Optional[Locator]:
        plat = (platform or "").strip().lower()
        backend = (backend or "").strip().lower()
        if plat == "ios":
            slot = ""
            if backend == "appium":
                slot = IOS_APPIUM_SLOT
            elif backend == "wda":
                slot = IOS_WDA_SLOT
            if slot and self.locators_by_platform.get(slot) is not None:
                return self.locators_by_platform[slot]
        if plat and self.locators_by_platform.get(plat) is not None:
            return self.locators_by_platform[plat]
        return self.locator

    def locator_for(self, platform: str) -> Optional[Locator]:
        """按设备平台("android"/"ios"/"")解析定位符：平台专属优先，否则用通用 locator。"""
        return self.locator_for_target(platform, "")

    def find(self, name: str) -> Optional["MapElement"]:
        """按名称在本元素及子树中查找。"""
        if self.name == name:
            return self
        for c in self.children:
            hit = c.find(name)
            if hit is not None:
                return hit
        return None


@dataclass
class MapFile:
    name: str = ""
    elements: list[MapElement] = field(default_factory=list)
    source_path: str = ""

    def find(self, name: str) -> Optional[MapElement]:
        for e in self.elements:
            hit = e.find(name)
            if hit is not None:
                return hit
        return None
