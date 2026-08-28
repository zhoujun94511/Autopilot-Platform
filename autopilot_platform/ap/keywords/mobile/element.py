"""移动端元素关键字。关键字 id 见 keyword_defs 定义（参考 align-mobile-appium.md）。

textInput 简化为 send_keys（现代 Appium 支持 unicode），不走 adb/IME。
swipe 用 W3C Actions 在元素中心按 direction 滑动。
"""

from __future__ import annotations

import time

from ..registry import keyword, KeywordError
from ..context import ExecutionContext
from .driver import find_element, get_manager, screen_locate, tap_xy
from .picture_locator import accuracy_to_threshold, is_picture_locator
from ...mobile.adb import ensure_adb, adb_shell, require_adb_input_safe_text, require_adb_shell_safe_token
from ...mobile.ios import driver_backend as ios_driver_backend, js_click_element as ios_js_click_element


def _is_yes(v) -> bool:
    return str(v).strip().lower() in ("是", "true", "1", "yes", "y", "t")


def _serial(ctx):
    # noinspection PyBroadException
    try:
        caps = get_manager(ctx).driver().capabilities
        return caps.get("udid") or caps.get("deviceName") or ""
    except Exception:
        return ""


def _adb_input_text(text: str, serial: str = "") -> None:
    """通过 adb shell input text 输入文本（空格转 %s，无文本则跳过）。"""
    if text is None or text == "":
        return

    # adb shell input text 不接受裸空格，须转义为 %s；拒 shell 元字符（AUD-2026-10）
    payload = require_adb_input_safe_text(text).replace(" ", "%s")
    adb_shell(f"input text {payload}", serial=serial)


@keyword("mobile_element_click", name="点击元素", category="Mobile",
         legacy_impl="MobileElementKeyword:elementClick")
def element_click(ctx: ExecutionContext, locator=None, timeout="", accuracy="", **_kw) -> None:
    # 图像识别点击：截屏匹配模板图 → tap；否则常规元素点击（timeout 内等元素出现）
    if is_picture_locator(locator if isinstance(locator, str) else ""):
        pos = screen_locate(ctx, locator, threshold=accuracy_to_threshold(accuracy))
        if pos is None:
            raise KeywordError(f"图像未匹配: {locator!r}")
        tap_xy(ctx, pos[0], pos[1])
        return
    find_element(ctx, locator, timeout).click()


@keyword("mobile_element_text_input", name="输入文本", category="Mobile",
         legacy_impl="MobileElementKeyword:textInput")
def text_input(ctx: ExecutionContext, locator=None, text: str = "", timeout="", **_kw) -> None:
    find_element(ctx, locator, timeout).send_keys(text)


# noinspection PyPep8Naming
@keyword("mobile_element_text_clear", name="清除文本", category="Mobile",
         legacy_impl="MobileElementKeyword:textClear")
def text_clear(ctx: ExecutionContext, locator=None, isPassword="", times="",
               timeout="", **_kw) -> None:
    # 普通输入框直接 clear()；密码框读不到 text、clear 常失效 → 聚焦后按 times 次删除键清空
    el = find_element(ctx, locator, timeout)
    if _is_yes(isPassword):
        n = int(times) if str(times).strip().isdigit() else 30
        # noinspection PyBroadException
        try:
            el.click()          # 聚焦
        except Exception:
            pass
        mgr = get_manager(ctx)
        drv = mgr.driver()
        from ...mobile.ios.keys import press_delete_keys
        backend = ios_driver_backend(drv, getattr(mgr, "backend", "") or "")
        platform = getattr(mgr, "platform", "") or ""
        if platform == "ios" or hasattr(drv, "wda_client") or hasattr(drv, "press_delete"):
            press_delete_keys(drv, backend or "wda", n)
        elif hasattr(drv, "press_keycode"):
            for _ in range(max(n, 0)):
                drv.press_keycode(67)
        elif hasattr(drv, "keyevent"):
            for _ in range(max(n, 0)):
                drv.keyevent(67)
    else:
        el.clear()


# noinspection PyPep8Naming
@keyword("mobile_element_get_element_text", name="获取元素文本", category="Mobile",
         out_params=["outVar"], legacy_impl="MobileElementKeyword:getElementText")
