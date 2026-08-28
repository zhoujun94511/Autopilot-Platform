"""WebDriver 生命周期管理 + locator→By 转换。

对齐：reverse/docs/align-webui-selenium.md
- BrowserManager 按 alias 管理多个 WebDriver（Browsers 注册表）。
- 驱动获取交给 Selenium Manager 自动解析（不手动管理 chromedriver.exe）。
- locator 转换：直接 By（ID/NAME/CLASS/XPATH/CSS/TEXT/WAP_ID/ROLE），AND/OR 才构造 XPath。
- E1：`web_engine=selenium|playwright`（ctx `__web_engine__` 或环境变量 AUTOPILOT_WEB_ENGINE）。
"""

from __future__ import annotations

import os
from typing import Any, Optional

# noinspection PyUnresolvedReferences
from selenium import webdriver
# noinspection PyUnresolvedReferences
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException

from ...model.mapfile import Locator
from ..context import ExecutionContext
from ..registry import KeywordError


# locator type → Selenium By
_BY_MAP = {
    "ID": By.ID,
    "WAP_ID": By.ID,
    "NAME": By.NAME,
    "CLASS": By.CLASS_NAME,
    "XPATH": By.XPATH,
    "CSS": By.CSS_SELECTOR,
    "TEXT": By.LINK_TEXT,
    # ROLE：降级为 CSS [role=…]（Playwright 可用 get_by_role；Selenium 无原生 ROLE）
    "ROLE": By.CSS_SELECTOR,
}


def resolve_web_engine(ctx: ExecutionContext | None = None) -> str:
    """selenium（默认）| playwright。

    优先级：ctx ``__web_engine__`` > 环境变量 ``AUTOPILOT_WEB_ENGINE`` > settings.web_engine。
    """
    if ctx is not None:
        v = str(ctx.get_var("__web_engine__") or "").strip().lower()
        if v in ("selenium", "playwright"):
            return v
    env = (os.environ.get("AUTOPILOT_WEB_ENGINE") or "").strip().lower()
    if env in ("selenium", "playwright"):
        return env
    try:
        from ...runtime import settings as _settings  # 延迟：settings 不可用时回落默认

        s = str(_settings.web_engine() or "").strip().lower()
        if s in ("selenium", "playwright"):
            return s
    except (ImportError, AttributeError, TypeError, ValueError, OSError, RuntimeError):
        # settings 不可用或返回异常时回落默认
        pass
    return "selenium"


def require_selenium_feature(ctx: ExecutionContext, feature: str) -> None:
    """Playwright 未映射的 Selenium 高级能力显式失败。"""
    if getattr(get_manager(ctx), "engine", "selenium") == "playwright":
        raise KeywordError(
            f"web_engine=playwright 暂不支持 {feature}；"
            f"请改用 AUTOPILOT_WEB_ENGINE=selenium 或拆分步骤"
        )


def _composite_xpath(loc: Locator) -> str:
    """AND/OR 复合定位 → XPath。AND=全部属性与，OR=任一属性或。"""
    tag = loc.tag or "*"
    conds = [f"@{p.get('name')}='{p.get('value')}'" for p in loc.properties if p.get("name")]
    if not conds:
        return f"//{tag}"
    joiner = " and " if loc.type == "AND" else " or "
    return f"//{tag}[{joiner.join(conds)}]"


def _role_to_css(value: str) -> str:
    role = (value or "").strip()
    if not role:
        raise KeywordError("ROLE 定位缺少 role 值")
    # 已是 CSS 选择器时原样使用
    if role.startswith("[") or role.startswith(".") or role.startswith("#"):
        return role
    escaped = role.replace("\\", "\\\\").replace('"', '\\"')
    return f'[role="{escaped}"]'


def locator_to_by(loc: Locator) -> tuple[str, str]:
    """把 Locator 转成 (By, value)。"""
    if loc.type in ("AND", "OR"):
        return By.XPATH, _composite_xpath(loc)
    if loc.type == "ROLE":
        return By.CSS_SELECTOR, _role_to_css(loc.value or "")
    by = _BY_MAP.get(loc.type, By.XPATH)
    return by, loc.value


