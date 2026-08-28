"""工程导入器：把既有 .tc/.ts/.map/.properties 工程文件翻译成内存模型。

原则：能读的尽量读，读不懂的步骤降级为占位而不是中断
（未实现的关键字步骤照样能进树，只是执行期报“未实现”）。
"""

from __future__ import annotations

import os
from typing import Optional

# noinspection PyUnresolvedReferences
from lxml import etree

from .testcase import (
    ParamValue,
    Step,
    StepSet,
    StepVerbs,
    StepInnerCase,
    Shell,
    TestCase,
    TestSuite,
    Desc,
    StepNode,
)
from .mapfile import Locator, MapElement, MapFile
from .keyworddef import KeywordDef, LocalParam
from .testplan import TestPlan


def _bool(v: Optional[str], default: bool = True) -> bool:
    if v is None:
        return default
    return str(v).strip().lower() == "true"


# noinspection PyProtectedMember
def _text(el: Optional[etree._Element]) -> str:
    if el is None or el.text is None:
        return ""
    return el.text


# noinspection PyProtectedMember
def _parse_params(parent: etree._Element) -> list[ParamValue]:
    return [
        ParamValue(param_id=p.get("id", ""), value=p.text or "")
        for p in parent.findall("param")
    ]


# noinspection PyProtectedMember
def _parse_step_node(el: etree._Element) -> Optional[StepNode]:
    """把单个 step/stepset/stepverbs/stepinnercase 元素翻译成模型节点。"""
    tag = el.tag
    if tag == "step":
        legacy_note = el.get("comment", "")
        step = Step(
            keyword_id=el.get("id", ""),
            comment="",
            remark=el.get("remark", legacy_note),
            is_run=_bool(el.get("isrun")),
            params=_parse_params(el),
        )
        # 条件步骤：内部可再嵌子步骤
        if step.is_condition:
            step.children = _parse_step_children(el)
        return step
    if tag == "stepverbs":
        legacy_note = el.get("comment", "")
        return StepVerbs(
            ks_id=el.get("id", ""),
            comment="",
            remark=el.get("remark", legacy_note),
            is_run=_bool(el.get("isrun")),
            params=_parse_params(el),
        )
    if tag == "stepset":
        legacy_note = el.get("comment", "")
        node = StepSet(
            name=el.get("name", ""),
            comment="",
            remark=el.get("remark", legacy_note),
            datapool=el.get("datapool", ""),
            is_run=_bool(el.get("isrun")),
        )
        node.children = _parse_step_children(el)
        return node
    if tag == "stepinnercase":
        legacy_note = el.get("comment", "")
        return StepInnerCase(
            relative_path=el.get("relativepath", ""),
            comment="",
            remark=el.get("remark", legacy_note),
            is_run=_bool(el.get("isrun")),
        )
    return None


# noinspection PyProtectedMember
def _parse_step_children(parent: etree._Element) -> list[StepNode]:
    out: list[StepNode] = []
    for child in parent:
        if child.tag in ("step", "stepset", "stepverbs", "stepinnercase"):
            node = _parse_step_node(child)
            if node is not None:
                out.append(node)
    return out


# noinspection PyProtectedMember
def _parse_shell(root: etree._Element, name: str) -> Shell:
    shell = Shell(name)
    el = root.find(name)
    if el is not None:
        shell.steps = _parse_step_children(el)
    return shell


# noinspection PyProtectedMember
def _parse_desc(root: etree._Element) -> Desc:
    d = root.find("desc")
    if d is None:
        return Desc()
    return Desc(
        author=_text(d.find("author")),
        create_time=_text(d.find("createtime")),
        last_modify_author=_text(d.find("lastmodifyauthor")),
        last_modify_time=_text(d.find("lastmodifytime")),
        versions=_text(d.find("versions")),
        description=_text(d.find("description")),
    )


def load_testcase(path: str) -> TestCase:
    root = etree.parse(path).getroot()
    tc = TestCase(
        name=os.path.splitext(os.path.basename(path))[0],
        data_id=root.get("db_id", ""),
        tag=root.get("tag", ""),
        is_execute=_bool(root.get("is_run")),
        able_invoked=_bool(root.get("is_able_invoked"), default=False),
        datapool=_text(root.find("datapool")) or "DATATABLE(NONE,false)",
        desc=_parse_desc(root),
        source_path=path,
    )
    tc.before = _parse_shell(root, "before")
    tc.case = _parse_shell(root, "case")
    tc.after = _parse_shell(root, "after")
    tc.fault = _parse_shell(root, "fault")
    return tc


def load_testsuite(path: str) -> TestSuite:
    root = etree.parse(path).getroot()
    ts = TestSuite(
        name=os.path.splitext(os.path.basename(path))[0],
        data_id=root.get("db_id", ""),
        tag=root.get("tag", ""),
        datapool=_text(root.find("datapool")) or "DATATABLE(NONE,true)",
        source_path=path,
    )
    ts.before = _parse_shell(root, "before")
    ts.after = _parse_shell(root, "after")
    ts.fault = _parse_shell(root, "fault")
    return ts


# ---- .ks 自定义关键字 ----

