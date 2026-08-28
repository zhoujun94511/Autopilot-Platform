"""XML（XPath）关键字（合并自 xml_kw.py / xml_ext.py）。

关键字 id 见 keyword_defs 定义（参考 align-http-protocol.md /
reverse/docs/manifests/XmlKeyword.json）。
"""

from __future__ import annotations

import os
import shutil
from typing import Any

# noinspection PyUnresolvedReferences
from lxml import etree

from ..registry import keyword, KeywordError
from ..context import ExecutionContext
from ...runtime.paths import join_project, to_native


def _to_root(xml_val: Any):
    if isinstance(xml_val, (bytes, bytearray)):
        return etree.fromstring(xml_val)
    return etree.fromstring(str(xml_val).encode("utf-8"))


def _xpath_texts(xml_val: Any, xpath: str) -> list[str]:
    root = _to_root(xml_val)
    results = root.xpath(xpath)
    texts = []
    for r in results:
        if isinstance(r, str):
            texts.append(r)
        elif hasattr(r, "text"):
            texts.append(r.text or "")
        else:
            texts.append(str(r))
    return texts


def _is_matched(matched: str) -> bool:
    return str(matched).strip().lower() in ("是", "true", "t", "1", "yes")


@keyword("xml_get_xml_value", name="获取XML值(XPath)", category="Http",
         out_params=["value"], legacy_impl="XmlKeyword:getXmlValue")
def get_xml_value(_ctx: ExecutionContext, xml="", xpath="", value="", separator=",", **_kw) -> dict:
    texts = _xpath_texts(xml, xpath)
    return {value: (separator or ",").join(texts)}


@keyword("xml_verify_xml_value", name="校验XML值(XPath)", category="Http",
         legacy_impl="XmlKeyword:verifyXmlValue")
def verify_xml_value(_ctx: ExecutionContext, xml="", xpath="", text="", matched="是",
                     mode="精确", separator=",", **_kw) -> None:
    actual = (separator or ",").join(_xpath_texts(xml, xpath))
    if mode == "包含":
        equal = str(text) in actual
    else:  # 精确
        equal = actual == str(text)
    if _is_matched(matched):
        if not equal:
            raise KeywordError(f"XML校验失败：{xpath} 期望[{text}] 实际[{actual}]")
    else:
        if equal:
            raise KeywordError(f"XML校验失败：{xpath} 不应匹配[{text}]")


# ---------------------------------------------------------------------------
# 扩展关键字（原 xml_ext.py，XmlKeyword 其余）。
# - 修改类（set/add）：解析→改→序列化回字符串存入 OUT 变量。
# - load/file 类：读文件内容存入 OUT 变量；项目根路径取自 ctx 变量 __project_path__。
# ---------------------------------------------------------------------------

def _project_path(ctx: ExecutionContext) -> str:
    """对应 Java 的 projectPath 前缀；未设置时为空（相对当前工作目录）。"""
    return str(ctx.get_var("__project_path__", "") or "")


def _resolve_path(ctx: ExecutionContext, path: str) -> str:
    path = to_native(path)
    base = _project_path(ctx)
    return join_project(base, path) if base else path


def _serialize(root) -> str:
    return etree.tostring(root, encoding="unicode")


def _select_single(root, xpath: str):
    results = root.xpath(xpath)
    if not results:
        return None
    return results[0]


def _is_true(val: Any) -> bool:
    return str(val).strip().lower() in ("是", "true", "t", "1", "yes")


# --------------------------------------------------------------------------
# 加载类
# --------------------------------------------------------------------------
@keyword("xml_load_xml_body", name="加载XML报文", category="Http",
         out_params=["xml"], legacy_impl="XmlKeyword:loadXmlBody")
def load_xml_body(ctx: ExecutionContext, xml_path="", xml="",
                  **_kw) -> dict:
    if not (xml_path and str(xml_path).strip()):
        raise KeywordError("报文文件路径xml_path，不允许为空，请检查!")
    full = _resolve_path(ctx, str(xml_path))
    if not os.path.exists(full):
        raise KeywordError(f"Xml file<{xml_path}> is not exist")
    with open(full, "r", encoding="utf-8") as f:
        content = f.read()
    # 校验可解析
    _to_root(content)
    return {xml: content}


