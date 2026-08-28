"""AutoPilot 新工程格式（YAML）序列化。

设计：现代、可读、可 diff 的 YAML，无损表达内存模型。
- 节点用判别键区分：step / stepverbs / stepset / innercase。
- 参数用有序 dict（param_id -> value）表达，简洁；顺序即 YAML 书写顺序。
- 文件顶层带 `type`（testcase/testsuite/mapfile）与 `format_version`，便于演进。

文件后缀约定：.tc.yaml / .ts.yaml / .map.yaml（与旧 .tc/.ts/.map 区分，可共存）。
"""

from __future__ import annotations

import dataclasses
from typing import Any

# noinspection PyUnresolvedReferences
import yaml

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
)
from .mapfile import Locator, MapElement, MapFile
from .keyworddef import KeywordDef, LocalParam
from .testplan import TestPlan


FORMAT_VERSION = 1


# ---------- 模型 → dict ----------

def _params_to_dict(params: list[ParamValue]) -> dict[str, str]:
    return {p.param_id: p.value for p in params}


def _node_to_dict(node) -> dict[str, Any]:
    if isinstance(node, Step):
        d: dict[str, Any] = {"step": node.keyword_id}
        if node.comment:
            d["comment"] = node.comment
        if node.remark:
            d["remark"] = node.remark
        if not node.is_run:
            d["is_run"] = False
        if node.params:
            d["params"] = _params_to_dict(node.params)
        if node.children:
            d["children"] = [_node_to_dict(c) for c in node.children]
        return d
    if isinstance(node, StepVerbs):
        d = {"stepverbs": node.ks_id}
        if node.comment:
            d["comment"] = node.comment
        if node.remark:
            d["remark"] = node.remark
        if not node.is_run:
            d["is_run"] = False
        if node.params:
            d["params"] = _params_to_dict(node.params)
        return d
    if isinstance(node, StepSet):
        d = {"stepset": node.name}
        if node.comment:
            d["comment"] = node.comment
        if node.remark:
            d["remark"] = node.remark
        if node.datapool:
            d["datapool"] = node.datapool
        if not node.is_run:
            d["is_run"] = False
        if node.children:
            d["children"] = [_node_to_dict(c) for c in node.children]
        return d
    if isinstance(node, StepInnerCase):
        d = {"innercase": node.relative_path}
        if node.comment:
            d["comment"] = node.comment
        if node.remark:
            d["remark"] = node.remark
        if not node.is_run:
            d["is_run"] = False
        return d
    raise TypeError(f"未知步骤节点类型: {type(node)!r}")


def _shell_to_list(shell: Shell) -> list[dict]:
    return [_node_to_dict(n) for n in shell.steps]


_DESC_FIELD_NAMES = {f.name for f in dataclasses.fields(Desc)}


def _desc_to_dict(desc: Desc) -> dict[str, str]:
    return {k: v for k, v in dataclasses.asdict(desc).items() if v}


def _dict_to_desc(raw: Any) -> Desc:
    if not isinstance(raw, dict):
        return Desc()
    kwargs = {
        k: str(v) if v is not None else ""
        for k, v in raw.items()
        if k in _DESC_FIELD_NAMES
    }
    return Desc(**kwargs)


def _testcase_has_trace(tc: TestCase) -> bool:
    return bool(
        (tc.schema_version or "").strip()
        or (tc.project_id or "").strip()
        or (tc.logical_case_id or "").strip()
        or (tc.automation_case_id or "").strip()
        or (tc.revision_id or "").strip()
        or (tc.case_key or "").strip()
    )


def testcase_to_dict(tc: TestCase) -> dict[str, Any]:
    traced = _testcase_has_trace(tc)
    schema_ver = (tc.schema_version or "").strip() or ("2.0" if traced else "")
    d: dict[str, Any] = {
        "type": "testcase",
        "format_version": 2 if (traced or schema_ver.startswith("2")) else FORMAT_VERSION,
        "name": tc.name,
        "data_id": tc.data_id,
        "tag": tc.tag,
        "platform": tc.platform,
        "is_execute": tc.is_execute,
        "able_invoked": tc.able_invoked,
        "datapool": tc.datapool,
        "desc": _desc_to_dict(tc.desc),
        "shells": {
            "before": _shell_to_list(tc.before),
            "case": _shell_to_list(tc.case),
            "after": _shell_to_list(tc.after),
            "fault": _shell_to_list(tc.fault),
        },
    }
    if schema_ver:
        d["schema_version"] = schema_ver
    for key in (
        "project_id",
        "logical_case_id",
        "automation_case_id",
        "revision_id",
        "case_key",
    ):
        val = str(getattr(tc, key, "") or "").strip()
        if val:
            d[key] = val
    return d