class BrowserManager:
    """按 alias 管理 WebDriver。alias 空串表示默认浏览器。"""

    def __init__(self) -> None:
        self._drivers: dict[str, Any] = {}
        self._current_alias: Optional[str] = None
        self.engine: str = "selenium"
        # 测试可注入：driver_factory(browser_type, useragent) -> driver
        self.driver_factory = default_driver_factory

    def open(self, alias: str, browser_type: str, useragent: str = "") -> Any:
        alias = alias or ""
        drv = self.driver_factory(browser_type, useragent)
        self._drivers[alias] = drv
        self._current_alias = alias
        return drv

    def driver(self, alias: Optional[str] = None) -> Any:
        key = (alias if alias is not None else self._current_alias) or ""
        drv = self._drivers.get(key)
        if drv is None:
            raise KeywordError(f"浏览器未启动（alias={key!r}），请先执行“浏览器打开”")
        return drv

    def switch(self, alias: str) -> None:
        if alias not in self._drivers:
            raise KeywordError(f"无此别名的浏览器: {alias!r}")
        self._current_alias = alias

    def quit(self, alias: Optional[str] = None) -> None:
        key = (alias if alias is not None else self._current_alias) or ""
        drv = self._drivers.pop(key, None)
        if drv is not None:
            quit_fn = getattr(drv, "quit", None)
            if callable(quit_fn):
                try:
                    quit_fn()
                except (OSError, RuntimeError, AttributeError, TypeError):
                    pass
        if self._current_alias == key:
            self._current_alias = next(iter(self._drivers), None)

    def quit_all(self) -> None:
        for drv in list(self._drivers.values()):
            quit_fn = getattr(drv, "quit", None)
            if callable(quit_fn):
                try:
                    quit_fn()
                except (OSError, RuntimeError, AttributeError, TypeError):
                    pass
        self._drivers.clear()
        self._current_alias = None


def default_driver_factory(browser_type: str, useragent: str = ""):
    """按浏览器类型创建真实 WebDriver（Selenium Manager 自动解析驱动）。"""
    t = (browser_type or "chrome").strip().lower()
    if t in ("chrome", "headless"):
        opts = webdriver.ChromeOptions()
        if t == "headless":
            opts.add_argument("--headless=new")
        if useragent:
            opts.add_argument(f"--user-agent={useragent}")
        return webdriver.Chrome(options=opts)
    if t == "firefox":
        opts = webdriver.FirefoxOptions()
        return webdriver.Firefox(options=opts)
    if t == "edge":
        opts = webdriver.EdgeOptions()
        return webdriver.Edge(options=opts)
    raise KeywordError(f"暂不支持的浏览器类型: {browser_type}（已砍 IE/Opera/Safari 的原生伪装）")


def _pw_error_types() -> tuple[type[BaseException], ...]:
    errs: list[type[BaseException]] = [
        OSError, RuntimeError, AttributeError, TypeError, ValueError,
    ]
    try:
        # noinspection PyPackageRequirements
        import playwright.sync_api as pw_api  # type: ignore[import-untyped]  # 延迟：可选 Playwright extra

        errs.extend([pw_api.Error, pw_api.TimeoutError])
    except ImportError:
        pass
    return tuple(errs)


_PW_ERRS = _pw_error_types()