@keyword("xml_load_xml_file", name="加载XML文件", category="Http",
         out_params=["xml"], legacy_impl="XmlKeyword:loadXmlFile")
def load_xml_file(ctx: ExecutionContext, path="", replace="否", xml="",
                  **_kw) -> dict:
    if not (path and str(path).strip()):
        raise KeywordError("Xml文件路径path，不允许为空，请检查!")
    full = _resolve_path(ctx, str(path))
    if not os.path.exists(full):
        raise KeywordError(f"Xml file<{path}> is not exist")
    with open(full, "r", encoding="utf-8") as f:
        content = f.read()
    _to_root(content)
    # replace=是 时对报文做变量替换：用 ctx 变量展开实现
    if _is_true(replace):
        content = ctx.expand_vars(content)
    return {xml: content}


# --------------------------------------------------------------------------
# 文件类
# --------------------------------------------------------------------------
# noinspection PyPep8Naming
@keyword("xml_copy", name="复制XML文件", category="Http",
         legacy_impl="XmlKeyword:copyFile")
def copy_file(ctx: ExecutionContext, srcPath="", destPath="", **_kw) -> None:
    src = _resolve_path(ctx, str(srcPath))
    dest = _resolve_path(ctx, str(destPath))
    if not os.path.exists(src):
        raise KeywordError(f"Xml file<{srcPath}> is not exist")
    dest_dir = os.path.dirname(dest)
    if dest_dir and not os.path.exists(dest_dir):
        os.makedirs(dest_dir, exist_ok=True)
    shutil.copyfile(src, dest)
    ctx.log(f"复制文件成功,新文件名为:{destPath}")


# noinspection PyPep8Naming
@keyword("xml_write", name="写入XML文件", category="Http",
         legacy_impl="XmlKeyword:writeFile")
def write_file(ctx: ExecutionContext, xmlStr="", destPath="", **_kw) -> None:
    dest = _resolve_path(ctx, str(destPath))
    dest_dir = os.path.dirname(dest)
    if dest_dir and not os.path.exists(dest_dir):
        os.makedirs(dest_dir, exist_ok=True)
    try:
        with open(dest, "w", encoding="utf-8") as f:
            f.write(str(xmlStr))
    except Exception as e:
        raise KeywordError(f"fail to Write Xml file<{destPath}> ") from e
    ctx.log(f"写入{destPath}文件成功.")


# --------------------------------------------------------------------------
# 修改类
# --------------------------------------------------------------------------
@keyword("xml_set_xml_value", name="修改XML元素内容", category="Http",
         out_params=["xml"], legacy_impl="XmlKeyword:setXmlValue")
def set_xml_value(ctx: ExecutionContext, xml="", xpath="", value="", **_kw) -> dict:
    root = _to_root(xml)
    if str(value) == "STR.Empty":
        value = ""
    el = _select_single(root, xpath)
    if el is None or not hasattr(el, "text"):
        raise KeywordError(f"Failed to find element with xpath<{xpath}>.")
    el.text = str(value)
    ctx.log(f"XML数据修改成功，Xpath <{xpath}>, Value <{value}>.")
    return {xml: _serialize(root)}


@keyword("xml_set_xml_attr_value", name="修改XML元素属性", category="Http",
         out_params=["xml"], legacy_impl="XmlKeyword:setXmlAttrValue")
def set_xml_attr_value(ctx: ExecutionContext, xml="", xpath="", name="", value="",
                       **_kw) -> dict:
    root = _to_root(xml)
    if str(value) == "STR.Empty":
        value = ""
    el = _select_single(root, xpath)
    if el is None or not hasattr(el, "set"):
        raise KeywordError(f"Failed to find element with xpath<{xpath}>.")
    el.set(str(name), str(value))
    ctx.log(f"XML元素属性值修改成功，Xpath <{xpath}>, Attribute Name <{name}>, "
            f"Value <{value}>.")
    return {xml: _serialize(root)}


