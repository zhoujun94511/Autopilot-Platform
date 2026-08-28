"""浏览器级 WebUI 关键字。关键字 id 见 keyword_defs 定义（参考 align-webui-selenium.md）。"""

from __future__ import annotations

import os
import re
import time
from urllib.parse import urlparse

from ..registry import keyword, KeywordError
from ..context import ExecutionContext
from ...model.mapfile import Locator
from .driver import get_manager, find_element, locator_to_by


_SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://")


def _normalize_url(url: str) -> str:
    # 已带任意协议头(http/https/file/ftp...)则不动；只认 http/https 会误伤 file://，此处修正
    if _SCHEME.match(url):
        return url
    return "http://" + url


def _current_host(drv) -> str:
    """当前页面 host（小写）；取不到返回空串。"""
    # noinspection PyBroadException
    try:
        return (urlparse(str(drv.current_url or "")).hostname or "").lower()
    except Exception:
        return ""


# noinspection PyShadowingBuiltins
@keyword("web_browser_open", name="浏览器打开", category="WebUI",
         legacy_impl="BrowserKeyword:browserOpen")
def browser_open(ctx: ExecutionContext, url: str = "", type: str = "",
                 alias: str = "", useragent: str = "", **_kw) -> None:
    # 未显式指定 type 时，回退批跑注入的默认浏览器 __web_browser__，再回退 Chrome
    btype = (type or "").strip() or str(ctx.get_var("__web_browser__") or "").strip() or "Chrome"
    mgr = get_manager(ctx)
    drv = mgr.open(alias, btype, useragent)
    drv.get(_normalize_url(url))


@keyword("web_browser_close", name="关闭当前浏览器", category="WebUI",
         legacy_impl="BrowserKeyword:browserClose")
def browser_close(ctx: ExecutionContext, **_kw) -> None:
    get_manager(ctx).quit()


@keyword("web_browser_quit", name="退出浏览器", category="WebUI",
         legacy_impl="BrowserKeyword:browserQuit")
def browser_quit(ctx: ExecutionContext, alias: str = "", **_kw) -> None:
    get_manager(ctx).quit(alias or None)


@keyword("web_browser_back", name="浏览器后退", category="WebUI",
         legacy_impl="BrowserKeyword:browserBack")
def browser_back(ctx: ExecutionContext, **_kw) -> None:
    get_manager(ctx).driver().back()


@keyword("web_browser_forward", name="浏览器前进", category="WebUI",
         legacy_impl="BrowserKeyword:browserForward")
def browser_forward(ctx: ExecutionContext, **_kw) -> None:
    get_manager(ctx).driver().forward()


@keyword("web_browser_refresh", name="浏览器刷新", category="WebUI",
         legacy_impl="BrowserKeyword:browserRefresh")
def browser_refresh(ctx: ExecutionContext, **_kw) -> None:
    get_manager(ctx).driver().refresh()


@keyword("web_browser_maximize", name="浏览器最大化", category="WebUI",
         legacy_impl="BrowserKeyword:browserMaximize")
def browser_maximize(ctx: ExecutionContext, **_kw) -> None:
    get_manager(ctx).driver().maximize_window()


# noinspection PyPep8Naming
@keyword("web_browser_get_url", name="获取当前URL", category="WebUI",
         out_params=["outVar"], legacy_impl="BrowserKeyword:getBrowserUrl")
def browser_get_url(ctx: ExecutionContext, outVar: str = "", **_kw) -> dict:
    return {outVar: get_manager(ctx).driver().current_url}


@keyword("web_browser_getBrowserTitle", name="获取浏览器标题", category="WebUI",
         out_params=["title"], legacy_impl="BrowserKeyword:getBrowserTitle")
def browser_get_title(ctx: ExecutionContext, title: str = "", **_kw) -> dict:
    return {title: get_manager(ctx).driver().title}


def _truthy(v) -> bool:
    """布尔参数：字符串 'true'/'是' 视为真。"""
    return str(v).strip().lower() in ("true", "是", "1", "yes")