class _PwElement:
    """Playwright ElementHandle 的 Selenium WebElement 表面。"""

    def __init__(self, handle: Any, page: Any, locator: Any = None) -> None:
        self.handle = handle
        self.page = page
        # ElementHandle 无 drag_to；保留 Locator 供 HTML5 拖拽等
        self.locator = locator

    def click(self) -> None:
        self.handle.click()

    def context_click(self) -> None:
        self.handle.click(button="right")

    def double_click(self) -> None:
        self.handle.dblclick()

    def hover(self) -> None:
        self.handle.hover()

    def drag_to(self, target: "_PwElement") -> None:
        src_loc = self.locator
        dst_loc = getattr(target, "locator", None)
        if src_loc is not None and dst_loc is not None:
            # Locator.drag_to 支持 HTML5 DnD；ElementHandle 无此 API
            src_loc.drag_to(dst_loc)
            return
        handle_drag = getattr(self.handle, "drag_to", None)
        if callable(handle_drag):
            handle_drag(target.handle)
            return
        # 无 Locator 时退回鼠标坐标拖（适合滑块；HTML5 DnD 可能不触发）
        src = self.handle.bounding_box()
        dst = target.handle.bounding_box()
        if not src or not dst:
            raise KeywordError("Playwright：无法获取拖拽元素 bounding_box")
        sx = float(src["x"]) + float(src["width"]) / 2.0
        sy = float(src["y"]) + float(src["height"]) / 2.0
        dx = float(dst["x"]) + float(dst["width"]) / 2.0
        dy = float(dst["y"]) + float(dst["height"]) / 2.0
        mouse = self.page.mouse
        mouse.move(sx, sy)
        mouse.down()
        mouse.move(dx, dy, steps=12)
        mouse.up()

    def select_option(
        self,
        *,
        index: int | list[int] | None = None,
        value: str | list[str] | None = None,
        label: str | list[str] | None = None,
    ) -> None:
        """单选传标量、多选传列表（<select multiple>）。"""
        kw: dict[str, Any] = {}
        if index is not None:
            kw["index"] = index
        elif value is not None:
            kw["value"] = value
        else:
            kw["label"] = label if label is not None else ""
        self.handle.select_option(**kw)

    def selected_option_texts(self) -> list[str]:
        try:
            texts = self.handle.evaluate(
                "el => Array.from(el.selectedOptions || []).map("
                "o => (o.textContent || o.label || '').trim())"
            )
            if isinstance(texts, list):
                return [str(t) for t in texts]
        except _PW_ERRS:
            pass
        return []

    def clear(self) -> None:
        try:
            self.handle.fill("")
        except _PW_ERRS:
            self.handle.evaluate("el => { el.value = ''; }")

    def send_keys(self, text: str) -> None:
        path = str(text)
        try:
            input_type = (self.handle.get_attribute("type") or "").lower()
        except _PW_ERRS:
            input_type = ""
        if input_type == "file":
            self.handle.set_input_files(path)
            return
        # fill 比逐键 type 更可靠（文本框）；失败再回退 type
        try:
            self.handle.fill(path)
        except _PW_ERRS:
            self.handle.type(path)

    @property
    def text(self) -> str:
        try:
            t = self.handle.inner_text()
            if t is not None:
                return str(t)
        except _PW_ERRS:
            pass
        try:
            return str(self.handle.text_content() or "")
        except _PW_ERRS:
            return ""

    def get_attribute(self, name: str) -> str:
        # Selenium 对 input.value 读的是当前属性值；Playwright get_attribute 只读 HTML 属性
        if (name or "").lower() == "value":
            try:
                return str(self.handle.input_value())
            except _PW_ERRS:
                try:
                    v = self.handle.evaluate("el => el.value")
                    return "" if v is None else str(v)
                except _PW_ERRS:
                    pass
        try:
            v = self.handle.get_attribute(name)
            return "" if v is None else str(v)
        except _PW_ERRS:
            return ""

    def is_displayed(self) -> bool:
        try:
            return bool(self.handle.is_visible())
        except _PW_ERRS:
            return False

    def is_enabled(self) -> bool:
        try:
            return bool(self.handle.is_enabled())
        except _PW_ERRS:
            return False

    def is_selected(self) -> bool:
        try:
            return bool(self.handle.is_checked())
        except _PW_ERRS:
            return False

    def find_element(self, by: str, value: str) -> "_PwElement":
        """相对当前元素查找（表格单元格等）。"""
        if by == By.XPATH or by == "xpath":
            loc = self.handle.query_selector(f"xpath={value}")
            if loc is None:
                raise KeywordError(f"Playwright 相对定位未找到: xpath={value!r}")
            # query_selector 返回 ElementHandle；无 Locator 时拖拽走鼠标回退
            return _PwElement(loc, self.page, locator=None)
        if by == By.CSS_SELECTOR or by == "css selector":
            loc = self.handle.query_selector(value)
            if loc is None:
                raise KeywordError(f"Playwright 相对定位未找到: css={value!r}")
            return _PwElement(loc, self.page, locator=None)
        raise KeywordError(f"Playwright 元素内查找暂不支持 by={by!r}")

    def find_elements(self, by: str, value: str) -> list["_PwElement"]:
        if by == By.XPATH or by == "xpath":
            handles = self.handle.query_selector_all(f"xpath={value}")
        elif by == By.CSS_SELECTOR or by == "css selector":
            handles = self.handle.query_selector_all(value)
        else:
            raise KeywordError(f"Playwright 元素内查找暂不支持 by={by!r}")
        return [_PwElement(h, self.page, locator=None) for h in handles]