def testsuite_to_dict(ts: TestSuite) -> dict[str, Any]:
    return {
        "type": "testsuite",
        "format_version": FORMAT_VERSION,
        "name": ts.name,
        "data_id": ts.data_id,
        "tag": ts.tag,
        "datapool": ts.datapool,
        "shells": {
            "before": _shell_to_list(ts.before),
            "after": _shell_to_list(ts.after),
            "fault": _shell_to_list(ts.fault),
        },
    }


def _locator_to_dict(loc: Locator) -> dict[str, Any]:
    d: dict[str, Any] = {"type": loc.type}
    if loc.type in ("AND", "OR"):
        d["tag"] = loc.tag
        d["properties"] = loc.properties
    else:
        d["value"] = loc.value
        if loc.mode:
            d["mode"] = loc.mode
    return d


def _map_element_to_dict(el: MapElement) -> dict[str, Any]:
    d: dict[str, Any] = {"name": el.name}
    if el.comment:
        d["comment"] = el.comment
    if el.locator is not None:
        d["locator"] = _locator_to_dict(el.locator)
    if el.locators_by_platform:           # 按平台定位符(android/ios)，有才写
        d["locators_by_platform"] = {p: _locator_to_dict(loc)
                                     for p, loc in el.locators_by_platform.items()
                                     if loc is not None}
    if el.children:
        d["children"] = [_map_element_to_dict(c) for c in el.children]
    return d


def mapfile_to_dict(mf: MapFile) -> dict[str, Any]:
    return {
        "type": "mapfile",
        "format_version": FORMAT_VERSION,
        "name": mf.name,
        "elements": [_map_element_to_dict(e) for e in mf.elements],
    }


def _local_param_to_dict(p: LocalParam) -> dict[str, Any]:
    d: dict[str, Any] = {"id": p.param_id}
    if p.name:
        d["name"] = p.name
    if p.default:
        d["default"] = p.default
    if p.values:
        d["values"] = p.values
    if p.required:
        d["required"] = True
    if p.datapool:
        d["datapool"] = p.datapool
    if p.comment:
        d["comment"] = p.comment
    if p.visible_on_platforms:
        d["visible_on_platforms"] = p.visible_on_platforms
    return d


def keyworddef_to_dict(kd: KeywordDef) -> dict[str, Any]:
    return {
        "type": "keyworddef",
        "format_version": FORMAT_VERSION,
        "ks_id": kd.ks_id,
        "data_id": kd.data_id,
        "tag": kd.tag,
        "params": [_local_param_to_dict(p) for p in kd.params],
        "steps": [_node_to_dict(n) for n in kd.steps],
    }


# ---------- dict → 模型 ----------

def _dict_to_params(d: dict[str, str] | None) -> list[ParamValue]:
    if not d:
        return []
    return [ParamValue(param_id=k, value="" if v is None else str(v)) for k, v in d.items()]


def _dict_to_node(d: dict[str, Any]):
    if "step" in d:
        step = Step(
            keyword_id=d["step"],
            comment=d.get("comment", ""),
            remark=d.get("remark", ""),
            is_run=d.get("is_run", True),
            params=_dict_to_params(d.get("params")),
        )
        step.children = [_dict_to_node(c) for c in d.get("children", [])]
        return step
    if "stepverbs" in d:
        return StepVerbs(
            ks_id=d["stepverbs"],
            comment=d.get("comment", ""),
            remark=d.get("remark", ""),
            is_run=d.get("is_run", True),
            params=_dict_to_params(d.get("params")),
        )
    if "stepset" in d:
        node = StepSet(
            name=d["stepset"],
            comment=d.get("comment", ""),
            remark=d.get("remark", ""),
            datapool=d.get("datapool", ""),
            is_run=d.get("is_run", True),
        )
        node.children = [_dict_to_node(c) for c in d.get("children", [])]
        return node
    if "innercase" in d:
        return StepInnerCase(
            relative_path=d["innercase"],
            comment=d.get("comment", ""),
            remark=d.get("remark", ""),
            is_run=d.get("is_run", True),
        )
    raise ValueError(f"无法识别的步骤节点: {d!r}")


def _list_to_shell(name: str, items: list[dict] | None) -> Shell:
    shell = Shell(name)
    shell.steps = [_dict_to_node(x) for x in (items or [])]
    return shell


def dict_to_testcase(d: dict[str, Any]) -> TestCase:
    shells = d.get("shells", {})
    tc = TestCase(
        name=d.get("name", ""),
        data_id=d.get("data_id", ""),
        tag=d.get("tag", ""),
        platform=d.get("platform", ""),
        is_execute=d.get("is_execute", True),
        able_invoked=d.get("able_invoked", False),
        datapool=d.get("datapool", "DATATABLE(NONE,false)"),
        desc=_dict_to_desc(d.get("desc")),
        schema_version=str(d.get("schema_version") or ""),
        project_id=str(d.get("project_id") or ""),
        logical_case_id=str(d.get("logical_case_id") or ""),
        automation_case_id=str(d.get("automation_case_id") or ""),
        revision_id=str(d.get("revision_id") or ""),
        case_key=str(d.get("case_key") or ""),
    )
    tc.before = _list_to_shell("before", shells.get("before"))
    tc.case = _list_to_shell("case", shells.get("case"))
    tc.after = _list_to_shell("after", shells.get("after"))
    tc.fault = _list_to_shell("fault", shells.get("fault"))
    return tc


