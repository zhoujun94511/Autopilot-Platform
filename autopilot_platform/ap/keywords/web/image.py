"""WebUI 图像识别关键字（opencv 模板匹配 + JS 坐标派发）。

关键字 id 见 keyword_defs 定义（参考 manifests/ImageIdentityKeyword.json）。
做法：selenium 截当前视口图 → opencv 匹配模板图 → 换算 CSS 坐标(除以 devicePixelRatio)
→ document.elementFromPoint(x,y) 派发 click/dblclick/contextmenu，或聚焦后输入。
模板图路径 imagePath：相对工程目录或绝对路径。
"""

from __future__ import annotations

import os
import time

from ..registry import keyword, KeywordError
from ..context import ExecutionContext
from .driver import get_manager
from ..image_match import find_template
from ...runtime.paths import join_project, to_native


def _resolve_image(ctx: ExecutionContext, image_path: str) -> str:
    raw = to_native(image_path)
    if os.path.isabs(raw) and os.path.exists(raw):
        return raw
    base = ctx.get_var("__project_path__") or os.getcwd()
    cand = join_project(str(base), raw)
    return cand if os.path.exists(cand) else raw


def _locate(ctx: ExecutionContext, image_path: str, threshold: float = 0.8):
    """返回 (css_x, css_y) 视口 CSS 坐标；未命中返回 None。"""
    drv = get_manager(ctx).driver()
    png = drv.get_screenshot_as_png()
    resolved = _resolve_image(ctx, image_path)
    try:
        m = find_template(png, resolved, threshold=threshold)
    except FileNotFoundError as exc:
        raise KeywordError(str(exc)) from exc
    if m is None:
        return None
    dpr = drv.execute_script("return window.devicePixelRatio") or 1
    return m.cx / dpr, m.cy / dpr


def _wait_locate(ctx, image_path, timeout_ms, want=True):
    deadline = time.time() + (int(str(timeout_ms) or "10000") / 1000.0)
    while True:
        pos = _locate(ctx, image_path)
        if (pos is not None) == want:
            return pos
        if time.time() > deadline:
            # 超时返回最后一次定位结果，由调用方决定是否抛错
            # （旧实现 want=False 时超时恒返回 None，导致 waitVanish 永不超时失败）
            return pos
        time.sleep(0.5)


def _dispatch(ctx, pos, event: str):
    drv = get_manager(ctx).driver()
    x, y = pos
    drv.execute_script(
        "var e=document.elementFromPoint(arguments[0],arguments[1]);"
        "if(!e)return false;"
        "var t=arguments[2];"
        "if(t==='click'){e.click();}"
        "else{var ev=new MouseEvent(t,{bubbles:true,cancelable:true,view:window});e.dispatchEvent(ev);}"
        "return true;", x, y, event)


# noinspection PyPep8Naming
@keyword("img_element_click", name="图像点击", category="WebUI",
         legacy_impl="ImageIdentityKeyword:imageClick")
def image_click(ctx: ExecutionContext, imagePath: str = "", **_kw) -> None:
    pos = _locate(ctx, imagePath)
    if pos is None:
        raise KeywordError(f"屏幕未找到目标图像: {imagePath}")
    _dispatch(ctx, pos, "click")


# noinspection PyPep8Naming
@keyword("img_element_doubleClick", name="图像双击", category="WebUI",
         legacy_impl="ImageIdentityKeyword:imageDoubleClick")
def image_double_click(ctx: ExecutionContext, imagePath: str = "", **_kw) -> None:
    pos = _locate(ctx, imagePath)
    if pos is None:
        raise KeywordError(f"屏幕未找到目标图像: {imagePath}")
    _dispatch(ctx, pos, "dblclick")


# noinspection PyPep8Naming
@keyword("img_element_rightClick", name="图像右键", category="WebUI",
         legacy_impl="ImageIdentityKeyword:imageRightClick")
def image_right_click(ctx: ExecutionContext, imagePath: str = "", **_kw) -> None:
    pos = _locate(ctx, imagePath)
    if pos is None:
        raise KeywordError(f"屏幕未找到目标图像: {imagePath}")
    _dispatch(ctx, pos, "contextmenu")


# noinspection PyPep8Naming
@keyword("img_element_type", name="图像处输入", category="WebUI",
         legacy_impl="ImageIdentityKeyword:imageType")
def image_type(ctx: ExecutionContext, imagePath: str = "", text: str = "", **_kw) -> None:
    pos = _locate(ctx, imagePath)
    if pos is None:
        raise KeywordError(f"屏幕未找到目标图像: {imagePath}")
    drv = get_manager(ctx).driver()
    x, y = pos
    drv.execute_script(
        "var e=document.elementFromPoint(arguments[0],arguments[1]);"
        "if(e){e.focus();if('value' in e){e.value=arguments[2];"
        "e.dispatchEvent(new Event('input',{bubbles:true}));}}", x, y, text)


# noinspection PyPep8Naming
@keyword("img_element_exists", name="图像存在判断", category="WebUI",
         out_params=["outVar"], legacy_impl="ImageIdentityKeyword:imageExists")
def image_exists(ctx: ExecutionContext, imagePath: str = "", timeout: str = "10000",
                 expectExist: str = "true", outVar: str = "", **_kw) -> dict:
    want = str(expectExist).strip().lower() in ("true", "是", "1", "yes")
    pos = _wait_locate(ctx, imagePath, timeout, want=want)
    exist = pos is not None
    if outVar:
        return {outVar: exist}
    if exist != want:
        raise KeywordError(f"图像存在性不符: {imagePath} 期望存在={want}")
    return {}


# noinspection PyPep8Naming
@keyword("img_element_wait", name="等待图像出现", category="WebUI",
         legacy_impl="ImageIdentityKeyword:imageWait")
def image_wait(ctx: ExecutionContext, imagePath: str = "", timeout: str = "10000",
               **_kw) -> None:
    if _wait_locate(ctx, imagePath, timeout, want=True) is None:
        raise KeywordError(f"等待图像出现超时: {imagePath}")


# noinspection PyPep8Naming
@keyword("img_element_waitVanish", name="等待图像消失", category="WebUI",
         legacy_impl="ImageIdentityKeyword:imageWaitVanish")
def image_wait_vanish(ctx: ExecutionContext, imagePath: str = "", timeout: str = "10000",
                      **_kw) -> None:
    if _wait_locate(ctx, imagePath, timeout, want=False) is not None:
        raise KeywordError(f"等待图像消失超时: {imagePath}")