class _PwAlert:
    """Playwright dialog 适配。

    Playwright 要求在 dialog 事件里立即 accept/dismiss，否则触发动作会挂起；
    因此打开时即处理并缓存文案，供 get/verify alert 读取。
    """

    def __init__(self, page: Any) -> None:
        self.page = page

    @property
    def text(self) -> str:
        msg = getattr(self.page, "ap_last_dialog_message", None)
        if msg is None:
            raise KeywordError("Playwright：当前无活动 alert/dialog")
        return str(msg)

    def accept(self) -> None:
        # 多数情况 dialog 已在事件回调里 accept；此处清缓存
        self.page.ap_last_dialog_message = None
        self.page.ap_last_dialog = None

    def dismiss(self) -> None:
        self.page.ap_last_dialog_message = None
        self.page.ap_last_dialog = None

    def send_keys(self, keys: str) -> None:
        # prompt：若尚未处理则带文本 accept；否则仅记录（打开时已自动 accept）
        dialog = getattr(self.page, "ap_last_dialog", None)
        if dialog is not None:
            try:
                dialog.accept(prompt_text=str(keys))
            except _PW_ERRS:
                pass
            self.page.ap_last_dialog = None
        self.page.ap_last_dialog_prompt = str(keys)


class _PwSwitchTo:
    def __init__(self, adapter: "_PlaywrightDriverAdapter") -> None:
        self.adapter = adapter

    @property
    def alert(self) -> _PwAlert:
        return _PwAlert(self.adapter.page)

    def default_content(self) -> None:
        # Playwright 无 frame 栈；回到主 page
        self.adapter.frame = None

    def frame(self, reference: Any) -> None:
        if isinstance(reference, _PwElement):
            fr = reference.handle.content_frame()
            if fr is None:
                raise KeywordError("Playwright：元素不是 frame")
            self.adapter.frame = fr
            return
        raise KeywordError("Playwright：switch_to.frame 仅支持已定位的 frame 元素")

    def window(self, handle: str) -> None:
        pages = list(self.adapter.context.pages)
        for p in pages:
            if id(p) == int(handle) if str(handle).isdigit() else False:
                self.adapter.page = p
                return
            if str(id(p)) == str(handle) or getattr(p, "ap_handle", "") == str(handle):
                self.adapter.page = p
                return
        # handle 也可能是 URL
        for p in pages:
            if str(p.url) == str(handle):
                self.adapter.page = p
                return
        if pages:
            # 按索引
            try:
                idx = int(handle)
                self.adapter.page = pages[idx]
                return
            except (TypeError, ValueError, IndexError):
                pass
        raise KeywordError(f"Playwright：未找到窗口 handle={handle!r}")


