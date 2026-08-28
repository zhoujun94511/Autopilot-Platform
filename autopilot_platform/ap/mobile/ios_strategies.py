"""iOS 定位策略排序：检视器候选定位符与执行层 find_element 共用。

WDA-direct 优先 link text / label；Appium 优先 accessibility id / name。
"""

from __future__ import annotations

from dataclasses import dataclass


def use_wda_order(backend: str) -> bool:
    return (backend or "").strip().lower() == "wda"


def predicate_eq(attr: str, value: str) -> str:
    esc = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'{attr} == "{esc}"'


def xpath_quote(value: str) -> str:
    return f'"{value}"' if "'" in value else f"'{value}'"


@dataclass(frozen=True)
class FindStrategy:
    by: str
    value: str


def _xpath_pair(value: str, *, name_first: bool) -> tuple[FindStrategy, FindStrategy]:
    quote = xpath_quote(value)
    first, second = ("name", "label") if name_first else ("label", "name")
    return (
        FindStrategy("xpath", f"//*[@{first}={quote}]"),
        FindStrategy("xpath", f"//*[@{second}={quote}]"),
    )


def attr_find_strategies(attr_name: str, attr_value: str, *,
                         wda_first: bool) -> list[FindStrategy]:
    name_first = attr_name == "name"
    if wda_first:
        x1, x2 = _xpath_pair(attr_value, name_first=name_first)
        return [
            FindStrategy("link text", f"{attr_name}={attr_value}"),
            FindStrategy("-ios predicate string", predicate_eq(attr_name, attr_value)),
            FindStrategy("accessibility id", attr_value),
            FindStrategy("name", attr_value),
            x1, x2,
        ]
    x1, x2 = _xpath_pair(attr_value, name_first=name_first)
    return [
        FindStrategy("accessibility id", attr_value),
        FindStrategy("name", attr_value),
        FindStrategy("-ios predicate string", predicate_eq(attr_name, attr_value)),
        FindStrategy("link text", f"{attr_name}={attr_value}"),
        x1, x2,
    ]


def text_find_strategies(text: str, *, wda_first: bool) -> list[FindStrategy]:
    if wda_first:
        x1, x2 = _xpath_pair(text, name_first=False)
        return [
            FindStrategy("link text", f"label={text}"),
            FindStrategy("link text", f"name={text}"),
            FindStrategy("accessibility id", text),
            FindStrategy("name", text),
            FindStrategy("-ios predicate string", predicate_eq("label", text)),
            FindStrategy("-ios predicate string", predicate_eq("name", text)),
            x1, x2,
        ]
    x1, x2 = _xpath_pair(text, name_first=True)
    return [
        FindStrategy("accessibility id", text),
        FindStrategy("name", text),
        FindStrategy("-ios predicate string", predicate_eq("name", text)),
        FindStrategy("-ios predicate string", predicate_eq("label", text)),
        FindStrategy("link text", f"label={text}"),
        FindStrategy("link text", f"name={text}"),
        x1, x2,
    ]


def dedupe_strategies(strategies: list[FindStrategy]) -> list[FindStrategy]:
    out: list[FindStrategy] = []
    seen: set[tuple[str, str]] = set()
    for s in strategies:
        key = (s.by, s.value)
        if key not in seen:
            seen.add(key)
            out.append(s)
    return out


def node_inspector_locators(
    *,
    acc_name: str,
    label: str,
    value: str,
    name_unique: bool,
    wda_first: bool,
    tag: str = "",
) -> list[tuple[str, str]]:
    """检视器候选定位符：(展示标签, locator 串)。"""
    out: list[tuple[str, str]] = []

    def add(display: str, locator: str) -> None:
        item = (display, locator)
        if item not in out:
            out.append(item)

    xcui_tag = tag if tag.startswith("XCUIElementType") else ""

    def add_class_chain(attr: str, val: str) -> None:
        if not xcui_tag or not val:
            return
        esc = str(val).replace("\\", "\\\\").replace('"', '\\"')
        add(f"class-chain({attr})", f"class-chain::**/{xcui_tag}[`{attr} == \"{esc}\"`]")

    if acc_name and name_unique:
        star = "" if wda_first else " *"
        add(f"name(accessibility id){star}", f"name::{acc_name}")
        add_class_chain("name", acc_name)

    if wda_first:
        if label:
            add("predicate(label) *", f"predicate::{predicate_eq('label', label)}")
            add("xpath(label)", f"xpath:://*[@label={xpath_quote(label)}]")
            add_class_chain("label", label)
        if acc_name:
            add("predicate(name)", f"predicate::{predicate_eq('name', acc_name)}")
            add("xpath(name)", f"xpath:://*[@name={xpath_quote(acc_name)}]")
    else:
        if acc_name:
            add("predicate(name) *", f"predicate::{predicate_eq('name', acc_name)}")
            add("xpath(name)", f"xpath:://*[@name={xpath_quote(acc_name)}]")
        if label:
            add("predicate(label)", f"predicate::{predicate_eq('label', label)}")
            add("xpath(label)", f"xpath:://*[@label={xpath_quote(label)}]")
            add_class_chain("label", label)

    if value:
        add("predicate(value)", f"predicate::{predicate_eq('value', value)}")
        add("xpath(value)", f"xpath:://*[@value={xpath_quote(value)}]")
        add_class_chain("value", value)

    return out


def node_inspector_runtime_fallbacks(
    *,
    acc_name: str,
    label: str,
    value: str,
    wda_first: bool,
) -> list[tuple[str, str]]:
    """执行层 find_element 会尝试、但检视器不作为首选推荐的 link text 回退。"""
    out: list[tuple[str, str]] = []

    def add(display: str, locator: str) -> None:
        item = (display, locator)
        if item not in out:
            out.append(item)

    if wda_first:
        if label:
            add("link text(label) [运行时]", f"linktext::label={label}")
        if acc_name and acc_name != label:
            add("link text(name) [运行时]", f"linktext::name={acc_name}")
    else:
        if acc_name:
            add("link text(name) [运行时]", f"linktext::name={acc_name}")
        if label and label != acc_name:
            add("link text(label) [运行时]", f"linktext::label={label}")
    if value and value not in (label, acc_name):
        add("link text(value) [运行时]", f"linktext::name={value}")
    return out