# 浏览器激活：按 alias 切换为当前浏览器（IE 的 TAB 伪装无法纯 Python 实现，已砍）
@keyword("web_browser_activate", name="浏览器激活", category="WebUI",
         legacy_impl="BrowserKeyword:browserActivate")
def browser_activate(ctx: ExecutionContext, alias: str = "", **_kw) -> None:
    get_manager(ctx).switch(alias or "")


# 浏览器地址输入：在当前浏览器导航到指定 URL
@keyword("web_browser_locate", name="浏览器地址输入", category="WebUI",
         legacy_impl="BrowserKeyword:browserLocate")
def browser_locate(ctx: ExecutionContext, url: str = "", **_kw) -> None:
    get_manager(ctx).driver().get(url)


# 浏览器关闭并切换到原始窗口：关闭当前窗口句柄，切回剩余的第一个窗口
@keyword("web_browser_close_andSwitch", name="浏览器关闭并切换到原始窗口", category="WebUI",
         legacy_impl="BrowserKeyword:browserCloseAndSwitch")
def browser_close_and_switch(ctx: ExecutionContext, **_kw) -> None:
    drv = get_manager(ctx).driver()
    drv.close()
    handles = drv.window_handles
    if handles:
        drv.switch_to.window(handles[0])


# 浏览器截屏：保存当前页面截图到文件，可选时间戳，输出路径到变量
# noinspection PyPep8Naming
@keyword("web_browser_snapshot", name="浏览器截屏", category="WebUI",
         out_params=["outVar"], legacy_impl="BrowserKeyword:browserSnapshot")
def browser_snapshot(ctx: ExecutionContext, fileName: str = "",
                     select_if_timestamp: str = "是", outVar: str = "",
                     **_kw) -> dict:
    drv = get_manager(ctx).driver()
    name = fileName or "snapshot"
    base, ext = os.path.splitext(name)
    if not ext:
        ext = ".png"
    if _truthy(select_if_timestamp):
        base = f"{base}_{time.strftime('%Y%m%d%H%M%S')}"
    path = os.path.abspath(base + ext)
    drv.save_screenshot(path)
    if outVar:
        return {outVar: path}
    return {}


# 浏览器窗口切换：按标题（模糊/精确）切换到匹配的窗口
@keyword("web_browser_switch_window", name="浏览器窗口切换", category="WebUI",
         legacy_impl="BrowserKeyword:switchWindow")
def browser_switch_window(ctx: ExecutionContext, title: str = "",
                          mode: str = "模糊匹配", **_kw) -> None:
    drv = get_manager(ctx).driver()
    if not title:
        # 无标题：切到最后一个新开的窗口
        drv.switch_to.window(drv.window_handles[-1])
        return
    exact = (mode == "精确匹配")
    current = drv.current_window_handle
    for h in drv.window_handles:
        drv.switch_to.window(h)
        t = drv.title or ""
        if (t == title) if exact else (title in t):
            return
    # 未匹配则切回原窗口
    drv.switch_to.window(current)
    raise KeywordError(f"未找到标题匹配的窗口: {title!r}")


# 浏览器页面框架切换：locator 为空则切回主文档，否则切入指定 frame
@keyword("web_browser_switch_frame", name="浏览器页面框架切换", category="WebUI",
         legacy_impl="BrowserKeyword:switchFrame")
def browser_switch_frame(ctx: ExecutionContext, locator=None, **_kw) -> None:
    mgr = get_manager(ctx)
    drv = mgr.driver()
    if not locator:
        drv.switch_to.default_content()
        return
    el = find_element(ctx, locator)
    try:
        drv.switch_to.frame(el)
    except KeywordError:
        raise
    except Exception as exc:
        raise KeywordError(f"元素不是 frame/iframe: {locator!r}") from exc


# 弹框点击操作：存在弹框时接受(true)/取消(false)
# noinspection PyPep8Naming
@keyword("web_browser_click_alert", name="弹框点击操作", category="WebUI",
         legacy_impl="BrowserKeyword:clickAlert")