class _PlaywrightDriverAdapter:
    """Selenium 关键字表面兼容的 Playwright 适配（E1 深化）。"""

    def __init__(self, pw: Any, browser: Any, context: Any, page: Any) -> None:
        self.pw = pw
        self.browser = browser
        self.context = context
        self.page = page
        self.frame: Any = None
        self.switch_to = _PwSwitchTo(self)
        self.capabilities = {"browserName": "playwright"}

        def _on_dialog(dialog: Any) -> None:
            # 必须在回调内处理，否则触发 click 的关键字会超时挂起
            page.ap_last_dialog_message = dialog.message
            page.ap_last_dialog_type = getattr(dialog, "type", "") or ""
            page.ap_last_dialog = dialog
            pending = getattr(page, "ap_pending_prompt", None)
            try:
                dtype = str(getattr(dialog, "type", "") or "")
                if dtype == "prompt":
                    dialog.accept(
                        prompt_text="" if pending is None else str(pending)
                    )
                    page.ap_pending_prompt = None
                elif getattr(page, "ap_dialog_dismiss", False):
                    dialog.dismiss()
                    page.ap_dialog_dismiss = False
                else:
                    dialog.accept()
            except _PW_ERRS:
                try:
                    dialog.dismiss()
                except _PW_ERRS:
                    pass

        page.on("dialog", _on_dialog)

    def _target(self) -> Any:
        return self.frame if self.frame is not None else self.page

    def get(self, url: str) -> None:
        self.page.goto(url)

    def back(self) -> None:
        self.page.go_back()

    def forward(self) -> None:
        self.page.go_forward()

    def refresh(self) -> None:
        self.page.reload()

    def maximize_window(self) -> None:
        self.page.set_viewport_size({"width": 1920, "height": 1080})

    @property
    def current_url(self) -> str:
        return str(self.page.url or "")

    @property
    def title(self) -> str:
        return str(self.page.title() or "")

    @property
    def page_source(self) -> str:
        return str(self.page.content() or "")

    @property
    def current_window_handle(self) -> str:
        return str(id(self.page))

    @property
    def window_handles(self) -> list[str]:
        return [str(id(p)) for p in self.context.pages]

    def get_screenshot_as_png(self) -> bytes:
        return bytes(self.page.screenshot(type="png") or b"")

    def save_screenshot(self, filename: str) -> bool:
        self.page.screenshot(path=filename, type="png")
        return True

    def get_cookie(self, name: str) -> dict[str, Any] | None:
        for c in self.context.cookies():
            if c.get("name") == name:
                return dict(c)
        return None

    def get_cookies(self) -> list[dict[str, Any]]:
        return [dict(c) for c in self.context.cookies()]

    def add_cookie(self, cookie_dict: dict[str, Any]) -> None:
        c = dict(cookie_dict or {})
        if "name" not in c and "key" in c:
            c["name"] = c.pop("key")
        # Playwright：url 与 domain 二选一；有 domain 时不要再塞 url
        if not c.get("domain") and "url" not in c and self.current_url:
            c["url"] = self.current_url
        self.context.add_cookies([c])

    def delete_cookie(self, name: str) -> None:
        remain = [c for c in self.context.cookies() if c.get("name") != name]
        self.context.clear_cookies()
        if remain:
            self.context.add_cookies(remain)

    def delete_all_cookies(self) -> None:
        self.context.clear_cookies()

    def execute_script(self, script: str, *args: Any) -> Any:
        """兼容 Selenium ``arguments[n]`` 风格；首参为元素时在该元素上 evaluate。"""
        target = self._target()
        body = (script or "").strip()
        if args and isinstance(args[0], _PwElement):
            extra = list(args[1:])
            # 构造与 Selenium 一致的 arguments 数组（含元素本身）
            wrapped = (
                "(el, extra) => { const arguments = [el, ...(extra || [])]; "
                + body
                + " }"
            )
            return args[0].handle.evaluate(wrapped, extra)
        if args:
            # 标量参数：scrollTo / elementFromPoint 等
            wrapped = "(extra) => { const arguments = extra || []; " + body + " }"
            return target.evaluate(wrapped, list(args))
        if "arguments[" in body:
            body = body.replace("arguments[0]", "null")
        return target.evaluate(f"() => {{ {body} }}")

    def close(self) -> None:
        """关闭当前 page（多窗口场景）。"""
        try:
            self.page.close()
        except _PW_ERRS:
            pass
        pages = list(self.context.pages)
        if pages:
            self.page = pages[-1]
            self.frame = None

    def _locator_for(self, by: str, value: str) -> Any:
        target = self._target()
        if by == "ROLE" or (isinstance(by, str) and by.upper() == "ROLE"):
            return target.get_by_role(value)
        if by == By.ID or by == "id":
            return target.locator(f"#{value}")
        if by == By.NAME or by == "name":
            return target.locator(f'[name="{value}"]')
        if by == By.CLASS_NAME or by == "class name":
            return target.locator(f".{value}")
        if by == By.LINK_TEXT or by == "link text":
            return target.get_by_text(value, exact=True)
        if by == By.XPATH or by == "xpath":
            return target.locator(f"xpath={value}")
        if by == By.CSS_SELECTOR or by == "css selector":
            return target.locator(value)
        return target.locator(value)

    def find_element(self, by: str, value: str) -> _PwElement:
        loc = self._locator_for(by, value)
        # ROLE/文本等可能命中多项；与 Selenium find_element 取首个一致
        first = loc.first
        try:
            handle = first.element_handle(timeout=5000)
        except _PW_ERRS as exc:
            raise KeywordError(
                f"Playwright 未找到元素: by={by!r} value={value!r}"
            ) from exc
        if handle is None:
            raise KeywordError(f"Playwright 未找到元素: by={by!r} value={value!r}")
        return _PwElement(handle, self.page, locator=first)

    def find_elements(self, by: str, value: str) -> list[_PwElement]:
        loc = self._locator_for(by, value)
        try:
            # Playwright Locator.element_handles() 无 timeout 参数
            handles = loc.element_handles()
        except _PW_ERRS as exc:
            raise KeywordError(
                f"Playwright 查找元素列表失败: by={by!r} value={value!r}"
            ) from exc
        return [
            _PwElement(h, self.page, locator=loc.nth(i))
            for i, h in enumerate(handles)
        ]

    def quit(self) -> None:
        try:
            self.context.close()
        except _PW_ERRS:
            pass
        try:
            self.browser.close()
        except _PW_ERRS:
            pass
        if getattr(self, "_pw_shared", False):
            _pw_runtime_release(self.pw)
        else:
            runtime = self.pw
            stop = getattr(runtime, "stop", None) if runtime is not None else None
            if callable(stop):
                try:
                    stop()
                except _PW_ERRS:
                    pass
        self.pw = None