def get_element_text(ctx: ExecutionContext, locator=None, outVar: str = "", **_kw) -> dict:
    return {outVar: find_element(ctx, locator).text}


# noinspection PyPep8Naming
@keyword("mobile_element_get_element_exist", name="判断元素存在", category="Mobile",
         out_params=["outVar"], legacy_impl="MobileElementKeyword:getElementExist")
def get_element_exist(ctx: ExecutionContext, locator=None, outVar: str = "",
                      timeout="", **_kw) -> dict:
    # timeout 内等元素出现再判定（对齐参考"最多等 N 秒再判断存在"）
    # noinspection PyBroadException
    try:
        find_element(ctx, locator, timeout)
        exist = True
    except Exception:
        exist = False
    return {outVar: exist}



@keyword("mobile_element_swipe", name="滑动元素", category="Mobile",
         legacy_impl="MobileElementKeyword:elementSwipe")
def element_swipe(ctx: ExecutionContext, locator=None, direction: str = "上", **_kw) -> None:
    mgr = get_manager(ctx)
    el = find_element(ctx, locator)
    drv = mgr.driver()
    from ...mobile.ios.gesture import swipe_element
    swipe_element(
        drv, el, direction,
        backend=ios_driver_backend(drv, mgr.backend) if mgr.platform == "ios" else "",
    )


# --------------------------------------------------------------------------
# 属性 / 状态查询
# --------------------------------------------------------------------------
# noinspection PyPep8Naming
@keyword("mobile_element_get_element_attribute", name="获取控件属性(mobile/wap)",
         category="Mobile", out_params=["outVar"],
         legacy_impl="MobileElementKeyword:getElementAttribute")
def get_element_attribute(ctx: ExecutionContext, locator=None, attribution: str = "",
                          outVar: str = "", **_kw) -> dict:
    mgr = get_manager(ctx)
    el = find_element(ctx, locator)
    from ...mobile.ios.attributes import read_element_attribute
    result = read_element_attribute(
        el, attribution or "",
        platform=mgr.platform or "",
        driver=mgr.driver(),
    )
    return {outVar: result}


# noinspection PyPep8Naming
@keyword("mobile_element_get_element_visible", name="获取控件可见性(mobile/wap)",
         category="Mobile", out_params=["outVar"],
         legacy_impl="MobileElementKeyword:getElementVisible")
def get_element_visible(ctx: ExecutionContext, locator=None, outVar: str = "",
                        timeout="", **_kw) -> dict:
    # noinspection PyBroadException
    try:
        el = find_element(ctx, locator, timeout)
        visible = bool(el.is_displayed())
    except Exception:
        visible = False
    return {outVar: visible}


# noinspection PyPep8Naming
@keyword("mobile_element_get_element_enabled", name="获取控件可用性(mobile/wap)",
         category="Mobile", out_params=["outVar"],
         legacy_impl="MobileElementKeyword:getElementEnabled")
def get_element_enabled(ctx: ExecutionContext, locator=None, outVar: str = "",
                        timeout="", **_kw) -> dict:
    # noinspection PyBroadException
    try:
        el = find_element(ctx, locator, timeout)
        enabled = bool(el.is_enabled())
    except Exception:
        enabled = False
    return {outVar: enabled}


# --------------------------------------------------------------------------
# 点击系列
# --------------------------------------------------------------------------
@keyword("mobile_element_continuous_click", name="控件连续点击(mobile)",
         category="Mobile",
         legacy_impl="MobileElementKeyword:elementContinuousClick")
def element_continuous_click(ctx: ExecutionContext, locator=None,
                             count: str = "1", duration: str = "100",
                             timeout="", **_kw) -> None:
    n = int(count or 1)
    gap = int(duration or 100) / 1000.0
    for i in range(n):
        find_element(ctx, locator, timeout).click()
        if i < n - 1 and gap > 0:
            time.sleep(gap)


@keyword("mobile_element_shift_click", name="[公用]控件点击+偏移量(mobile)",
         category="Mobile",
         legacy_impl="MobileElementKeyword:elementShiftClick")
