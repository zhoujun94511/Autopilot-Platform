"""校验类 WebUI 关键字（对应关键字分类 Verify / Common）。

涵盖：控件可见性/可用性/选中/存在/文本/属性、当前URL、弹出框文本、下拉选项校验，
以及它们的「保存校验结果」变体（不抛异常，把 true/false 结果写入 outVar）。

枚举约定：
- isVisible/isEnabled/.../matched：是/true→期望成立，否/false→期望不成立。
- mode：精确匹配/模糊匹配/正则表达式匹配（兼容 精确/包含/正则）。

校验类失败抛 KeywordError；保存类不抛，返回 {outVar: "true"/"false"}。
"""

from __future__ import annotations

import re

from ..registry import keyword, KeywordError
from ..context import ExecutionContext
from .driver import _PwElement, find_element, get_manager
from selenium.webdriver.support.ui import Select


# ---- 枚举解析 ----

def _is_yes(flag, default: bool = True) -> bool:
    s = str(flag).strip()
    if s in ("否", "false", "False", "0", "no", "No"):
        return False
    if s in ("是", "true", "True", "1", "yes", "Yes"):
        return True
    return default


def _match(actual: str, expect: str, mode: str) -> bool:
    """按 mode 判断 actual 是否匹配 expect。"""
    actual = "" if actual is None else str(actual)
    expect = "" if expect is None else str(expect)
    m = str(mode or "").strip()
    if m in ("模糊匹配", "包含", "contains"):
        return expect in actual
    if m in ("正则表达式匹配", "正则", "正则匹配", "regex"):
        return re.search(expect, actual) is not None
    # 默认精确匹配
    return actual == expect


def _verify(ok_when_match: bool, matched: bool, what: str, detail: str) -> None:
    """ok_when_match=本次条件是否成立；matched=期望成立与否。不符则抛错。"""
    if ok_when_match != matched:
        expect_desc = "应" if matched else "不应"
        raise KeywordError(f"校验失败：{what}{expect_desc}{detail}")


def _result_str(condition: bool, matched: bool) -> str:
    return "true" if (condition == matched) else "false"


# ---- 元素状态采集 ----

def _visible(ctx, locator) -> bool:
    # noinspection PyBroadException
    try:
        return find_element(ctx, locator).is_displayed()
    except Exception:
        return False


def _enabled(ctx, locator) -> bool:
    return find_element(ctx, locator).is_enabled()


def _selected(ctx, locator) -> bool:
    return find_element(ctx, locator).is_selected()


def _existed(ctx, locator) -> bool:
    # noinspection PyBroadException
    try:
        find_element(ctx, locator)
        return True
    except Exception:
        return False


def _element_text(ctx, locator) -> str:
    return find_element(ctx, locator).text


def _element_attr(ctx, locator, attribute) -> str:
    return find_element(ctx, locator).get_attribute(attribute)


def _current_url(ctx) -> str:
    return get_manager(ctx).driver().current_url


def _alert_text(ctx) -> str:
    return get_manager(ctx).driver().switch_to.alert.text


def _combo_texts(ctx, locator) -> list[str]:
    """下拉框已选选项文本（支持多选）。"""

    el = find_element(ctx, locator)
    if getattr(get_manager(ctx), "engine", "selenium") == "playwright" or isinstance(
        el, _PwElement
    ):
        return el.selected_option_texts()

    sel = Select(el)
    return [o.text for o in sel.all_selected_options]


# =====================================================================
# VerifyKeyword
# =====================================================================

# noinspection PyPep8Naming
@keyword("web_verify_element_visible", name="校验控件可见性", category="WebUI",
         legacy_impl="VerifyKeyword:verifyElementVisible")
def verify_element_visible(ctx: ExecutionContext, locator=None, isVisible="true", **_kw):
    cond = _visible(ctx, locator)
    _verify(cond, _is_yes(isVisible), "控件", "可见")


# noinspection PyPep8Naming
@keyword("web_set_element_visible_status", name="校验控件可见性(保存校验结果)", category="WebUI",
         out_params=["outVar"], legacy_impl="VerifyKeyword:setElementVisibleStatus")
