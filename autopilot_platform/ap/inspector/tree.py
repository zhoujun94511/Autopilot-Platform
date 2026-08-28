"""Snapshot parsing and locator generation helpers for inspector."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Optional

# noinspection PyUnresolvedReferences
from lxml import etree

_ANDROID_BOUNDS = re.compile(r"\[(\d+),(\d+)]\[(\d+),(\d+)]")


@dataclass
class UiNode:
    tag: str
    attrs: dict
    bounds: Optional[tuple]
    children: list = field(default_factory=list)
    depth: int = 0
    locators: list = field(default_factory=list)

    def label(self) -> str:
        a = self.attrs
        key = (
            a.get("resource-id")
            or a.get("content-desc")
            or a.get("text")
            or a.get("name")
            or a.get("label")
            or a.get("id")
            or ""
        )
        short_tag = self.tag.split(".")[-1].replace("XCUIElementType", "")
        return f"{short_tag}  {key}".strip() if key else short_tag

    def iter_all(self):
        yield self
        for child in self.children:
            yield from child.iter_all()


def _android_bounds(value: str) -> Optional[tuple]:
    m = _ANDROID_BOUNDS.search(value or "")
    if not m:
        return None
    x1, y1, x2, y2 = (int(g) for g in m.groups())
    return x1, y1, max(0, x2 - x1), max(0, y2 - y1)


# noinspection PyProtectedMember
def _build(el: "etree._Element", platform: str, depth: int) -> UiNode:
    attrs = {k: (v or "") for k, v in el.attrib.items()}
    if platform == "android":
        tag = attrs.get("class") or el.tag
        bounds = _android_bounds(attrs.get("bounds", ""))
    else:
        tag = attrs.get("type") or el.tag
        # noinspection PyBroadException
        try:
            bounds = (
                int(float(attrs["x"])),
                int(float(attrs["y"])),
                int(float(attrs["width"])),
                int(float(attrs["height"])),
            ) if {"x", "y", "width", "height"} <= attrs.keys() else None
        except Exception:
            bounds = None
    node = UiNode(tag=tag, attrs=attrs, bounds=bounds, depth=depth)
    for child in el:
        if isinstance(child.tag, str):
            node.children.append(_build(child, platform, depth + 1))
    return node


def parse_android(xml: str) -> UiNode:
    root = etree.fromstring(xml.encode("utf-8") if isinstance(xml, str) else xml)
    real = root[0] if root.tag == "hierarchy" and len(root) else root
    return _build(real, "android", 0)


def parse_ios(xml: str) -> UiNode:
    root = etree.fromstring(xml.encode("utf-8") if isinstance(xml, str) else xml)
    return _build(root, "ios", 0)


def parse_web(data) -> UiNode:
    obj = json.loads(data) if isinstance(data, (str, bytes)) else data
    viewport = obj.get("viewport") or [0, 0]
    tree = obj.get("tree") or {}

    def build(node_dict: dict, depth: int) -> UiNode:
        rect = node_dict.get("rect") or [0, 0, 0, 0]
        bounds = (int(rect[0]), int(rect[1]), int(rect[2]), int(rect[3])) if len(rect) == 4 else None
        node = UiNode(
            tag=node_dict.get("tag") or "node",
            attrs={k: (v or "") for k, v in (node_dict.get("attrs") or {}).items()},
            bounds=bounds,
            depth=depth,
        )
        loc = node_dict.get("loc") or {}
        for key, prefix, label in (
            ("id", "id::", "id"),
            ("css", "css::", "css"),
            ("xpath", "xpath::", "xpath"),
        ):
            value = loc.get(key)
            if value:
                node.locators.append((label, prefix + value))
        for child in node_dict.get("children") or []:
            node.children.append(build(child, depth + 1))
        return node

    root = build(tree, 0)
    if viewport and viewport[0]:
        root.bounds = (0, 0, int(viewport[0]), int(viewport[1]))
    return root


def parse_snapshot(xml: str, platform: str) -> UiNode:
    p = str(platform).lower()
    if p.startswith("ios"):
        return parse_ios(xml)
    if p.startswith("web"):
        return parse_web(xml)
    return parse_android(xml)


def _max_bounds_extent(root: UiNode, *, img_w: int = 0) -> tuple[int, int]:
    mw = mh = 0
    for n in root.iter_all():
        b = n.bounds
        if not b or b[2] <= 0 or b[3] <= 0:
            continue
        # Appium 全屏 Window 常以物理像素(width≈截图像素)上报，不参与逻辑范围统计
        if img_w > 0 and b[2] >= img_w * 0.9:
            continue
        mw = max(mw, b[0] + b[2])
        mh = max(mh, b[1] + b[3])
    return mw, mh


def compute_render_scale(
    platform: str,
    img_w: int,
    _img_h: int,
    root: UiNode,
    *,
    logical_size: Optional[dict] = None,
    backend: str = "",
) -> float:
    """截图像素 ↔ page_source 坐标的缩放比（device_coord * scale = pixel）。

    分支策略（避免 Mac 修复影响 Windows 已验证路径）：
    - Android：始终用根 bounds 宽（历史行为，Windows 主路径）
    - iOS + Appium：page_source 常混用物理像素 Window 与点坐标子节点
    - iOS + WDA/其他：沿用根 bounds（Windows WDA-direct 已验证）
    """
    if img_w <= 0:
        return 1.0
    p = str(platform).lower()
    if not p.startswith("ios"):
        rb = root.bounds
        return (img_w / rb[2]) if (rb and rb[2]) else 1.0

    if logical_size:
        lw = logical_size.get("width") or 0
        if lw > 0:
            return img_w / float(lw)

    b = str(backend).lower()
    if b == "appium":
        max_w, _ = _max_bounds_extent(root, img_w=img_w)
        rb = root.bounds
        root_w = (rb[2] if rb else 0) or 0
        if root_w >= img_w * 0.9:
            root_w = 0
        if 0 < max_w < img_w * 0.55:
            return img_w / float(max_w)
        if root_w > 0:
            return img_w / float(root_w)
        if max_w > 0:
            return img_w / float(max_w)

    rb = root.bounds
    return (img_w / rb[2]) if (rb and rb[2]) else 1.0


def _area(bounds: tuple) -> int:
    return bounds[2] * bounds[3]


def hit_test(root: UiNode, x: int, y: int) -> Optional[UiNode]:
    best: Optional[UiNode] = None
    for node in root.iter_all():
        bounds = node.bounds
        if not bounds or bounds[2] <= 0 or bounds[3] <= 0:
            continue
        if bounds[0] <= x <= bounds[0] + bounds[2] and bounds[1] <= y <= bounds[1] + bounds[3]:
            if best is None or _area(bounds) < _area(best.bounds):
                best = node
    return best


def _xq(value: str) -> str:
    from ..mobile.ios_strategies import xpath_quote
    return xpath_quote(value)


def _ios_predicate(attr: str, value: str) -> str:
    from ..mobile.ios_strategies import predicate_eq
    return predicate_eq(attr, value)


def _count_attr(root: UiNode, attr: str, value: str) -> int:
    return sum(1 for node in root.iter_all() if node.attrs.get(attr) == value)


def generate_locators(root: UiNode, node: UiNode, platform: str, backend: str = "") -> list:
    out: list = []
    attrs = node.attrs
    p = str(platform).lower()
    b = str(backend).lower()
    is_ios = p.startswith("ios")
    is_web = p.startswith("web")

    def add(strategy: str, locator_value: str) -> None:
        item = (strategy, locator_value)
        if item not in out:
            out.append(item)

    if is_web:
        if node.locators:
            for label, locator in node.locators:
                add(label, locator)
        else:
            _web_locators(root, node, attrs, add)
        add("absolute xpath", "xpath::" + _abs_xpath(root, node))
        return out

    if is_ios:
        from ..mobile.ios_strategies import node_inspector_locators, use_wda_order

        acc_name = attrs.get("name") or ""
        label = attrs.get("label") or ""
        value = attrs.get("value") or ""
        for display, locator in node_inspector_locators(
            acc_name=acc_name,
            label=label,
            value=value,
            name_unique=bool(acc_name and _count_attr(root, "name", acc_name) == 1),
            wda_first=use_wda_order(b),
            tag=node.tag,
        ):
            add(display, locator)
        from ..mobile.ios_strategies import node_inspector_runtime_fallbacks
        for display, locator in node_inspector_runtime_fallbacks(
            acc_name=acc_name,
            label=label,
            value=value,
            wda_first=use_wda_order(b),
        ):
            add(display, locator)
    else:
        resource_id = attrs.get("resource-id") or ""
        if resource_id and _count_attr(root, "resource-id", resource_id) == 1:
            add("resource-id", f"id::{resource_id}")
        desc = attrs.get("content-desc") or ""
        if desc:
            add("xpath(content-desc)", f"xpath:://*[@content-desc={_xq(desc)}]")
        text = attrs.get("text") or ""
        if text:
            add("xpath(text)", f"xpath:://*[@text={_xq(text)}]")
        if resource_id:
            add("xpath(resource-id)", f"xpath:://*[@resource-id={_xq(resource_id)}]")

    add("absolute xpath", "xpath::" + _abs_xpath(root, node))
    return out


def _count_class(root: UiNode, cls: str) -> int:
    return sum(1 for node in root.iter_all() if cls in (node.attrs.get("class") or "").split())


def _web_locators(root: UiNode, node: UiNode, attrs: dict, add) -> None:
    node_id = attrs.get("id") or ""
    if node_id and _count_attr(root, "id", node_id) == 1:
        add("id", f"id::{node_id}")
        add("css(id)", f"css::#{node_id}")
    test_id = attrs.get("data-testid") or ""
    if test_id and _count_attr(root, "data-testid", test_id) == 1:
        add("css(data-testid)", f"css::[data-testid={_xq(test_id)}]")
    for k, v in attrs.items():
        if not k.startswith("data-") or k == "data-testid" or not v:
            continue
        if _count_attr(root, k, v) == 1:
            add(f"css({k})", f"css::[{k}={_xq(v)}]")
    name = attrs.get("name") or ""
    if name and _count_attr(root, "name", name) == 1:
        add("css(name)", f"css::[name={_xq(name)}]")
    for cls in (attrs.get("class") or "").split():
        if _count_class(root, cls) == 1:
            add("css(class)", f"css::{'.' + cls}")
            break
    aria = attrs.get("aria-label") or ""
    if aria:
        add("xpath(aria-label)", f"xpath:://*[@aria-label={_xq(aria)}]")
    text = attrs.get("text") or ""
    if text and node.tag in ("a", "button", "span", "label", "li", "h1", "h2", "h3"):
        add("xpath(text)", f"xpath:://{node.tag}[normalize-space()={_xq(text)}]")


def _abs_xpath(root: UiNode, target: UiNode) -> str:
    path: list[str] = []

    def dfs(node: UiNode, trail: list[str]) -> bool:
        if node is target:
            path.extend(trail)
            return True
        counts: dict[str, int] = {}
        for child in node.children:
            counts[child.tag] = counts.get(child.tag, 0) + 1
            segment = f"{child.tag}[{counts[child.tag]}]"
            if dfs(child, trail + [segment]):
                return True
        return False

    return "//" + "/".join(path) if dfs(root, [f"{root.tag}[1]"]) or path else "//*"