def browser_click_alert(ctx: ExecutionContext, isAccept: str = "true", **_kw) -> None:
    mgr = get_manager(ctx)
    drv = mgr.driver()
    want = _truthy(isAccept)
    # Playwright：dialog 在事件回调里必须立即处理；isAccept=false 时预置下一次 dismiss
    # （须在触发弹框的点击之前调用，与 Selenium「弹后点取消」顺序不同）
    if getattr(mgr, "engine", "selenium") == "playwright":
        page = getattr(drv, "page", None)
        if page is not None:
            page.ap_dialog_dismiss = not want
            if not want:
                return
        # accept：若弹框仍挂起则同步清缓存（多数已在 dialog 回调处理）
        # noinspection PyBroadException
        try:
            alert = drv.switch_to.alert
        except Exception:
            return
        alert.accept()
        return
    # noinspection PyBroadException
    try:
        alert = drv.switch_to.alert
    except Exception:
        return
    if want:
        alert.accept()
    else:
        alert.dismiss()


# 获取弹框文本：存在弹框时把文本存入输出变量
# noinspection PyPep8Naming
@keyword("web_browser_get_alertTxt", name="获取弹框文本", category="WebUI",
         out_params=["alertTxt"], legacy_impl="BrowserKeyword:getAlertTxt")
def browser_get_alert_txt(ctx: ExecutionContext, alertTxt: str = "", **_kw) -> dict:
    drv = get_manager(ctx).driver()
    # noinspection PyBroadException
    try:
        text = drv.switch_to.alert.text
    except Exception:
        return {}
    if alertTxt:
        return {alertTxt: text}
    return {}


# 输入弹框文本：向 prompt 弹框输入文本
# noinspection PyPep8Naming
@keyword("web_browser_set_promptValue", name="输入弹框文本", category="WebUI",
         legacy_impl="BrowserKeyword:setPromptValue")
def browser_set_prompt_value(ctx: ExecutionContext, inputValue: str = "", **_kw) -> None:
    mgr = get_manager(ctx)
    drv = mgr.driver()
    # Playwright：dialog 必须在弹出回调内处理，故在触发前预置 prompt 文本
    if getattr(mgr, "engine", "selenium") == "playwright":
        page = getattr(drv, "page", None)
        if page is not None:
            page.ap_pending_prompt = str(inputValue)
        return
    # noinspection PyBroadException
    try:
        alert = drv.switch_to.alert
    except Exception:
        return
    alert.send_keys(inputValue)


# 等待弹框存在：轮询等待弹框出现(isAccept=true)/消失(false)，超时则抛错
# noinspection PyPep8Naming
@keyword("web_browser_wait_alert", name="等待弹框存在", category="WebUI",
         legacy_impl="BrowserKeyword:waitAlert")
def browser_wait_alert(ctx: ExecutionContext, isAccept: str = "true",
                       timeout: str = "30000", **_kw) -> None:
    drv = get_manager(ctx).driver()
    want = _truthy(isAccept)
    ms = int(str(timeout or "30000") or "30000")
    deadline = time.time() + (ms / 1000.0)
    while True:
        # noinspection PyBroadException
        try:
            _ = drv.switch_to.alert.text
            exist = True
        except Exception:
            exist = False
        if exist == want:
            return
        if time.time() > deadline:
            raise KeywordError(f"等待弹框超时(期望存在={want}, timeout={ms}ms)")
        time.sleep(0.2)


# 执行JS脚本：执行脚本并把返回值存入输出变量
@keyword("web_browser_execute_js", name="执行JS脚本", category="WebUI",
         out_params=["var_value"], legacy_impl="BrowserKeyword:executeJScript")
def browser_execute_js(ctx: ExecutionContext, script: str = "", arg1="",
                       arg2="", arg3="", var_value: str = "VAR_VALUE",
                       **_kw) -> dict:
    drv = get_manager(ctx).driver()
    args = [a for a in (arg1, arg2, arg3) if a != ""]
    try:
        result = drv.execute_script(script, *args)
    except KeywordError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise KeywordError(f"执行JS失败: {exc}") from exc
    if result is None or result == "":
        ctx.log("脚本返回结果为空")
        result = ""
    return {var_value: result} if var_value else {}


