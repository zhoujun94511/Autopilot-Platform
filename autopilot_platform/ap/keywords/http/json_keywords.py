"""JSON 关键字（JsonPath + 老式 xpath，合并自 json_kw.py / json_ext.py）。

关键字 id 见 keyword_defs 定义（参考 align-http-protocol.md /
reverse/docs/manifests/JSONKeyword.json）。

两套路径风格：
- jsonpath 风格（*ByJsonPath / addJsonElement / deleteJsonElement /
  setJsonValueByJsonPath）：jsonpath 抬头用 `#` 代替 `$`，同时兼容
  `#`/`$` 两种写法。
- 老式 xpath（setJsonValue/getJsonValue/getJsonValuesNum/getStrsXkeyValue/
  jsonExistNodeByXpath/verifyJsonValue）：`a/b[0]/c` 斜杠分隔、`[i]` 下标，
  这里转换成 jsonpath 后用 jsonpath-ng 求值。
"""

from __future__ import annotations

import json as _json
import os
import re
from typing import Any

# noinspection PyUnresolvedReferences
from jsonpath_ng.ext import parse as jsonpath_parse

from ..registry import keyword, KeywordError
from ..context import ExecutionContext
from ...runtime.paths import to_native


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------

def _as_obj(json_val: Any) -> Any:
    if isinstance(json_val, (dict, list)):
        return json_val
    return _json.loads(str(json_val))


def _find(json_val: Any, path: str) -> list:
    obj = _as_obj(json_val)
    return [m.value for m in jsonpath_parse(path).find(obj)]


def _is_matched(matched: str) -> bool:
    return str(matched).strip().lower() in ("是", "true", "t", "1", "yes")


def _to_str(json_obj: Any) -> str:
    if isinstance(json_obj, str):
        return json_obj
    return _json.dumps(json_obj, ensure_ascii=False)


def _is_legal_json(s: str) -> bool:
    # noinspection PyBroadException
    try:
        _json.loads(s)
        return True
    except Exception:
        return False


def _xpath_to_jsonpath(xpath: str) -> str:
    """老式 xpath（a/b[0]/c）转 jsonpath（$.a.b[0].c）。"""
    p = str(xpath).strip()
    if p.startswith("$"):
        return p
    if p.startswith("#"):
        p = "$" + p[1:]
        return p
    p = p.strip("/")
    parts = [seg for seg in p.split("/") if seg != ""]
    out = "$"
    for seg in parts:
        m = re.match(r"^([^\[\]]+)((?:\[\d+])*)$", seg)
        if m:
            out += "." + m.group(1) + (m.group(2) or "")
        else:
            out += "." + seg
    return out


def _normalize_jsonpath(jpath: str) -> str:
    """jsonpath 风格参数：抬头 `#` 转 `$`，已是 `$` 原样返回。"""
    p = str(jpath)
    if not p:
        raise KeywordError("jsonpath输入错误，请参照jsonpath语法，并将抬头的 $ 替换为 # ")
    if p.startswith("#"):
        return "$" + p[1:]
    if p.startswith("$"):
        return p
    raise KeywordError("jsonpath输入错误，请参照jsonpath语法，并将抬头的 $ 替换为 # ")


def _coerce_value(value: str) -> Any:
    """模仿 Java：尝试把字符串 value 转成 int/float/bool/null/嵌套JSON。"""
    if isinstance(value, (dict, list, int, float, bool)) or value is None:
        return value
    s = str(value)
    if re.match(r"^[0-9]+$", s):
        return int(s)
    if re.match(r"^[0-9]+\.[0-9]+$", s):
        return float(s)
    if s == "true":
        return True
    if s == "false":
        return False
    if s == "null":
        return None
    if (s.startswith("{") and s.endswith("}")) or (s.startswith("[") and s.endswith("]")):
        # noinspection PyBroadException
        try:
            return _json.loads(s)
        except Exception:
            return s
    if s.startswith('"') and s.endswith('"') and len(s) >= 2:
        return s[1:-1]
    return s


# ---------------------------------------------------------------------------
# JsonPath 风格关键字（原 json_kw.py）
# ---------------------------------------------------------------------------

# noinspection PyShadowingBuiltins
@keyword("json_get_json_value_byjsonpath", name="获取JSON值(JsonPath)", category="Http",
         out_params=["value"], legacy_impl="JSONKeyword:getJsonValueByJsonPath")