def set_element_visible_status(ctx: ExecutionContext, locator=None, isVisible="true",
                               outVar="", **_kw):
    cond = _visible(ctx, locator)
    return {outVar: _result_str(cond, _is_yes(isVisible))}


# noinspection PyPep8Naming
@keyword("web_verify_element_enabled", name="校验控件可用性", category="WebUI",
         legacy_impl="VerifyKeyword:verifyElementEnabled")
def verify_element_enabled(ctx: ExecutionContext, locator=None, isEnabled="true", **_kw):
    cond = _enabled(ctx, locator)
    _verify(cond, _is_yes(isEnabled), "控件", "可用")


# noinspection PyPep8Naming
@keyword("web_set_element_enabled_status", name="校验控件可用性(保存校验结果)", category="WebUI",
         out_params=["outVar"], legacy_impl="VerifyKeyword:setElementEnabledStatus")
def set_element_enabled_status(ctx: ExecutionContext, locator=None, isEnabled="true",
                               outVar="", **_kw):
    cond = _enabled(ctx, locator)
    return {outVar: _result_str(cond, _is_yes(isEnabled))}


# noinspection PyPep8Naming
@keyword("web_verify_element_selected", name="校验控件是否已选中", category="WebUI",
         legacy_impl="VerifyKeyword:verifyElementSelected")
def verify_element_selected(ctx: ExecutionContext, locator=None, isSelected="true", **_kw):
    cond = _selected(ctx, locator)
    _verify(cond, _is_yes(isSelected), "控件", "被选中")


# noinspection PyPep8Naming
@keyword("web_set_element_selected_status", name="校验控件是否已选中(保存校验结果)", category="WebUI",
         out_params=["outVar"], legacy_impl="VerifyKeyword:setElementSelectedStatus")
def set_element_selected_status(ctx: ExecutionContext, locator=None, isSelected="true",
                                outVar="", **_kw):
    cond = _selected(ctx, locator)
    return {outVar: _result_str(cond, _is_yes(isSelected))}


# noinspection PyPep8Naming
@keyword("web_verify_element_existed", name="校验控件是否存在", category="WebUI",
         legacy_impl="VerifyKeyword:verifyElementExisted")
def verify_element_existed(ctx: ExecutionContext, locator=None, isExisted="true", **_kw):
    cond = _existed(ctx, locator)
    _verify(cond, _is_yes(isExisted), "控件", "存在")


# noinspection PyPep8Naming
@keyword("web_set_element_existed_status", name="校验控件是否存在(保存校验结果)", category="WebUI",
         out_params=["outVar"], legacy_impl="VerifyKeyword:setElementExistedStatus")
def set_element_existed_status(ctx: ExecutionContext, locator=None, isExisted="true",
                               outVar="", **_kw):
    cond = _existed(ctx, locator)
    return {outVar: _result_str(cond, _is_yes(isExisted))}


@keyword("web_verify_element_text", name="校验控件文本", category="WebUI",
         legacy_impl="VerifyKeyword:verifyElementText")
def verify_element_text(ctx: ExecutionContext, locator=None, text="", matched="true",
                        mode="精确匹配", **_kw):
    actual = _element_text(ctx, locator)
    cond = _match(actual, text, mode)
    _verify(cond, _is_yes(matched), "控件文本", f"匹配[{text}]（实际[{actual}]）")


# noinspection PyPep8Naming
@keyword("web_set_element_text_status", name="校验控件文本(保存校验结果)", category="WebUI",
         out_params=["outVar"], legacy_impl="VerifyKeyword:setElementTextStatus")
def set_element_text_status(ctx: ExecutionContext, locator=None, text="", matched="true",
                            mode="精确匹配", outVar="", **_kw):
    cond = _match(_element_text(ctx, locator), text, mode)
    return {outVar: _result_str(cond, _is_yes(matched))}


@keyword("web_verify_element_attribute", name="校验控件属性值", category="WebUI",
         legacy_impl="VerifyKeyword:verifyElementAttribute")
def verify_element_attribute(ctx: ExecutionContext, locator=None, attribute="", value="",
                             matched="true", mode="精确匹配", **_kw):
    actual = _element_attr(ctx, locator, attribute)
    cond = _match(actual, value, mode)
    _verify(cond, _is_yes(matched), f"控件属性[{attribute}]", f"匹配[{value}]（实际[{actual}]）")


