"""iOS 原生下拉/选择器：点击展开 + 点选（WDA-direct / Appium iOS 共用）。

勿使用 Selenium Select（WdaElement 非 WebElement）。WebView 内 HTML <select> 由关键字层走 Select。
"""

from __future__ import annotations

import time
from typing import Any

_OPTION_TYPES = (
    "XCUIElementTypeStaticText",
    "XCUIElementTypeCell",
    "XCUIElementTypeButton",
    "XCUIElementTypeOther",
)


def _escape_xpath_literal(text: str) -> str:
    s = str(text)
    if "'" not in s:
        return f"'{s}'"
    if '"' not in s:
        return f'"{s}"'
    parts = s.split("'")
    return "concat(" + ", \"'\", ".join(f"'{p}'" for p in parts) + ")"


def _visible(driver: Any, xpath: str) -> list[Any]:
    found = driver.find_elements("xpath", xpath)
    out: list[Any] = []
    for el in found:
        # noinspection PyBroadException
        try:
            if el.is_displayed():
                out.append(el)
        except Exception:
            out.append(el)
    return out


def ios_combo_select(
    driver: Any,
    combo_el: Any,
    select_type: str,
    value: str,
    *,
    settle_s: float = 0.35,
) -> None:
    """模拟原生下拉：先点控件，再按文本或索引点选可见项。"""
    combo_el.click()
    if settle_s > 0:
        time.sleep(settle_s)

    kind = (select_type or "内容").strip()
    if kind == "索引":
        idx = int(value)
        if idx < 0:
            raise ValueError(f"下拉索引不能为负: {value!r}")
        types = " | ".join(f"//XCUIElementType{t}" for t in _OPTION_TYPES)
        options = _visible(driver, f"({types})")
        if idx >= len(options):
            raise ValueError(
                f"下拉索引 {idx} 超出可见选项数 {len(options)}"
            )
        options[idx].click()
        return

    lit = _escape_xpath_literal(str(value))
    xp = (
        f"//*[@label={lit} or @name={lit} or @value={lit}]"
        f"|//*[contains(@label, {lit}) or contains(@name, {lit})]"
    )
    matches = _visible(driver, xp)
    if not matches:
        raise ValueError(f"未找到下拉选项: {value!r}")
    matches[0].click()