@keyword("xml_add_xml_value", name="增加XML元素节点", category="Http",
         out_params=["xml"], legacy_impl="XmlKeyword:addXmlElement")
def add_xml_element(ctx: ExecutionContext, xml="", xpath="", position="中",
                    element="", value="", **_kw) -> dict:
    root = _to_root(xml)
    el = _select_single(root, xpath)
    if el is None:
        raise KeywordError(f"Failed to find element with xpath<{xpath}>.")
    new_el = el.makeelement(str(element), {})
    new_el.text = str(value)
    if position == "上":
        parent = el.getparent()
        if parent is None:
            raise KeywordError(f"Failed to find parent of xpath<{xpath}>.")
        parent.insert(parent.index(el), new_el)
    elif position == "下":
        parent = el.getparent()
        if parent is None:
            raise KeywordError(f"Failed to find parent of xpath<{xpath}>.")
        parent.insert(parent.index(el) + 1, new_el)
    else:  # 中：作为子节点追加
        el.append(new_el)
    ctx.log(f"XML数据新增成功，Xpath <{xpath}节点下>, Element <{element}>; "
            f"Value <{value}>.")
    return {xml: _serialize(root)}


# --------------------------------------------------------------------------
# 取值 / 校验类
# --------------------------------------------------------------------------
@keyword("xml_get_xml_nodeNum", name="获取XML元素个数", category="Http",
         out_params=["num"], legacy_impl="XmlKeyword:getXmlNodeNum")
def get_xml_node_num(_ctx: ExecutionContext, xml="", xpath="", num="VAR_NUM",
                     **_kw) -> dict:
    root = _to_root(xml)
    try:
        results = root.xpath(xpath)
    except etree.XPathEvalError as e:
        raise KeywordError(
            f"please check the xpath,maybe it is invalid, xpath<{xpath}>.") from e
    return {num: str(len(results))}


@keyword("xml_verify_xml_Existed", name="校验XML元素存在性", category="Http",
         legacy_impl="XmlKeyword:verifyXmlIsExisted")
def verify_xml_is_existed(_ctx: ExecutionContext, xml="", xpath="", existed="true",
                          **_kw) -> None:
    root = _to_root(xml)
    try:
        results = root.xpath(xpath)
    except etree.XPathEvalError as e:
        raise KeywordError(
            f"please check the xpath,maybe it is invalid, xpath<{xpath}>.") from e
    actual = len(results) > 0
    expected = _is_true(existed)
    if actual != expected:
        raise KeywordError(
            f"校验XML元素节点存在性失败，期望值是：{expected},实际值是：{actual}")


@keyword("xml_verify_xml_All", name="全量校验XML内容", category="Http",
         legacy_impl="XmlKeyword:verifyXmlAll")
def verify_xml_all(ctx: ExecutionContext, xml_act="", xml_exp="", **_kw) -> None:
    str_act = etree.tostring(_to_root(xml_act), encoding="unicode")
    str_exp = etree.tostring(_to_root(xml_exp), encoding="unicode")
    ctx.log(f"实际的xml报文：\n{str_act}")
    ctx.log(f"预期的xml报文：\n{str_exp}")
    if str_act != str_exp:
        raise KeywordError("校验失败：实际xml报文内容与预期xml报文内容不同，请检查!")
    ctx.log("校验通过：实际xml报文内容与预期xml报文内容相同.")


@keyword("xml_doc2_str", name="转换XML对象为字符串", category="Http",
         out_params=["xml_str"], legacy_impl="XmlKeyword:doc2String")
def doc2_string(_ctx: ExecutionContext, xml_obj="", xml_str="var_xmlStr",
                **_kw) -> dict:
    try:
        if isinstance(xml_obj, str):
            root = _to_root(xml_obj)
        elif hasattr(xml_obj, "getroottree") or hasattr(xml_obj, "tag"):
            root = xml_obj
        else:
            root = _to_root(str(xml_obj))
        result = etree.tostring(root, encoding="unicode")
    except Exception as e:
        raise KeywordError(
            "转换失败，请检查输入参数是否为加载xml报文或者加载xml文件获取的xml对象内容") from e
    return {xml_str: result}