# noinspection PyPep8Naming
@keyword("web_set_element_attribute_status", name="校验控件属性值(保存校验结果)", category="WebUI",
         out_params=["outVar"], legacy_impl="VerifyKeyword:setElementAttributeStatus")
def set_element_attribute_status(ctx: ExecutionContext, locator=None, attribute="", value="",
                                 matched="true", mode="精确匹配", outVar="", **_kw):
    cond = _match(_element_attr(ctx, locator, attribute), value, mode)
    return {outVar: _result_str(cond, _is_yes(matched))}


@keyword("web_verify_current_url", name="校验当前页面URL", category="WebUI",
         legacy_impl="VerifyKeyword:verifyCurrentUrl")
def verify_current_url(ctx: ExecutionContext, url="", matched="true", mode="精确匹配", **_kw):
    actual = _current_url(ctx)
    cond = _match(actual, url, mode)
    _verify(cond, _is_yes(matched), "当前URL", f"匹配[{url}]（实际[{actual}]）")


# noinspection PyPep8Naming
@keyword("web_set_current_url_status", name="校验当前页面URL(保存校验结果)", category="WebUI",
         out_params=["outVar"], legacy_impl="VerifyKeyword:setCurrentUrlStatus")
def set_current_url_status(ctx: ExecutionContext, url="", matched="true", mode="精确匹配",
                           outVar="", **_kw):
    cond = _match(_current_url(ctx), url, mode)
    return {outVar: _result_str(cond, _is_yes(matched))}


@keyword("web_verify_alert_text", name="校验弹出框文本", category="WebUI",
         legacy_impl="VerifyKeyword:verifyAlertText")
def verify_alert_text(ctx: ExecutionContext, text="", matched="true", mode="精确匹配", **_kw):
    actual = _alert_text(ctx)
    cond = _match(actual, text, mode)
    _verify(cond, _is_yes(matched), "弹出框文本", f"匹配[{text}]（实际[{actual}]）")


# noinspection PyPep8Naming
@keyword("web_set_alert_text", name="校验弹出框文本(保存校验结果)", category="WebUI",
         out_params=["outVar"], legacy_impl="VerifyKeyword:setAlertTextStatus")
def set_alert_text(ctx: ExecutionContext, text="", matched="true", mode="精确匹配",
                   outVar="", **_kw):
    cond = _match(_alert_text(ctx), text, mode)
    return {outVar: _result_str(cond, _is_yes(matched))}


@keyword("web_verify_combo_select", name="校验下拉选项文本", category="WebUI",
         legacy_impl="VerifyKeyword:verifyComboSelectOption")
def verify_combo_select(ctx: ExecutionContext, locator=None, text="", matched="true", **_kw):
    selected = _combo_texts(ctx, locator)
    expects = [t for t in str(text).split(";") if t != ""]
    # 期望的每个选项都应处于已选中状态（精确匹配文本）
    cond = all(e in selected for e in expects) if expects else False
    _verify(cond, _is_yes(matched), "下拉选项", f"已选中[{text}]（实际[{';'.join(selected)}]）")


# noinspection PyPep8Naming
@keyword("web_set_combo_select_status", name="校验下拉选项文本(保存校验结果)", category="WebUI",
         out_params=["outVar"], legacy_impl="VerifyKeyword:setComboSelectOptionStatus")
def set_combo_select_status(ctx: ExecutionContext, locator=None, text="", matched="true",
                            outVar="", **_kw):
    selected = _combo_texts(ctx, locator)
    expects = [t for t in str(text).split(";") if t != ""]
    cond = all(e in selected for e in expects) if expects else False
    return {outVar: _result_str(cond, _is_yes(matched))}


# =====================================================================
# CommonKeyword
# =====================================================================


@keyword("web_browser_killAll", name="浏览器进程清除", category="WebUI",
         legacy_impl="CommonKeyword:killAllBrowsers")
def web_browser_kill_all(ctx: ExecutionContext, **_kw):
    get_manager(ctx).quit_all()