def _wait_until(_ctx, predicate, timeout=30.0):
    deadline = time.time() + timeout
    # 短超时用更密轮询，避免 800ms 只睡一轮就误判
    interval = 0.05 if timeout <= 1.0 else 0.2 if timeout <= 5.0 else 0.5
    while True:
        # noinspection PyBroadException
        try:
            if predicate():
                return True
        except Exception:
            pass
        if time.time() > deadline:
            return False
        time.sleep(interval)


def _timeout_sec(timeout: str | int | float | None, default_ms: int = 30000) -> float:
    raw = str(timeout if timeout is not None else default_ms).strip() or str(default_ms)
    return max(0.0, int(raw) / 1000.0)


def _element_exists(ctx: ExecutionContext, locator) -> bool:
    """存在性快检：用 find_elements，避免 PW find_element 默认长等待拖垮 wait 超时。"""
    if isinstance(locator, str):
        loc = Locator(type="XPATH", value=locator)
    else:
        loc = locator
    if not isinstance(loc, Locator):
        return False
    mgr = get_manager(ctx)
    drv = mgr.driver()
    # noinspection PyBroadException
    try:
        if getattr(mgr, "engine", "selenium") == "playwright" and loc.type == "ROLE":
            els = drv.find_elements("ROLE", (loc.value or "").strip())
        else:
            by, value = locator_to_by(loc)
            els = drv.find_elements(by, value)
        return len(els) > 0
    except Exception:
        return False


# 等待控件存在性判断：等待元素存在(true)/不存在(false)
# noinspection PyPep8Naming
@keyword("web_browser_wait_for_exist", name="等待控件存在性判断", category="WebUI",
         legacy_impl="BrowserKeyword:waitForElementExist")
def browser_wait_for_exist(ctx: ExecutionContext, locator=None,
                           isExist: str = "true", timeout: str = "30000", **_kw) -> None:
    want = _truthy(isExist)

    def check():
        return _element_exists(ctx, locator) is want
    if not _wait_until(ctx, check, timeout=_timeout_sec(timeout)):
        raise KeywordError(f"等待控件存在性判断超时(期望存在={want})")


# 等待控件可见性判断：等待元素可见(true)/不可见(false)
# noinspection PyPep8Naming
@keyword("web_browser_wait_for_visible", name="等待控件可见性判断", category="WebUI",
         legacy_impl="BrowserKeyword:waitForElementVisible")
def browser_wait_for_visible(ctx: ExecutionContext, locator=None,
                             isVisible: str = "true", timeout: str = "30000", **_kw) -> None:
    want = _truthy(isVisible)

    def check():
        # noinspection PyBroadException
        try:
            el = find_element(ctx, locator)
            return el.is_displayed() == want
        except Exception:
            return want is False
    if not _wait_until(ctx, check, timeout=_timeout_sec(timeout)):
        raise KeywordError(f"等待控件可见性判断超时(期望可见={want})")


# 等待控件文本匹配性判断：等待元素文本包含/不包含指定文本
# noinspection PyPep8Naming
@keyword("web_browser_wait_for_text", name="等待控件文本匹配性判断", category="WebUI",
         legacy_impl="BrowserKeyword:waitForElementText")
def browser_wait_for_text(ctx: ExecutionContext, locator=None, text: str = "",
                          isMatched: str = "true", timeout: str = "30000", **_kw) -> None:
    want = _truthy(isMatched)

    def check():
        el = find_element(ctx, locator)
        matched = text in (el.text or "")
        return matched == want
    if not _wait_until(ctx, check, timeout=_timeout_sec(timeout)):
        raise KeywordError(f"等待控件文本匹配超时(text={text!r}, 期望匹配={want})")


# 滚动条纵向移动：滚动到指定高度，-1 表示滚动到底部
@keyword("web_browser_scroll_vertical_bar", name="滚动条纵向移动", category="WebUI",
         legacy_impl="BrowserKeyword:scrollVerticalBar")
def browser_scroll_vertical_bar(ctx: ExecutionContext, height: str = "-1", **_kw) -> None:
    drv = get_manager(ctx).driver()
    h = int(str(height) or "-1")
    if h < 0:
        drv.execute_script("window.scrollTo(0, document.body.scrollHeight);")
    else:
        drv.execute_script("window.scrollTo(0, arguments[0]);", h)