def element_shift_click(ctx: ExecutionContext, locator=None, horizontal: str = "",
                        vertical: str = "", **_kw) -> None:
    # 偏移量为元素尺寸百分比(0~100，夹紧)：0=左/上边、50=中心、100=右/下边。
    # 原实现仅在 0<h<100 且 0<v<100 才点击，传 0/100/越界时静默不动——此处修正为夹紧后必点。
    from .session import _tap_xy           # 懒加载，避免与 session 循环导入
    h = max(0.0, min(100.0, float(horizontal or 0)))
    v = max(0.0, min(100.0, float(vertical or 0)))
    el = find_element(ctx, locator)
    loc, size = el.location, el.size
    x = int(loc["x"]) + int(size["width"] * h / 100)
    y = int(loc["y"]) + int(size["height"] * v / 100)
    _tap_xy(get_manager(ctx).driver(), x, y)
    time.sleep(1)


@keyword("mobile_element_JS_click", name="控件JS点击(wap)", category="Mobile",
         legacy_impl="MobileElementKeyword:elementJSClick")
def element_js_click(ctx: ExecutionContext, locator=None, timeout="", **_kw) -> None:
    mgr = get_manager(ctx)
    el = find_element(ctx, locator, timeout)
    backend = ios_driver_backend(mgr.driver(), mgr.backend)
    ios_js_click_element(mgr.driver(), backend, el)


@keyword("mobile_any_element_click", name="点击任意位置控件(wap)", category="Mobile",
         legacy_impl="MobileElementKeyword:anyElementClick")
def any_element_click(ctx: ExecutionContext, locator=None, **_kw) -> None:
    # 任意位置点击：定位到元素后直接点击
    find_element(ctx, locator).click()


# --------------------------------------------------------------------------
# 输入系列（依赖 adb，缓做）
# --------------------------------------------------------------------------
# noinspection PyShadowingBuiltins
@keyword("mobile_element_text_input_adb", name="adb输入法文本框文本输入(mobile/wap)",
         category="Mobile",
         legacy_impl="MobileElementKeyword:textInputByAdb")
def text_input_by_adb(ctx: ExecutionContext, locator=None, text: str = "",
                      type: str = "text", **_kw) -> None:
    # 先定位并点击/聚焦元素，再用 adb shell input text 输入
    serial = _serial(ctx)
    el = find_element(ctx, locator)
    # noinspection PyBroadException
    try:
        el.click()
    except Exception:
        # 聚焦失败不阻断输入
        pass
    if str(type).strip() == "keyevent":

        ensure_adb()
        code = require_adb_shell_safe_token(text, what="keyevent")
        adb_shell(f"input keyevent {code}", serial=serial)
    else:
        _adb_input_text(text, serial)


# noinspection PyShadowingBuiltins
@keyword("mobile_element_adb_input_text", name="adb命令文本框文本输入(mobile)",
         category="Mobile",
         legacy_impl="MobileElementKeyword:adbInputCmd")
def adb_input_cmd(ctx: ExecutionContext, text: str = "",
                  type: str = "text", **_kw) -> None:
    # type=keyevent 时走 input keyevent；否则 input text（空格转 %s）
    serial = _serial(ctx)
    if str(type).strip() == "keyevent":

        ensure_adb()
        code = require_adb_shell_safe_token(text, what="keyevent")
        adb_shell(f"input keyevent {code}", serial=serial)
    else:
        _adb_input_text(text, serial)


# --------------------------------------------------------------------------
# 选择控件
# --------------------------------------------------------------------------
# noinspection PyShadowingBuiltins
@keyword("mobile_element_combo_select", name="下拉列表选择(mobile)", category="Mobile",
         legacy_impl="MobileElementKeyword:comboSelect")
