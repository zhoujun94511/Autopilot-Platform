"""元素级 WebUI 关键字。关键字 id 见 keyword_defs 定义（参考 align-webui-selenium.md）。

中文枚举（是/否、索引/文本）保留以兼容旧工程导入。
"""

from __future__ import annotations

import os
import time

# noinspection PyUnresolvedReferences
from selenium.webdriver.support.ui import Select
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains

from ..registry import keyword, KeywordError
from ..context import ExecutionContext
from .driver import (
    _PW_ERRS,
    _PwElement,
    find_element,
    get_manager,
    locator_to_by,
)
from ...model.mapfile import Locator


def _is_pw(ctx: ExecutionContext) -> bool:
    return getattr(get_manager(ctx), "engine", "selenium") == "playwright"


def _is_yes(flag: str, default: bool = True) -> bool:
    if flag in ("否", "false", "False", "0"):
        return False
    if flag in ("是", "true", "True", "1"):
        return True
    return default


# noinspection PyPep8Naming
@keyword("web_element_click", name="点击元素", category="WebUI",
         legacy_impl="WebElementKeyword:elementClick")
def element_click(ctx: ExecutionContext, locator=None, isScroll: str = "是",
                  scrollMode: str = "", **_kw) -> None:
    el = find_element(ctx, locator, scroll=_is_yes(isScroll), scroll_align=scrollMode)
    el.click()


# noinspection PyPep8Naming
@keyword("web_element_text_input", name="输入文本", category="WebUI",
         legacy_impl="WebElementKeyword:textInput")
def text_input(ctx: ExecutionContext, locator=None, isClear: str = "是",
               text: str = "", **_kw) -> None:
    el = find_element(ctx, locator)
    if _is_pw(ctx) or isinstance(el, _PwElement):
        # PW fill() 会整框覆盖；isClear=否 时改为追加 type
        if _is_yes(isClear):
            el.clear()
            el.send_keys(text)
        else:
            # 追加到现有 value（type 默认光标在开头，不能直接敲）
            try:
                el.handle.evaluate(
                    "(el, t) => { el.focus(); el.value = (el.value || '') + t;"
                    " el.dispatchEvent(new Event('input', {bubbles: true})); }",
                    str(text),
                )
            except _PW_ERRS:
                el.send_keys(text)
        return
    if _is_yes(isClear):
        el.clear()
    el.send_keys(text)


# noinspection PyShadowingBuiltins
@keyword("web_element_combo_select", name="下拉选择", category="WebUI",
         legacy_impl="WebElementKeyword:comboSelect")
def combo_select(ctx: ExecutionContext, locator=None, type: str = "文本",
                 value: str = "", **_kw) -> None:
    el = find_element(ctx, locator)
    parts = [p for p in str(value).split(";") if p != ""]
    try:
        if _is_pw(ctx) or isinstance(el, _PwElement):
            if type == "索引":
                idxs = [int(p) for p in parts] if parts else [int(value)]
                if len(idxs) == 1:
                    el.select_option(index=idxs[0])
                else:
                    el.select_option(index=idxs)
            elif type == "value":
                vals = parts or [value]
                el.select_option(value=vals if len(vals) > 1 else vals[0])
            else:
                labels = parts or [value]
                el.select_option(label=labels if len(labels) > 1 else labels[0])
            return
        select = Select(el)
        if type == "索引":
            for p in (parts or [str(value)]):
                select.select_by_index(int(p))
        elif type == "value":
            for p in (parts or [value]):
                select.select_by_value(p)
        else:  # 文本
            for p in (parts or [value]):
                select.select_by_visible_text(p)
    except KeywordError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise KeywordError(f"下拉选择失败(type={type!r}, value={value!r}): {exc}") from exc


# noinspection PyPep8Naming
@keyword("web_element_get_element_text", name="获取元素文本", category="WebUI",
         out_params=["outVar"], legacy_impl="WebElementKeyword:getElementText")
def get_element_text(ctx: ExecutionContext, locator=None, outVar: str = "", **_kw) -> dict:
    el = find_element(ctx, locator)
    return {outVar: el.text}


# noinspection PyPep8Naming,PyBroadException
@keyword("web_element_get_element_exist", name="判断元素存在", category="WebUI",
         out_params=["outVar"], legacy_impl="WebElementKeyword:getElementExist")