# noinspection PyProtectedMember
def _parse_local_param(el: etree._Element) -> LocalParam:
    """解析 .ks 局部参数定义：<param id><name><default><values><required><datapool><comment>。"""
    def t(tag: str) -> str:
        c = el.find(tag)
        return (c.text or "").strip() if c is not None and c.text else ""

    raw_values = t("values")
    values = [v.strip() for v in raw_values.replace("\\r\\n", "\n").replace("\r\n", "\n")
              .split("\n") if v.strip()] if raw_values else []
    raw_visible = t("visible_on_platforms")
    visible_on_platforms = [v.strip() for v in raw_visible.replace("\\r\\n", "\n").replace("\r\n", "\n")
                            .split("\n") if v.strip()] if raw_visible else []
    return LocalParam(
        param_id=el.get("id", ""),
        name=t("name"),
        default=t("default"),
        values=values,
        required=t("required").upper() == "T",
        datapool=t("datapool"),
        comment=t("comment"),
        visible_on_platforms=visible_on_platforms,
    )


def load_keyword(path: str) -> KeywordDef:
    """加载 .ks 自定义关键字定义。

    形参定义可出现在 <params>/<localparams> 下，也可能直接是 root 的 <param>（含 <name> 等子节点）；
    步骤序列在 <steps> 下。容错解析：缺失部分按空处理。
    """
    root = etree.parse(path).getroot()
    kd = KeywordDef(
        ks_id=_text(root.find("id")) or os.path.splitext(os.path.basename(path))[0],
        data_id=root.get("db_id", ""),
        tag=root.get("tag", ""),
        source_path=path,
    )
    # 形参定义：兼容 <params>/<localparams> 容器或散落在 root 下的含子节点的 <param>
    container = root.find("params")
    if container is None:
        container = root.find("localparams")
    param_els = (container.findall("param") if container is not None
                 else [p for p in root.findall("param") if len(p) > 0])
    kd.params = [_parse_local_param(p) for p in param_els]
    # 步骤序列
    steps_el = root.find("steps")
    if steps_el is not None:
        kd.steps = _parse_step_children(steps_el)
    return kd


# ---- .tp 测试计划 ----

def load_testplan(path: str) -> TestPlan:
    """加载 .tp 测试计划（解析本地执行配置 + 成员相对路径，容错）。"""
    root = etree.parse(path).getroot()
    plan_el = root.find("testplan") if root.find("testplan") is not None else root
    local = plan_el.find("local")
    src = local if local is not None else plan_el

    def t(tag_name: str) -> str:
        c = src.find(tag_name)
        return (c.text or "").strip() if c is not None and c.text else ""

    try:
        ft = int(t("faulttimes") or 0)
    except ValueError:
        ft = 0
    tp = TestPlan(
        name=t("name") or os.path.splitext(os.path.basename(path))[0],
        dataconfig=t("dataconfig"),
        fault_times=ft,
        start_time=t("starttime"),
        end_time=t("endtime"),
        source_path=path,
    )
    # 成员：兼容 <member>/<case> 节点（relativepath 属性或文本）
    for tag in ("member", "case"):
        for el in plan_el.iter(tag):
            rel = el.get("relativepath") or (el.text or "").strip()
            if rel:
                tp.members.append(rel)
    return tp


# ---- .map ----

_SIMPLE_LOCATOR_TAGS = {
    "ID": "id",
    "NAME": "name",
    "TEXT": "text",
    "CLASS": "class",
    "WAP_ID": "id",
    "XPATH": "xpath",
    "CSS": "css",
}


# noinspection PyProtectedMember
def _parse_locator(loc_el: etree._Element) -> Locator:
    ltype = loc_el.get("type", "XPATH")
    loc = Locator(type=ltype)
    if ltype in ("AND", "OR"):
        loc.tag = _text(loc_el.find("tag"))
        props_el = loc_el.find("properties")
        if props_el is not None:
            for p in props_el.findall("property"):
                loc.properties.append(
                    {
                        "name": p.get("name", ""),
                        "mode": int(p.get("mode", "0") or 0),
                        "value": p.text or "",
                    }
                )
    else:
        child_tag = _SIMPLE_LOCATOR_TAGS.get(ltype, ltype.lower())
        node = loc_el.find(child_tag)
        if node is not None:
            loc.value = _text(node.find("value"))
            mode_el = node.find("mode")
            loc.mode = int(_text(mode_el) or 0) if mode_el is not None else 0
    return loc


# noinspection PyProtectedMember
def _parse_map_element(el: etree._Element) -> MapElement:
    me = MapElement(name=el.get("name", ""), comment=_text(el.find("comment")))
    loc_el = el.find("locator")
    if loc_el is not None:
        me.locator = _parse_locator(loc_el)
    for child in el.findall("element"):
        me.children.append(_parse_map_element(child))
    return me


def load_mapfile(path: str) -> MapFile:
    root = etree.parse(path).getroot()
    mf = MapFile(
        name=os.path.splitext(os.path.basename(path))[0],
        source_path=path,
    )
    for el in root.findall("element"):
        mf.elements.append(_parse_map_element(el))
    return mf