def combo_select(ctx: ExecutionContext, locator=None, type: str = "内容",
                 value: str = "", **_kw) -> None:
    mgr = get_manager(ctx)
    el = find_element(ctx, locator)
    if mgr.platform == "ios":
        # WebView 内 HTML <select> 仍用 Selenium；原生控件走点击点选
        tag = ""
        # noinspection PyBroadException
        try:
            tag = (el.tag_name or "").lower()
        except Exception:
            pass
        if tag == "select":
            from selenium.webdriver.support.ui import Select
            sel = Select(el)
            if type == "索引":
                sel.select_by_index(int(value))
            else:
                sel.select_by_visible_text(value)
            return
        from ...mobile.ios.picker import ios_combo_select
        # noinspection PyBroadException
        try:
            ios_combo_select(mgr.driver(), el, type, value)
        except ValueError as e:
            raise KeywordError(str(e)) from e
        return
    from selenium.webdriver.support.ui import Select
    sel = Select(el)
    if type == "索引":
        sel.select_by_index(int(value))
    else:
        sel.select_by_visible_text(value)


# noinspection PyPep8Naming
@keyword("mobile_element_radio_click", name="单选框点击(mobile)", category="Mobile",
         legacy_impl="MobileElementKeyword:radioClick")
def radio_click(ctx: ExecutionContext, locator=None, isSelected: str = "true",
                **_kw) -> None:
    want = str(isSelected).lower() == "true"
    el = find_element(ctx, locator)
    if el.is_selected() != want:
        el.click()


# noinspection PyPep8Naming
@keyword("mobile_element_check_select", name="多选框点击(mobile)", category="Mobile",
         legacy_impl="MobileElementKeyword:checkSelect")
def check_select(ctx: ExecutionContext, locator=None, isSelected: str = "true",
                 **_kw) -> None:
    want = str(isSelected).lower() == "true"
    el = find_element(ctx, locator)
    if el.is_selected() != want:
        el.click()


# --------------------------------------------------------------------------
# 滑动登录 / 键盘遮挡 / Activity 切换
# --------------------------------------------------------------------------
@keyword("swipe_login", name="滑动登录（若存在）", category="Mobile",
         legacy_impl="MobileElementKeyword:swipeLogin")
def swipe_login(ctx: ExecutionContext, locator=None, timeout="", **_kw) -> None:
    # 探针性质"存在才滑"：默认只等 3s，避免无滑块时白等 30s；用户传 timeout 则尊重
    # noinspection PyBroadException
    try:
        mgr = get_manager(ctx)
        el = find_element(ctx, locator, timeout or "3000")
        if el.is_displayed():
            from ...mobile.ios.gesture import swipe_element_horizontal
            drv = mgr.driver()
            swipe_element_horizontal(
                drv, el,
                backend=ios_driver_backend(drv, mgr.backend) if mgr.platform == "ios" else "",
            )
    except Exception:
        # 与 Java 一致：滑块不存在时忽略
        pass


@keyword("Shelter", name="智能防键盘遮挡", category="Mobile",
         legacy_impl="MobileElementKeyword:Shelter")
def shelter(ctx: ExecutionContext, locator=None, **_kw) -> None:
    driver = get_manager(ctx).driver()
    # noinspection PyBroadException
    try:
        from .driver import locator_to_by
        from ...model.mapfile import Locator
        loc = locator if not isinstance(locator, str) else Locator(type="XPATH", value=locator)
        by, value = locator_to_by(loc)
        found = driver.find_elements(by, value)
    except Exception:
        found = []
    if len(found) > 0:
        # 控件未被遮挡，正常继续
        return
    # 控件被键盘遮挡，回退键收起键盘
    if hasattr(driver, "back"):
        driver.back()
    elif hasattr(driver, "press_keycode"):
        driver.press_keycode(4)  # KEYCODE_BACK


@keyword("mobile_activity_switch", name="Activity来回切换(mobile)", category="Mobile",
         legacy_impl="MobileElementKeyword:activitySwitch")
def activity_switch(ctx: ExecutionContext, locator=None,
                    times: str = "10", timeout="", **_kw) -> None:
    n = int(times or 10)
    if n > 40:
        n = 40
    driver = get_manager(ctx).driver()
    # noinspection PyBroadException
    try:
        el = find_element(ctx, locator, timeout)
        for _ in range(n):
            el.click()
            time.sleep(2)
            if hasattr(driver, "back"):
                driver.back()
            elif hasattr(driver, "press_keycode"):
                driver.press_keycode(4)  # KEYCODE_BACK
    except Exception:
        # 与 Java 一致：控件未找到时仅记录，不抛出
        pass