def get_element_exist(ctx: ExecutionContext, locator=None, outVar: str = "", **_kw) -> dict:
    # noinspection PyBroadException
    try:
        find_element(ctx, locator)
        exist = True
    except Exception:
        exist = False
    return {outVar: exist}


# noinspection PyPep8Naming
@keyword("web_element_get_element_attribute", name="获取元素属性", category="WebUI",
         out_params=["outVar"], legacy_impl="WebElementKeyword:getElementAttribute")
def get_element_attribute(ctx: ExecutionContext, locator=None, name: str = "",
                          outVar: str = "", **_kw) -> dict:
    # 参数 id 为 name(属性名称)——旧实现误用 attribute 形参致引擎传的 name 落空、恒取不到属性
    el = find_element(ctx, locator)
    return {outVar: el.get_attribute(name)}


def _to_locator(locator):
    """容错：字符串当 XPath 处理，其它直接当 Locator。"""
    if isinstance(locator, str):
        return Locator(type="XPATH", value=locator)
    return locator


# 修饰键中文/组合名 → selenium Keys
_MODIFIER_MAP = {
    "Ctrl": [Keys.CONTROL],
    "Shift": [Keys.SHIFT],
    "Alt": [Keys.ALT],
    "Ctrl+Shift": [Keys.CONTROL, Keys.SHIFT],
    "Ctrl+Alt": [Keys.CONTROL, Keys.ALT],
    "Alt+Shift": [Keys.ALT, Keys.SHIFT],
}

# Playwright keyboard 修饰键名
_PW_MODIFIER_MAP = {
    "Ctrl": ["Control"],
    "Shift": ["Shift"],
    "Alt": ["Alt"],
    "Ctrl+Shift": ["Control", "Shift"],
    "Ctrl+Alt": ["Control", "Alt"],
    "Alt+Shift": ["Alt", "Shift"],
}

_PW_KEY_MAP = {
    "Enter": "Enter",
    "BackSpace": "Backspace",
    "PageUp": "PageUp",
    "PageDown": "PageDown",
    "Up": "ArrowUp",
    "Down": "ArrowDown",
    "Left": "ArrowLeft",
    "Right": "ArrowRight",
    "Home": "Home",
    "End": "End",
    "Tab": "Tab",
    "Esc": "Escape",
}

# 功能键名 → selenium Keys
_KEY_MAP = {
    "Enter": Keys.ENTER,
    "BackSpace": Keys.BACK_SPACE,
    "PageUp": Keys.PAGE_UP,
    "PageDown": Keys.PAGE_DOWN,
    "Up": Keys.ARROW_UP,
    "Down": Keys.ARROW_DOWN,
    "Left": Keys.ARROW_LEFT,
    "Right": Keys.ARROW_RIGHT,
    "Home": Keys.HOME,
    "End": Keys.END,
    "Tab": Keys.TAB,
    "Esc": Keys.ESCAPE,
}


def _resolve_key(key: str):
    """普通字母/功能键名 → 发送值。"""
    return _KEY_MAP.get(key, (key or "").lower() if len(key or "") == 1 else key)


# ---------------- 点击类 ----------------

@keyword("web_element_JSclick", name="控件JS点击", category="WebUI",
         legacy_impl="WebElementKeyword:elementJSClick")
def element_js_click(ctx: ExecutionContext, locator=None, **_kw) -> None:
    """通过 JS 触发 click，绕过遮挡/不可见点击限制。"""
    el = find_element(ctx, locator)
    get_manager(ctx).driver().execute_script("arguments[0].click();", el)


@keyword("web_element_check_click", name="控件判断点击", category="WebUI",
         legacy_impl="WebElementKeyword:elementCheckAndClick")
def element_check_and_click(ctx: ExecutionContext, locator=None, timeout="5000", **_kw) -> None:
    """在 timeout(ms) 内轮询等待元素可点击后点击。"""
    deadline = time.time() + (int(timeout) / 1000.0)
    last_err = None
    while time.time() < deadline:
        try:
            el = find_element(ctx, locator)
            if el.is_displayed() and el.is_enabled():
                el.click()
                return
        except Exception as e:  # noqa: BLE001
            last_err = e
        time.sleep(0.5)
    raise KeywordError(f"控件在 {timeout}ms 内未变为可点击: {last_err}")


@keyword("web_element_scroll_click", name="控件滚动点击", category="WebUI",
         legacy_impl="WebElementKeyword:elementScrollAndClick")
def element_scroll_and_click(ctx: ExecutionContext, locator=None, **_kw) -> None:
    """滚动至元素后点击。"""
    el = find_element(ctx, locator, scroll=True)
    el.click()