def get_json_value(_ctx: ExecutionContext, json="", jsonpath="", value="", **_kw) -> dict:
    matches = _find(json, jsonpath)
    result = matches[0] if matches else ""
    return {value: result}


# noinspection PyShadowingBuiltins
@keyword("json_verify_json_value_ByJsonPath", name="校验JSON值(JsonPath)", category="Http",
         legacy_impl="JSONKeyword:verifyJsonValueByJsonPath")
def verify_json_value(_ctx: ExecutionContext, json="", jsonpath="", text="", matched="是", **_kw) -> None:
    matches = _find(json, jsonpath)
    actual = str(matches[0]) if matches else ""
    equal = actual == str(text)
    if _is_matched(matched):
        if not equal:
            raise KeywordError(f"JSON校验失败：{jsonpath} 期望[{text}] 实际[{actual}]")
    else:
        if equal:
            raise KeywordError(f"JSON校验失败：{jsonpath} 不应等于[{text}]")


# noinspection PyShadowingBuiltins
@keyword("json_exist_key_byjsonpath", name="判断JSON节点存在(JsonPath)", category="Http",
         legacy_impl="JSONKeyword:jsonExistNodeByJsonPath")
def exist_key(_ctx: ExecutionContext, json="", jsonpath="", matched="是", **_kw) -> None:
    exist = len(_find(json, jsonpath)) > 0
    if _is_matched(matched):
        if not exist:
            raise KeywordError(f"JSON节点不存在：{jsonpath}")
    else:
        if exist:
            raise KeywordError(f"JSON节点不应存在：{jsonpath}")


# noinspection PyShadowingBuiltins
@keyword("json_load_json_file_fastjson", name="加载JSON文件", category="Http",
         out_params=["json"], legacy_impl="JSONKeyword:loadJsonFileFastJson")
def load_json_file(_ctx: ExecutionContext, path="", json="", **_kw) -> dict:
    if not os.path.exists(path):
        raise KeywordError(f"JSON文件不存在: {path}")
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    return {json: content}


# ---------------------------------------------------------------------------
# 加载文件（老式，原 json_ext.py）
# ---------------------------------------------------------------------------

# noinspection PyShadowingBuiltins
@keyword("json_load_json_file", name="加载JSON文件", category="Http",
         out_params=["json"], legacy_impl="JSONKeyword:loadJSONFile")
def load_json_file_xpath(_ctx: ExecutionContext, path="", json="", **_kw) -> dict:
    p = to_native(path)
    if not os.path.exists(p):
        raise KeywordError(f"Json file<{path}> is not exist")
    with open(p, "r", encoding="utf-8") as f:
        content = f.read()
    return {json: content}


# ---------------------------------------------------------------------------
# 修改元素（老式 xpath）
# ---------------------------------------------------------------------------

@keyword("json_set_json_value", name="修改JSON元素内容", category="Http",
         out_params=["json"], legacy_impl="JSONKeyword:setJsonValue")
def set_json_value(_ctx: ExecutionContext, json="", xpath="", value="", **_kw) -> dict:
    obj = _as_obj(json)
    jpath = _xpath_to_jsonpath(xpath)
    expr = jsonpath_parse(jpath)
    matches = expr.find(obj)
    if not matches:
        raise KeywordError(f"Failed to find element with xpath<{xpath}>.")
    # selection 为 true 时按下拉/选中语义处理；这里统一原样写入 value 文本
    expr.update(obj, value)
    return {json: _to_str(obj)}


@keyword("json_set_json_value_byjsonpath", name="修改JSON元素内容(JSONPATH)", category="Http",
         out_params=["json"], legacy_impl="JSONKeyword:setJsonValueByJsonPath")
def set_json_value_by_jsonpath(_ctx: ExecutionContext, json="", jsonpath="", value="", **_kw) -> dict:
    src = _to_str(json)
    if not _is_legal_json(src):
        raise KeywordError("被修改的json文件格式不正确，请检查")
    jpath = _normalize_jsonpath(jsonpath)
    obj = _json.loads(src)
    expr = jsonpath_parse(jpath)
    if not expr.find(obj):
        raise KeywordError(f"修改元素出现异常，未找到路径：{jsonpath}")
    expr.update(obj, _coerce_value(value))
    return {json: _to_str(obj)}


# ---------------------------------------------------------------------------
# 增加元素
# ---------------------------------------------------------------------------

@keyword("json_add_json_value", name="增加JSON元素内容", category="Http",
         out_params=["json"], legacy_impl="JSONKeyword:addJsonElement")