# 获取cookie的值：按名称取 cookie 值存入输出变量
# noinspection PyPep8Naming
@keyword("web_browser_getCookieValueByName", name="获取cookie的值", category="WebUI",
         out_params=["cookieValue"], legacy_impl="BrowserKeyword:getCookieValueByName")
def browser_get_cookie_value(ctx: ExecutionContext, cookieName: str = "",
                             cookieValue: str = "var_cookieValue", **_kw) -> dict:
    drv = get_manager(ctx).driver()
    c = drv.get_cookie(cookieName)
    val = c.get("value", "") if c else ""
    return {cookieValue: val} if cookieValue else {}


# 删除所有cookies
@keyword("web_browser_deleteAllCookies", name="删除所有cookies", category="WebUI",
         legacy_impl="BrowserKeyword:deleteAllCookies")
def browser_delete_all_cookies(ctx: ExecutionContext, **_kw) -> None:
    get_manager(ctx).driver().delete_all_cookies()


# 删除某个cookie：按名称删除
# noinspection PyPep8Naming
@keyword("web_browser_deleteCookieNamed", name="删除某个cookie", category="WebUI",
         legacy_impl="BrowserKeyword:deleteCookieNamed")
def browser_delete_cookie_named(ctx: ExecutionContext, cookieName: str = "", **_kw) -> None:
    get_manager(ctx).driver().delete_cookie(cookieName)


# 增加cookie：以 key/value 添加 cookie
@keyword("web_browser_addCookie", name="增加cookie", category="WebUI",
         legacy_impl="BrowserKeyword:addCookie")
def browser_add_cookie(ctx: ExecutionContext, key: str = "", value: str = "", **_kw) -> None:
    get_manager(ctx).driver().add_cookie({"name": key, "value": value})


# 增加cookie(多配置)：带 domain/path 添加 cookie
@keyword("web_browser_addCookie_Complex", name="增加cookie(多配置)", category="WebUI",
         legacy_impl="BrowserKeyword:addCookieComplex")
def browser_add_cookie_complex(ctx: ExecutionContext, key: str = "", value: str = "",
                               domain: str = "", path: str = "/", **_kw) -> None:
    cookie = {"name": key, "value": value, "path": path}
    drv = get_manager(ctx).driver()
    if domain:
        cookie["domain"] = domain
        # 部分引擎对跨站 domain 静默接受；与当前 host 明显不符时主动失败
        host = _current_host(drv)
        d = str(domain).lstrip(".").lower()
        if host and d and host != d and not host.endswith("." + d):
            raise KeywordError(
                f"增加 cookie 失败: domain={domain!r} 与当前页面 host={host!r} 不匹配"
            )
    try:
        drv.add_cookie(cookie)
    except KeywordError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise KeywordError(f"增加 cookie 失败: {exc}") from exc


# 获取浏览器类型：把当前浏览器类型名存入输出变量
# noinspection PyShadowingBuiltins
@keyword("web_browser_getBrowserType", name="获取浏览器类型", category="WebUI",
         out_params=["type"], legacy_impl="BrowserKeyword:getBrowserType")
def browser_get_browser_type(ctx: ExecutionContext, type: str = "var_curBrowserType",
                             **_kw) -> dict:
    drv = get_manager(ctx).driver()
    # Selenium driver 的能力里有浏览器名
    # noinspection PyBroadException
    try:
        name = (drv.capabilities or {}).get("browserName", "")
    except Exception:
        name = ""
    return {type: name} if type else {}


# 获取页面源码：把当前页面 HTML 源码存入输出变量
# noinspection PyPep8Naming
@keyword("web_browser_getPageSource", name="获取页面源码", category="WebUI",
         out_params=["outValue"], legacy_impl="BrowserKeyword:getPageSource")
def browser_get_page_source(ctx: ExecutionContext, outValue: str = "var_pageSource",
                            **_kw) -> dict:
    src = get_manager(ctx).driver().page_source
    return {outValue: src} if outValue else {}