@keyword("web_element_click_and_switch", name="控件点击并切至新打开窗口", category="WebUI",
         legacy_impl="WebElementKeyword:elementClickAndSwitch")
def element_click_and_switch(ctx: ExecutionContext, locator=None, timeout: str = "10000",
                             **_kw) -> None:
    """点击后切换到新打开的窗口句柄。"""
    drv = get_manager(ctx).driver()
    ms = int(str(timeout or "10000") or "10000")
    if _is_pw(ctx):
        # Playwright：用 expect_popup 捕获 window.open（仅轮询 handles 在部分环境下不可靠）
        page = drv.page
        el = find_element(ctx, locator)
        try:
            with page.expect_popup(timeout=ms) as popup_info:
                el.click()
            popup = popup_info.value
        except Exception as exc:  # noqa: BLE001 — 含 Playwright TimeoutError
            raise KeywordError("点击后未检测到新打开的窗口") from exc
        drv.page = popup
        drv.frame = None
        return
    before = set(drv.window_handles)
    find_element(ctx, locator).click()
    deadline = time.time() + (ms / 1000.0)
    while time.time() < deadline:
        new = set(drv.window_handles) - before
        if new:
            drv.switch_to.window(new.pop())
            return
        time.sleep(0.2)
    raise KeywordError("点击后未检测到新打开的窗口")


@keyword("web_element_context_click", name="控件右键点击", category="WebUI",
         legacy_impl="WebElementKeyword:elementContextClick")
def element_context_click(ctx: ExecutionContext, locator=None, **_kw) -> None:
    """对元素执行右键(上下文)点击。"""
    el = find_element(ctx, locator)
    if _is_pw(ctx) or isinstance(el, _PwElement):
        el.context_click()
        return
    ActionChains(get_manager(ctx).driver()).context_click(el).perform()


@keyword("web_element_double_click", name="控件双击", category="WebUI",
         legacy_impl="WebElementKeyword:elementDoubleClick")
def element_double_click(ctx: ExecutionContext, locator=None, **_kw) -> None:
    """对元素执行双击。"""
    el = find_element(ctx, locator)
    if _is_pw(ctx) or isinstance(el, _PwElement):
        el.double_click()
        return
    ActionChains(get_manager(ctx).driver()).double_click(el).perform()


# ---------------- 鼠标移动/拖拽 ----------------

@keyword("web_element_move", name="鼠标移动", category="WebUI",
         legacy_impl="WebElementKeyword:elementMove")
def element_move(ctx: ExecutionContext, locator=None, **_kw) -> None:
    """鼠标悬停移动到元素上。"""
    el = find_element(ctx, locator)
    if _is_pw(ctx) or isinstance(el, _PwElement):
        el.hover()
        return
    ActionChains(get_manager(ctx).driver()).move_to_element(el).perform()


@keyword("web_element_drag", name="鼠标拖拽", category="WebUI",
         legacy_impl="WebElementKeyword:elementDrag")
def element_drag(ctx: ExecutionContext, source=None, target=None, **_kw) -> None:
    """把 source 元素拖拽到 target 元素。"""
    src = find_element(ctx, source)
    tgt = find_element(ctx, target)
    if _is_pw(ctx) or isinstance(src, _PwElement):
        src.drag_to(tgt)
        return
    ActionChains(get_manager(ctx).driver()).drag_and_drop(src, tgt).perform()


def _pw_drag_by_offset(el: _PwElement, x_offset: int, y_offset: int, *, steps: int = 1) -> None:
    """Playwright：按偏移分段拖动（拼图/登录滑块）。"""
    box = el.handle.bounding_box()
    if not box:
        raise KeywordError("Playwright：无法获取元素 bounding_box，无法按偏移拖动")
    x = float(box["x"]) + float(box["width"]) / 2.0
    y = float(box["y"]) + float(box["height"]) / 2.0
    mouse = el.page.mouse
    mouse.move(x, y)
    mouse.down()
    n = max(1, int(steps))
    mouse.move(x + float(x_offset), y + float(y_offset), steps=n)
    mouse.up()


# noinspection PyPep8Naming
@keyword("web_puzzle_drag_offset", name="控件滑动", category="WebUI",
         legacy_impl="WebElementKeyword:puzzleDragByOffset")