def add_json_element(_ctx: ExecutionContext, json="", jsonpath="", key="", value="", **_kw) -> dict:
    src = _to_str(json)
    if not _is_legal_json(src):
        raise KeywordError("被修改的json文件格式不正确，请检查")
    jpath = _normalize_jsonpath(jsonpath)
    if not _is_legal_json('{"' + str(key) + '":' + str(value) + "}") and not _is_legal_json(str(value)):
        raise KeywordError("输入的value格式不正确，请检查")
    obj = _json.loads(src)
    matches = jsonpath_parse(jpath).find(obj)
    if not matches:
        raise KeywordError(f"选择的JSON路径下并不能插入新节点：{jsonpath}")
    added = _coerce_value(value)
    for m in matches:
        target = m.value
        if isinstance(target, dict):
            target[key] = added
        elif isinstance(target, list):
            target.append(added)
        else:
            raise KeywordError("选择的JSON路径下并不能插入新节点")
    return {json: _to_str(obj)}


# ---------------------------------------------------------------------------
# 删除元素
# ---------------------------------------------------------------------------

@keyword("json_delete_json_value", name="删除JSON元素内容", category="Http",
         out_params=["json"], legacy_impl="JSONKeyword:deleteJsonElement")
def delete_json_element(_ctx: ExecutionContext, json="", jsonpath="", **_kw) -> dict:
    src = _to_str(json)
    if not _is_legal_json(src):
        raise KeywordError("被修改的json文件格式不正确，请检查")
    jpath = _normalize_jsonpath(jsonpath)
    obj = _json.loads(src)
    try:
        jsonpath_parse(jpath).filter(lambda _v: True, obj)
    except Exception as e:
        raise KeywordError(f"删除元素出现异常，异常信息：{e}")
    return {json: _to_str(obj)}


# ---------------------------------------------------------------------------
# 取值（老式 xpath）
# ---------------------------------------------------------------------------

@keyword("json_get_json_value", name="获取JSON元素内容", category="Http",
         out_params=["value"], legacy_impl="JSONKeyword:getJsonValue")
def get_json_value_xpath(_ctx: ExecutionContext, json="", xpath="", value="", **_kw) -> dict:
    matches = _find(json, _xpath_to_jsonpath(xpath))
    result = matches[0] if matches else ""
    if isinstance(result, (dict, list)):
        result = _to_str(result)
    return {value: result}


@keyword("json_get_json_values_num", name="获取JSON属性值数", category="Http",
         out_params=["num"], legacy_impl="JSONKeyword:getJsonValuesNum")
def get_json_values_num(_ctx: ExecutionContext, json="", xpath="", num="", **_kw) -> dict:
    matches = _find(json, _xpath_to_jsonpath(xpath))
    # 若命中单个数组，返回数组长度；否则返回命中个数
    if len(matches) == 1 and isinstance(matches[0], list):
        n = len(matches[0])
    else:
        n = len(matches)
    return {num: str(n)}


@keyword("json_get_json_values_num_byjsonpath", name="获取JSON属性值数(JSONPATH)", category="Http",
         out_params=["num"], legacy_impl="JSONKeyword:getJsonValuesNumByJsonPath")
def get_json_values_num_by_jsonpath(_ctx: ExecutionContext, json="", jsonpath="", num="", **_kw) -> dict:
    src = _to_str(json)
    if not _is_legal_json(src):
        raise KeywordError("json文件格式不正确，请检查")
    matches = _find(src, _normalize_jsonpath(jsonpath))
    if len(matches) == 1 and isinstance(matches[0], list):
        n = len(matches[0])
    else:
        n = len(matches)
    return {num: str(n)}


# ---------------------------------------------------------------------------
# 取数组子节点元素值
# ---------------------------------------------------------------------------

def _strs_xkey_value(arr: list, key: str, value: str, key2: str) -> str:
    for item in arr:
        if not isinstance(item, dict):
            continue
        if str(item.get(key, "")) == str(value):
            return str(item.get(key2, ""))
    raise KeywordError(f"json数组下不存在满足查询条件的内容，条件是：{key}={value}")


@keyword("json_get_Strs_Xkey_Value", name="获取JSON某数组的子节点元素值", category="Http",
         out_params=["value2"], legacy_impl="JSONKeyword:getStrsXkeyValue")