# 同线程内复用 sync_playwright，避免多 alias 二次 start 触发 asyncio 冲突
_PW_RUNTIME: Any | None = None
_PW_RUNTIME_REFS = 0


def _pw_runtime_acquire() -> Any:
    global _PW_RUNTIME, _PW_RUNTIME_REFS
    if _PW_RUNTIME is None:
        try:
            # noinspection PyPackageRequirements
            from playwright.sync_api import sync_playwright  # type: ignore[import-untyped]  # 延迟：可选 Playwright extra
        except ImportError as exc:
            raise KeywordError(
                "web_engine=playwright 需要安装 playwright："
                "pip install 'autopilot[web_playwright]' && playwright install chromium"
            ) from exc
        _PW_RUNTIME = sync_playwright().start()
    _PW_RUNTIME_REFS += 1
    return _PW_RUNTIME


def _pw_stop(runtime: Any | None) -> None:
    stop = getattr(runtime, "stop", None) if runtime is not None else None
    if callable(stop):
        try:
            stop()
        except _PW_ERRS:
            pass


def _pw_runtime_release(pw: Any | None) -> None:
    global _PW_RUNTIME, _PW_RUNTIME_REFS
    if pw is None:
        return
    if pw is not _PW_RUNTIME:
        _pw_stop(pw)
        return
    _PW_RUNTIME_REFS = max(0, _PW_RUNTIME_REFS - 1)
    if _PW_RUNTIME_REFS == 0:
        runtime = _PW_RUNTIME
        _pw_stop(runtime)
        _PW_RUNTIME = None