def puzzle_drag_by_offset(ctx: ExecutionContext, locator=None, xOffset="325", yOffset="0", **_kw) -> None:
    """按偏移量拖动滑块控件（拼图/滑动验证）。"""
    el = find_element(ctx, locator)
    dx, dy = int(xOffset), int(yOffset)
    if _is_pw(ctx) or isinstance(el, _PwElement):
        _pw_drag_by_offset(el, dx, dy, steps=1)
        return
    ActionChains(get_manager(ctx).driver()).click_and_hold(el).move_by_offset(
        dx, dy).release().perform()


# noinspection PyPep8Naming
@keyword("web_element_drag_offset_forLogin", name="登录页面安全滑块拖动", category="WebUI",
         legacy_impl="WebElementKeyword:elementDragByOffsetForLogin")
def element_drag_by_offset_for_login(ctx: ExecutionContext, source=None, xOffset="325", yOffset="0", **_kw) -> None:
    """登录页安全滑块按偏移拖动（分段移动模拟人手）。"""
    el = find_element(ctx, source)
    dx, dy = int(xOffset), int(yOffset)
    if _is_pw(ctx) or isinstance(el, _PwElement):
        _pw_drag_by_offset(el, dx, dy, steps=10)
        return
    drv = get_manager(ctx).driver()
    actions = ActionChains(drv)
    actions.click_and_hold(el)
    steps = 10
    for i in range(steps):
        actions.move_by_offset(int(dx / steps), int(dy / steps))
    actions.release().perform()


# ---------------- 输入类 ----------------

@keyword("web_text_check_Input", name="文本框判断输入", category="WebUI",
         legacy_impl="WebElementKeyword:textCheckAndInput")
def text_check_and_input(ctx: ExecutionContext, locator=None, text="", timeout="5000", **_kw) -> None:
    """在 timeout(ms) 内等待文本框可用后清空并输入。"""
    deadline = time.time() + (int(timeout) / 1000.0)
    last_err = None
    while time.time() < deadline:
        try:
            el = find_element(ctx, locator)
            if el.is_displayed() and el.is_enabled():
                el.clear()
                el.send_keys(text)
                return
        except Exception as e:  # noqa: BLE001
            last_err = e
        time.sleep(0.5)
    raise KeywordError(f"文本框在 {timeout}ms 内未变为可输入: {last_err}")


# ---------------- 复选/单选 ----------------

# noinspection PyPep8Naming
@keyword("web_element_checkbox_click", name="复选框点击", category="WebUI",
         legacy_impl="WebElementKeyword:checkClick")
def check_click(ctx: ExecutionContext, locator=None, isChecked="true", isScroll="是",
                scrollMode: str = "", **_kw) -> None:
    """根据期望勾选状态点击复选框（已为目标态则不动作）。"""
    el = find_element(ctx, locator, scroll=_is_yes(isScroll), scroll_align=scrollMode)
    want = _is_yes(isChecked)
    if el.is_selected() != want:
        el.click()


# noinspection PyPep8Naming
@keyword("web_element_radio_click", name="单选框点击", category="WebUI",
         legacy_impl="WebElementKeyword:radioClick")
def radio_click(ctx: ExecutionContext, locator=None, isSelected="true", isScroll="是",
                scrollMode: str = "", **_kw) -> None:
    """根据期望选中状态点击单选框（已为目标态则不动作）。"""
    el = find_element(ctx, locator, scroll=_is_yes(isScroll), scroll_align=scrollMode)
    want = _is_yes(isSelected)
    if el.is_selected() != want:
        el.click()


# ---------------- 属性 ----------------

@keyword("web_element_set_element_attribute", name="设置控件属性值", category="WebUI",
         legacy_impl="WebElementKeyword:setElementAttribute")
def set_element_attribute(ctx: ExecutionContext, locator=None, name="", value="", **_kw) -> None:
    """通过 JS 设置元素的指定属性值。"""
    el = find_element(ctx, locator)
    get_manager(ctx).driver().execute_script(
        "arguments[0].setAttribute(arguments[1], arguments[2]);", el, name, value)


# ---------------- 获取类（输出变量） ----------------

# noinspection PyPep8Naming
@keyword("web_element_get_elements_number", name="获取控件个数", category="WebUI",
         out_params=["outVar"], legacy_impl="WebElementKeyword:getElementsNumber")
def get_elements_number(ctx: ExecutionContext, locator=None, outVar="", **_kw) -> dict:
    """统计匹配定位的元素个数。"""
    loc = _to_locator(locator)
    if not isinstance(loc, Locator):
        raise KeywordError(f"无效的元素定位: {locator!r}")
    drv = get_manager(ctx).driver()
    by, value = locator_to_by(loc)
    els = drv.find_elements(by, value)
    return {outVar: len(els)}