def get_strs_xkey_value(_ctx: ExecutionContext, json="", xpath="", key="", value="",
                        key2="", value2="var_value", **_kw) -> dict:
    matches = _find(json, _xpath_to_jsonpath(xpath))
    arr = matches[0] if (matches and isinstance(matches[0], list)) else matches
    if not arr:
        raise KeywordError(f"根据给出的路径无法查出对应的数组或查询的数组个数为0：{xpath}")
    result = _strs_xkey_value(arr, key, value, key2)
    return {value2: result}


@keyword("json_get_Strs_Xkey_Value_ByJsonPath", name="获取JSON某数组的子节点元素值(JSONPATH)", category="Http",
         out_params=["value2"], legacy_impl="JSONKeyword:getStrsXkeyValueByJsonPath")
def get_strs_xkey_value_by_jsonpath(_ctx: ExecutionContext, json="", jsonpath="", key="", value="",
                                    key2="", value2="var_value", **_kw) -> dict:
    src = _to_str(json)
    matches = _find(src, _normalize_jsonpath(jsonpath))
    arr = matches[0] if (matches and isinstance(matches[0], list)) else matches
    if not arr:
        raise KeywordError(f"根据给出的路径无法查出对应的数组或查询的数组个数为0：{jsonpath}")
    result = _strs_xkey_value(arr, key, value, key2)
    return {value2: result}


# ---------------------------------------------------------------------------
# 校验 / 节点存在（老式 xpath）
# ---------------------------------------------------------------------------

@keyword("json_verify_json_value", name="校验JSON元素内容", category="Http",
         legacy_impl="JSONKeyword:verifyJsonValue")
def verify_json_value_xpath(_ctx: ExecutionContext, json="", xpath="", text="", matched="true", **_kw) -> None:
    matches = _find(json, _xpath_to_jsonpath(xpath))
    actual = str(matches[0]) if matches else ""
    equal = actual == str(text)
    if _is_matched(matched):
        if not equal:
            raise KeywordError(f"JSON校验失败：{xpath} 期望[{text}] 实际[{actual}]")
    else:
        if equal:
            raise KeywordError(f"JSON校验失败：{xpath} 不应等于[{text}]")


@keyword("json_exist_key", name="判断JSON中是否存在指定节点", category="Http",
         legacy_impl="JSONKeyword:jsonExistNodeByXpath")
def json_exist_node_by_xpath(_ctx: ExecutionContext, json="", xpath="", matched="true", **_kw) -> None:
    exist = len(_find(json, _xpath_to_jsonpath(xpath))) > 0
    if _is_matched(matched):
        if not exist:
            raise KeywordError(f"JSON节点不存在：{xpath}")
    else:
        if exist:
            raise KeywordError(f"JSON节点不应存在：{xpath}")


# ---------------------------------------------------------------------------
# 转字符串
# ---------------------------------------------------------------------------

@keyword("json_to_string", name="JSON对象转字符串", category="Http",
         out_params=["string"], legacy_impl="JSONKeyword:jsonToString")
def json_to_string(_ctx: ExecutionContext, json="", string="", **_kw) -> dict:
    obj = _as_obj(json)
    return {string: _to_str(obj)}


# ---------------------------------------------------------------------------
# 全量校验
# ---------------------------------------------------------------------------

# noinspection PyPep8Naming
@keyword("json_comp", name="JSON全量校验", category="Http",
         legacy_impl="JSONKeyword:jsonComppareAll")
def json_compare_all(_ctx: ExecutionContext, jString1="", jString2="", **_kw) -> None:
    s1, s2 = str(jString1).strip(), str(jString2).strip()
    both_arr = s1.startswith("[") and s2.startswith("[") and s1.endswith("]") and s2.endswith("]")
    both_obj = s1.startswith("{") and s2.startswith("{") and s1.endswith("}") and s2.endswith("}")
    if not (both_arr or both_obj):
        raise KeywordError("JSON全量校验失败:数据不是有效的JSON格式")
    # noinspection PyBroadException
    try:
        o1, o2 = _json.loads(s1), _json.loads(s2)
    except Exception:
        raise KeywordError("JSON全量校验失败:数据不是有效的JSON格式")
    # NON_EXTENSIBLE：键集合需完全一致（不允许多余字段），值递归相等
    if not _json_equal_strict(o1, o2):
        raise KeywordError("JSON全量校验失败！")


def _json_equal_strict(a: Any, b: Any) -> bool:
    if isinstance(a, dict) and isinstance(b, dict):
        if set(a.keys()) != set(b.keys()):
            return False
        return all(_json_equal_strict(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return False
        return all(_json_equal_strict(x, y) for x, y in zip(a, b))
    return a == b