def playwright_driver_factory(browser_type: str, useragent: str = ""):
    """E1：Playwright sync API；未安装时给出明确错误。

    可选依赖：``pip install 'autopilot[web_playwright]'`` 或 ``playwright``。
    """
    t = (browser_type or "chrome").strip().lower()
    headless = t in ("headless", "chromium-headless")
    channel = None
    browser_name = "chromium"
    if t in ("firefox",):
        browser_name = "firefox"
    elif t in ("edge", "msedge"):
        browser_name = "chromium"
        channel = "msedge"
    elif t in ("chrome", "chromium", "headless", ""):
        browser_name = "chromium"
        if t == "chrome":
            channel = "chrome"

    pw = _pw_runtime_acquire()
    launch_kw: dict[str, Any] = {"headless": headless or t == "headless"}
    if channel:
        launch_kw["channel"] = channel
    try:
        browser = getattr(pw, browser_name).launch(**launch_kw)
    except _PW_ERRS:
        # channel 不可用时回退无 channel
        launch_kw.pop("channel", None)
        browser = getattr(pw, browser_name).launch(**launch_kw)
    ctx_kw: dict[str, Any] = {}
    if useragent:
        ctx_kw["user_agent"] = useragent
    context = browser.new_context(**ctx_kw)
    page = context.new_page()
    adapter = _PlaywrightDriverAdapter(pw, browser, context, page)
    adapter._pw_shared = True  # type: ignore[attr-defined]
    return adapter


def make_driver_factory(engine: str):
    eng = (engine or "selenium").strip().lower()
    if eng == "playwright":
        return playwright_driver_factory
    return default_driver_factory


# ---- ExecutionContext 上的浏览器管理器（懒挂载）----

def get_manager(ctx: ExecutionContext) -> BrowserManager:
    mgr = getattr(ctx, "web", None)
    if mgr is None:
        mgr = BrowserManager()
        eng = resolve_web_engine(ctx)
        mgr.engine = eng
        mgr.driver_factory = make_driver_factory(eng)
        ctx.web = mgr  # type: ignore[attr-defined]
    return mgr


_SCROLL_BLOCK = {"顶部": "start", "底部": "end", "居中": "center", "": "center"}


def find_element(ctx: ExecutionContext, locator, scroll: bool = False, scroll_align: str = ""):
    """根据 locator（Locator 或定位串）在当前浏览器查找元素。

    scroll=True 时滚动使元素可见；scroll_align(scrollMode) 决定对齐：顶部/底部/居中(默认)。
    """
    if isinstance(locator, str):
        # 兜底：未被 context 解析成 Locator 的串，当作 XPath
        loc = Locator(type="XPATH", value=locator)
    else:
        loc = locator
    if not isinstance(loc, Locator):
        raise KeywordError(f"无效的元素定位: {locator!r}")
    mgr = get_manager(ctx)
    drv = mgr.driver()
    try:
        if getattr(mgr, "engine", "selenium") == "playwright" and loc.type == "ROLE":
            el = drv.find_element("ROLE", (loc.value or "").strip())
        else:
            by, value = locator_to_by(loc)
            try:
                el = drv.find_element(by, value)
            except Exception as exc:
                if getattr(mgr, "engine", "selenium") != "playwright":
                    if isinstance(exc, NoSuchElementException):
                        raise KeywordError(
                            f"未找到元素: by={by!r} value={value!r}"
                        ) from exc
                raise
    except KeywordError:
        raise
    if scroll:
        block = _SCROLL_BLOCK.get((scroll_align or "").strip(), "center")
        try:
            if isinstance(el, _PwElement):
                el.handle.evaluate(
                    f"(el) => el.scrollIntoView({{block: '{block}'}})"
                )
            else:
                drv.execute_script(
                    f"arguments[0].scrollIntoView({{block:'{block}'}});", el
                )
        except _PW_ERRS:
            pass
    return el