# noinspection PyPep8Naming
@keyword("web_element_get_element_visible", name="获取控件可见性", category="WebUI",
         out_params=["outVar"], legacy_impl="WebElementKeyword:getElementVisible")
def get_element_visible(ctx: ExecutionContext, locator=None, outVar="", **_kw) -> dict:
    """返回元素是否可见。"""
    el = find_element(ctx, locator)
    return {outVar: el.is_displayed()}


# noinspection PyPep8Naming
@keyword("web_element_get_element_enabled", name="获取控件可用性", category="WebUI",
         out_params=["outVar"], legacy_impl="WebElementKeyword:getElementEnabled")
def get_element_enabled(ctx: ExecutionContext, locator=None, outVar="", **_kw) -> dict:
    """返回元素是否可用(enabled)。"""
    el = find_element(ctx, locator)
    return {outVar: el.is_enabled()}


# noinspection PyPep8Naming
@keyword("web_element_get_element_Selected", name="获取控件选择性", category="WebUI",
         out_params=["outVar"], legacy_impl="WebElementKeyword:getElementSelected")
def get_element_selected(ctx: ExecutionContext, locator=None, outVar="", **_kw) -> dict:
    """返回元素是否被选中(selected)。"""
    el = find_element(ctx, locator)
    return {outVar: el.is_selected()}


# noinspection PyPep8Naming
@keyword("web_element_get_table_element", name="获取表格中的控件文本", category="WebUI",
         out_params=["outVar"], legacy_impl="WebElementKeyword:getTableElement")
def get_table_element(ctx: ExecutionContext, locator=None, outVar="", xpath="", col="", row="", **_kw) -> dict:
    """获取表格指定行列单元格文本（1 基行列号）。"""
    table = find_element(ctx, locator)
    r = int(row)
    c = int(col)
    if xpath:
        cell = table.find_element(By.XPATH, xpath)
    else:
        cell = table.find_element(
            By.XPATH, f".//tr[{r}]/td[{c}]")
    return {outVar: cell.text}


# ---------------- 键盘 ----------------

@keyword("web_key_press_WihtSelenium", name="键盘动作(Selenium)", category="WebUI",
         legacy_impl="WebElementKeyword:keyPressWihtSelenium")
def key_press_with_selenium(ctx: ExecutionContext, locator=None, modifierkey="", key="a", count="1", **_kw) -> None:
    """对元素发送（修饰键+键），重复 count 次（Selenium ActionChains / Playwright keyboard）。"""
    el = find_element(ctx, locator)
    if _is_pw(ctx) or isinstance(el, _PwElement):
        kb = el.page.keyboard
        try:
            el.handle.focus()
        except _PW_ERRS:
            pass
        mods = _PW_MODIFIER_MAP.get(modifierkey, [])
        press_key = _PW_KEY_MAP.get(key, (key or "").lower() if len(key or "") == 1 else key)
        for _ in range(int(count)):
            for m in mods:
                kb.down(m)
            if len(str(press_key)) == 1 and not mods:
                kb.type(str(press_key))
            else:
                kb.press(str(press_key))
            for m in reversed(mods):
                kb.up(m)
            time.sleep(1)
        return
    drv = get_manager(ctx).driver()
    mods = _MODIFIER_MAP.get(modifierkey, [])
    send_key = _resolve_key(key)
    for _ in range(int(count)):
        actions = ActionChains(drv)
        if mods:
            for m in mods:
                actions.key_down(m, el)
            actions.send_keys(send_key)
            for m in reversed(mods):
                actions.key_up(m)
        else:
            actions.send_keys_to_element(el, send_key)
        actions.perform()
        time.sleep(1)


# ---------------- 文件上传/下载（部分依赖原生） ----------------

@keyword("web_element_uploadfile_common", name="文件上传_普通", category="WebUI",
         legacy_impl="WebElementKeyword:uploadFile")
def upload_file(ctx: ExecutionContext, locator=None, text="", **_kw) -> None:
    """普通 input[type=file] 上传：直接向元素 send_keys 文件路径。"""
    path = str(text or "")
    if not path or not os.path.isfile(path):
        raise KeywordError(f"上传文件不存在: {path!r}")
    el = find_element(ctx, locator)
    el.send_keys(path)