def dict_to_testsuite(d: dict[str, Any]) -> TestSuite:
    shells = d.get("shells", {})
    ts = TestSuite(
        name=d.get("name", ""),
        data_id=d.get("data_id", ""),
        tag=d.get("tag", ""),
        datapool=d.get("datapool", "DATATABLE(NONE,true)"),
    )
    ts.before = _list_to_shell("before", shells.get("before"))
    ts.after = _list_to_shell("after", shells.get("after"))
    ts.fault = _list_to_shell("fault", shells.get("fault"))
    return ts


def _dict_to_locator(d: dict[str, Any]) -> Locator:
    loc = Locator(type=d.get("type", "XPATH"))
    if loc.type in ("AND", "OR"):
        loc.tag = d.get("tag", "")
        loc.properties = d.get("properties", []) or []
    else:
        loc.value = d.get("value", "")
        loc.mode = d.get("mode", 0)
    return loc


def _dict_to_map_element(d: dict[str, Any]) -> MapElement:
    el = MapElement(name=d.get("name", ""), comment=d.get("comment", ""))
    if "locator" in d:
        el.locator = _dict_to_locator(d["locator"])
    el.locators_by_platform = {p: _dict_to_locator(v)
                               for p, v in (d.get("locators_by_platform") or {}).items()}
    el.children = [_dict_to_map_element(c) for c in d.get("children", [])]
    return el


def dict_to_mapfile(d: dict[str, Any]) -> MapFile:
    mf = MapFile(name=d.get("name", ""))
    mf.elements = [_dict_to_map_element(e) for e in d.get("elements", [])]
    return mf


def _dict_to_local_param(d: dict[str, Any]) -> LocalParam:
    return LocalParam(
        param_id=d.get("id", ""),
        name=d.get("name", ""),
        default=d.get("default", ""),
        values=list(d.get("values", []) or []),
        required=bool(d.get("required", False)),
        datapool=d.get("datapool", ""),
        comment=d.get("comment", ""),
        visible_on_platforms=list(d.get("visible_on_platforms", []) or []),
    )


def testplan_to_dict(tp: TestPlan) -> dict[str, Any]:
    return {
        "type": "testplan",
        "format_version": FORMAT_VERSION,
        "name": tp.name,
        "dataconfig": tp.dataconfig,
        "fault_times": tp.fault_times,
        "start_time": tp.start_time,
        "end_time": tp.end_time,
        "members": list(tp.members),
    }


def dict_to_testplan(d: dict[str, Any]) -> TestPlan:
    return TestPlan(
        name=d.get("name", ""),
        dataconfig=d.get("dataconfig", ""),
        fault_times=int(d.get("fault_times", 0) or 0),
        start_time=d.get("start_time", ""),
        end_time=d.get("end_time", ""),
        members=list(d.get("members", []) or []),
    )


def dict_to_keyworddef(d: dict[str, Any]) -> KeywordDef:
    kd = KeywordDef(
        ks_id=d.get("ks_id", ""),
        data_id=d.get("data_id", ""),
        tag=d.get("tag", ""),
        params=[_dict_to_local_param(p) for p in d.get("params", [])],
    )
    kd.steps = [_dict_to_node(x) for x in d.get("steps", [])]
    return kd


# ---------- YAML 读写 ----------

def _dump_yaml(data: dict, path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False, default_flow_style=False)


def save_testcase(tc: TestCase, path: str) -> None:
    _dump_yaml(testcase_to_dict(tc), path)


def save_testsuite(ts: TestSuite, path: str) -> None:
    _dump_yaml(testsuite_to_dict(ts), path)


def save_mapfile(mf: MapFile, path: str) -> None:
    _dump_yaml(mapfile_to_dict(mf), path)


def save_keyword(kd: KeywordDef, path: str) -> None:
    _dump_yaml(keyworddef_to_dict(kd), path)


def save_testplan(tp: TestPlan, path: str) -> None:
    _dump_yaml(testplan_to_dict(tp), path)


def load(path: str):
    """按文件内 type 字段反序列化为对应模型对象。"""
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    obj_type = data.get("type")
    if obj_type == "testcase":
        obj = dict_to_testcase(data)
    elif obj_type == "testsuite":
        obj = dict_to_testsuite(data)
    elif obj_type == "mapfile":
        obj = dict_to_mapfile(data)
    elif obj_type == "keyworddef":
        obj = dict_to_keyworddef(data)
    elif obj_type == "testplan":
        obj = dict_to_testplan(data)
    else:
        raise ValueError(f"未知文件 type: {obj_type!r} ({path})")
    obj.source_path = path
    return obj
