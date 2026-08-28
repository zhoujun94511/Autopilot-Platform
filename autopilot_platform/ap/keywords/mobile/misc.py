"""移动端杂项关键字（VerifyMobile / AndroidMobile / MobileProduct / MobileSDKergodic）。

关键字 id / 参数名见 keyword_defs 定义(参考 reverse/docs/manifests/*.json)。

- VerifyMobileKeyword：等待/校验类，基于 Appium 元素文本/属性/可见/可用/存在。
- AndroidMobileKeyword：android 专有。可用 Appium driver 完成的实现（启动 Activity、
  获取设备版本、获取当前 Activity）；依赖 adb shell / monkey / push 的缓做。
- MobileProductKeyword：目标 App 业务，textInput/elementClick/getPrice 可通用化实现，
  backToTab 依赖按返回键直到回到指定 Activity（android 专有，可实现）。
- MobileSDKergodicKeyword：SDK 遍历依赖 adb + AppiumBootstrap + 内部组件，缓做。
"""

from __future__ import annotations

import re
import time

from ..registry import keyword, KeywordError, NotImplementedKeyword
from ..context import ExecutionContext
from .driver import (
    extract_ios_button_label, find_element, get_manager, ios_alert_locator_hint,
    ios_alert_strong_hint, ios_alert_wait_budget_ms,
    screen_locate, tap_xy, try_ios_alert_click,
)
from .picture_locator import accuracy_to_threshold, is_picture_locator
from ...mobile.adb import run_adb, adb_shell, require_adb_shell_safe_token, require_android_package


def _serial(ctx):
    # noinspection PyBroadException
    try:
        caps = get_manager(ctx).driver().capabilities
        return caps.get("udid") or caps.get("deviceName") or ""
    except Exception:
        return ""


def _resumed_package(serial: str = "") -> str:
    """通过 dumpsys activity 解析当前 resumed 包名/Activity，返回 'pkg/activity'。"""
    out = adb_shell("dumpsys activity activities", serial=serial)
    for line in out.replace("\r", "").split("\n"):
        line = line.strip()
        if line.startswith("mResumedActivity:"):
            # 形如: mResumedActivity: ActivityRecord{... pkg/.Activity t123}
            parts = line.split()
            for token in parts:
                if "/" in token:
                    return token.rstrip(",")
    return ""


# --------------------------------------------------------------------------- #
# 公共小工具
# --------------------------------------------------------------------------- #
def _to_bool(v) -> bool:
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("true", "1", "是", "yes")


def _to_int(v, default: int) -> int:
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return default


def _text_match(actual: str, expect: str, mode: str) -> bool:
    """按指定匹配模式判断 actual 是否匹配 expect。"""
    actual = "" if actual is None else str(actual)
    expect = "" if expect is None else str(expect)
    if mode == "模糊匹配":
        return expect in actual
    if mode == "正则表达式匹配":
        return re.search(expect, actual) is not None
    # 默认精确匹配
    return actual == expect


def _find_or_none(ctx, locator, timeout_ms: int):
    """在 timeout 内轮询查找元素，找不到返回 None（不抛异常）。"""
    deadline = time.time() + max(0, timeout_ms) / 1000.0

    def remaining_ms() -> int:
        return max(0, int((deadline - time.time()) * 1000))

    while True:
        # noinspection PyBroadException
        try:
            return find_element(ctx, locator, timeout=remaining_ms())
        except NotImplementedKeyword:
            raise
        except KeywordError as e:
            if "会话未创建" in str(e):
                raise
        except Exception:  # noqa: BLE001
            pass
        if time.time() >= deadline:
            return None
        time.sleep(0.5)


# =========================================================================== #
# VerifyMobileKeyword（9）
# =========================================================================== #
# noinspection PyPep8Naming
@keyword("mobile_wait_element_visible", name="[公用]等待控件可见性判断(mobile)",
         category="Mobile", legacy_impl="VerifyMobileKeyword:waitForElementVisible")
def wait_element_visible(ctx: ExecutionContext, locator=None, isVisible="true",
                         timeout="30000", **_kw) -> None:
    want = _to_bool(isVisible)
    el = _find_or_none(ctx, locator, _to_int(timeout, 30000))
    vis = bool(el is not None and el.is_displayed())
    if vis != want:
        raise KeywordError(f"等待控件可见性失败：期望可见[{want}] 实际[{vis}]")


# noinspection PyPep8Naming
@keyword("mobile_wait_element_enabled", name="[公用]等待控件可用性判断(mobile)",
         category="Mobile", legacy_impl="VerifyMobileKeyword:waitForElementEnabled")
def wait_element_enabled(ctx: ExecutionContext, locator=None, isEnabled="true",
                         timeout="30000", **_kw) -> None:
    want = _to_bool(isEnabled)
    el = _find_or_none(ctx, locator, _to_int(timeout, 30000))
    enabled = bool(el is not None and el.is_enabled())
    if enabled != want:
        raise KeywordError(f"等待控件可用性失败：期望可用[{want}] 实际[{enabled}]")


# noinspection PyPep8Naming
@keyword("mobile_browser_wait_for_exist", name="[公用]等待控件存在性判断(mobile)",
         category="Mobile", legacy_impl="VerifyMobileKeyword:waitForElementExist")
def wait_for_exist(ctx: ExecutionContext, locator=None, isExist="true",
                   timeout="30000", **_kw) -> None:
    if not str(timeout).strip().isdigit():
        raise KeywordError("您输入的等待时间格式错误(等待时间是由0-9数字组成的大于等于零的数值),请检查!")
    want = _to_bool(isExist)
    el = _find_or_none(ctx, locator, _to_int(timeout, 30000))
    exist = el is not None
    if exist != want:
        raise KeywordError(f"等待控件存在性失败：期望存在[{want}] 实际[{exist}]")


@keyword("mobile_browser_wait_for_text", name="[公用]等待控件文本匹配性判断(mobile)",
         category="Mobile", legacy_impl="VerifyMobileKeyword:waitForElementText")
def wait_for_text(ctx: ExecutionContext, locator=None, text="", mode="精确匹配",
                  matched="true", timeout="30000", **_kw) -> None:
    if not str(timeout).strip().isdigit():
        raise KeywordError("您输入的等待时间格式错误(等待时间是由0-9数字组成的大于等于零的数值),请检查!")
    want = _to_bool(matched)
    el = _find_or_none(ctx, locator, _to_int(timeout, 30000))
    if el is None:
        raise KeywordError(f"等待控件文本失败：控件不存在 {locator!r}")
    ok = _text_match(el.text, text, mode)
    if ok != want:
        raise KeywordError(
            f"等待控件文本失败：期望匹配[{want}] 实际文本[{el.text}] 期望文本[{text}] 模式[{mode}]")


# noinspection PyPep8Naming
@keyword("mobile_verify_element_existed", name="[公用]校验控件是否存在(mobile)",
         category="Mobile", legacy_impl="VerifyMobileKeyword:verifyElementExisted")
def verify_element_existed(ctx: ExecutionContext, locator=None, isExisted="true",
                           timeout="30000", accuracy="", **_kw) -> None:
    want = _to_bool(isExisted)
    if is_picture_locator(locator if isinstance(locator, str) else ""):
        # 图像识别：截屏匹配模板图判断存在性
        exist = screen_locate(
            ctx, locator, threshold=accuracy_to_threshold(accuracy)) is not None
    else:
        el = _find_or_none(ctx, locator, _to_int(timeout, 30000))
        exist = el is not None
    if exist != want:
        raise KeywordError(
            f"校验控件存在性失败：实际值是[{str(exist).lower()}],期望值是[{str(want).lower()}],不符合预期.")


# noinspection PyPep8Naming
@keyword("mobile_verify_element_visible", name="[公用]校验控件是否可见(mobile)",
         category="Mobile", legacy_impl="VerifyMobileKeyword:verifyElementVisible")
def verify_element_visible(ctx: ExecutionContext, locator=None, isVisible="true",
                           timeout="30000", **_kw) -> None:
    want = _to_bool(isVisible)
    el = _find_or_none(ctx, locator, _to_int(timeout, 30000))
    vis = bool(el is not None and el.is_displayed())
    if vis != want:
        raise KeywordError(
            f"校验控件可见性失败：实际值是[{str(vis).lower()}],期望值是[{str(want).lower()}],不符合预期.")


# noinspection PyPep8Naming
@keyword("mobile_verify_element_enabled", name="[公用]校验控件是否可用(mobile)",
         category="Mobile", legacy_impl="VerifyMobileKeyword:verifyElementEnabled")
def verify_element_enabled(ctx: ExecutionContext, locator=None, isEnabled="true",
                           timeout="30000", **_kw) -> None:
    want = _to_bool(isEnabled)
    el = _find_or_none(ctx, locator, _to_int(timeout, 30000))
    enabled = bool(el is not None and el.is_enabled())
    if enabled != want:
        raise KeywordError(
            f"校验控件可用性失败：实际值是[{str(enabled).lower()}],期望值是[{str(want).lower()}],不符合预期.")


@keyword("mobile_verify_element_text", name="[公用]校验控件文本(mobile)",
         category="Mobile", legacy_impl="VerifyMobileKeyword:verifyElementText")
def verify_element_text(ctx: ExecutionContext, locator=None, text="", matched="true",
                        mode="精确匹配", timeout="30000", **_kw) -> None:
    want = _to_bool(matched)
    el = _find_or_none(ctx, locator, _to_int(timeout, 30000))
    if el is None:
        raise KeywordError(f"校验控件文本失败：控件不存在 {locator!r}")
    ok = _text_match(el.text, text, mode)
    if ok != want:
        raise KeywordError(
            f"校验控件文本失败：实际文本[{el.text}] 期望文本[{text}] 匹配模式[{mode}] "
            f"期望匹配[{str(want).lower()}],不符合预期.")


@keyword("mobile_verify_element_attribute", name="[公用]校验控件属性值(mobile)",
         category="Mobile", legacy_impl="VerifyMobileKeyword:verifyElementAttribute")
def verify_element_attribute(ctx: ExecutionContext, locator=None, attribute="",
                             value="", matched="true", mode="精确匹配", **_kw) -> None:
    want = _to_bool(matched)
    mgr = get_manager(ctx)
    el = find_element(ctx, locator)
    from ...mobile.ios.attributes import read_element_attribute
    actual = read_element_attribute(
        el, attribute or "",
        platform=mgr.platform or "",
        driver=mgr.driver(),
    )
    ok = _text_match(actual, value, mode)
    if ok != want:
        raise KeywordError(
            f"校验控件属性失败：属性[{attribute}] 实际值[{actual}] 期望值[{value}] "
            f"匹配模式[{mode}] 期望匹配[{str(want).lower()}],不符合预期.")


# =========================================================================== #
# AndroidMobileKeyword（6）
# =========================================================================== #
# noinspection PyPep8Naming
@keyword("mobile_get_current_activity", name="获取当前Activity", category="Mobile",
         out_params=["outVar"], legacy_impl="AndroidMobileKeyword:androidGetCurrentActivity")
def get_current_activity(ctx: ExecutionContext, outVar="", **_kw) -> dict:
    drv = get_manager(ctx).driver()
    activity = getattr(drv, "current_activity", None)
    if activity is None:
        raise KeywordError("当前 driver 不支持 current_activity（非 Android 会话？）")
    return {outVar: activity}


# noinspection PyPep8Naming
@keyword("mobile_start_activity", name="启动Activity", category="Mobile",
         legacy_impl="AndroidMobileKeyword:androidStartActivity")
def start_activity(ctx: ExecutionContext, packageName="", activityName="", **_kw) -> None:
    drv = get_manager(ctx).driver()
    if not hasattr(drv, "start_activity"):
        raise KeywordError("当前 driver 不支持 start_activity（非 Android 会话？）")
    drv.start_activity(packageName, activityName)


# noinspection PyPep8Naming
@keyword("mobile_get_deviceinfo", name="获取设备参数信息", category="Mobile",
         out_params=["outVar"], legacy_impl="AndroidMobileKeyword:androidGetDeviceInfo")
def get_device_info(ctx: ExecutionContext, deviceInfo="AndroidVersion", outVar="",
                    **_kw) -> dict:
    mgr = get_manager(ctx)
    if (mgr.platform or "").strip().lower() == "ios":
        from ...mobile.ios.device_info import lookup_ios_device_info
        val = lookup_ios_device_info(mgr.driver(), deviceInfo)
        return {outVar: val}
    # Android：adb getprop / wm
    if deviceInfo == "AndroidVersion":
        # 优先用会话 caps 的版本；无会话/无版本则回退 adb getprop
        # noinspection PyBroadException
        try:
            caps = getattr(get_manager(ctx).driver(), "capabilities", {}) or {}
            ver = caps.get("platformVersion") or caps.get("version")
            if ver:
                return {outVar: str(ver)}
        except Exception:
            pass
    serial = _serial(ctx)
    # 屏幕分辨率/密度：经 wm 命令（非 getprop）
    if deviceInfo in ("resolution", "screenSize", "size"):
        out = adb_shell("wm size", serial=serial)
        m = re.search(r"(\d+x\d+)", out)
        return {outVar: m.group(1) if m else out.strip()}
    if deviceInfo in ("density", "dpi"):
        out = adb_shell("wm density", serial=serial)
        m = re.search(r"(\d+)", out)
        return {outVar: m.group(1) if m else out.strip()}
    # 设备信息项 -> 对应 getprop 属性
    prop_map = {
        "AndroidVersion": "ro.build.version.release",
        "release": "ro.build.version.release",
        "model": "ro.product.model",
        "Model": "ro.product.model",
        "brand": "ro.product.brand",
        "Brand": "ro.product.brand",
        "manufacturer": "ro.product.manufacturer",
        "sdk": "ro.build.version.sdk",
        "sdkInt": "ro.build.version.sdk",
        "serial": "ro.serialno",
        "abi": "ro.product.cpu.abi",
        "cpuabi": "ro.product.cpu.abi",
        "fingerprint": "ro.build.fingerprint",
        "board": "ro.product.board",
        "hardware": "ro.hardware",
        "device": "ro.product.device",
        "name": "ro.product.name",
        "incremental": "ro.build.version.incremental",
    }
    # 白名单命中用映射；未知项按「原始键即 getprop 属性名」兜底试取一次

    prop = require_adb_shell_safe_token(
        prop_map.get(deviceInfo, deviceInfo), what="getprop 键"
    )
    result = adb_shell(f"getprop {prop}", serial=serial).strip()
    if not result and deviceInfo not in prop_map:
        raise NotImplementedKeyword(
            f"原因:未知设备信息项[{deviceInfo}]，且按原始 getprop 键也取不到值")
    return {outVar: result}


# noinspection PyPep8Naming
@keyword("mobile_monkey", name="执行Monkey稳定性测试", category="Mobile",
         legacy_impl="AndroidMobileKeyword:androidRunMonkey")
def run_monkey(ctx: ExecutionContext, monkeySteps="20", **_kw) -> None:
    steps = _to_int(monkeySteps, 20)
    plat = str(ctx.get_var("__current_platform__") or _kw.get("type") or "").strip().lower()
    mgr = getattr(ctx, "appium", None)
    if (mgr is not None and getattr(mgr, "platform", "") == "ios") or plat.startswith("ios"):
        from ...mobile.ios.monkey import run_ios_monkey
        run_ios_monkey(ctx, steps=steps, **_kw)
        return

    serial = _serial(ctx)
    # 目标包：优先会话当前包，回退 dumpsys 解析
    # noinspection PyBroadException
    try:
        pkg = get_manager(ctx).driver().current_package or ""
    except Exception:
        pkg = ""
    if not pkg:
        focus = _resumed_package(serial)
        pkg = focus.split("/")[0] if focus else ""
    if not pkg:
        raise KeywordError("无法确定 Monkey 目标包名")
    from ...engine.interrupt import adb_shell_cancellable, RunInterrupted

    pkg = require_android_package(pkg)
    try:
        out = adb_shell_cancellable(
            f"monkey -p {pkg} {steps}", ctx, serial=serial,
        )
        ctx.log(f"Monkey 执行完成: 包[{pkg}] 次数[{steps}]\n{out}")
    except RunInterrupted:
        ctx.log(f"Monkey 已按用户请求停止: 包[{pkg}]")
        raise


# noinspection PyPep8Naming
@keyword("mobile_pull_file_to_mobile", name="push文件", category="Mobile",
         legacy_impl="AndroidMobileKeyword:androidPullFileToMobile")
def pull_file_to_mobile(ctx: ExecutionContext, path="", remotPath="", **_kw) -> None:
    # 名为 pull，实为 push：本地 path -> 设备 remotPath
    serial = _serial(ctx)
    if not str(path).strip() or not str(remotPath).strip():
        raise KeywordError("push文件失败：本地path与远端remotPath均不能为空")
    out = run_adb(["push", path, remotPath], serial=serial, timeout=120)
    ctx.log(f"push {path} -> {remotPath}\n{out}")


@keyword("mobile_toast_verify", name="android端toast消息验证", category="Mobile",
         legacy_impl="AndroidMobileKeyword:androidToastVerify")
def toast_verify(ctx: ExecutionContext, text="", wait="", **_kw) -> None:
    """校验 Android toast：在 wait 秒内轮询页面源，捕获到含 text 的 toast 即通过，否则抛错。

    UiAutomator2 会把 toast 暴露到无障碍树(android.widget.Toast)，其文本随之出现在
    page_source，故无需 adb forward + 私有 Bootstrap 接口即可校验。
    """
    target = str(text or "").strip()
    if not target:
        raise KeywordError("缺少待校验的 toast 文本(text)")
    try:
        secs = float(wait) if str(wait).strip() else 5.0
    except (TypeError, ValueError):
        secs = 5.0
    drv = get_manager(ctx).driver()
    deadline = time.monotonic() + max(secs, 0)
    while True:
        # noinspection PyBroadException
        try:
            src = drv.page_source or ""
        except Exception:
            src = ""
        if target in src:
            ctx.log(f"已捕获 toast: {target}")
            return
        if time.monotonic() >= deadline:
            break
        time.sleep(0.4)
    raise KeywordError(f"未在 {secs:.0f}s 内捕获到 toast 文本: {target!r}")


# =========================================================================== #
# MobileProductKeyword（4）
# =========================================================================== #
@keyword("textInput", name="判断并文本框输入文本(mobile/wap)", category="Mobile",
         legacy_impl="MobileProductKeyword:textInput")
def product_text_input(ctx: ExecutionContext, locator=None, text="", timeout="5000",
                       **_kw) -> None:
    """控件存在则清空并输入；不存在则跳过、不报错。"""
    el = _find_or_none(ctx, locator, _to_int(timeout, 5000))
    if el is None:
        ctx.log(f"控件不存在，不做文本框输入: {locator!r}")
        return
    el.clear()
    if text:
        el.send_keys(text)


def _remaining_ms(deadline: float) -> int:
    return max(0, int((deadline - time.time()) * 1000))


def _log_ios_alert_click(ctx: ExecutionContext, locator) -> None:
    btn = extract_ios_button_label(locator)
    if btn:
        ctx.log(f"已通过 iOS Alert API 点击: {btn!r}")
    else:
        ctx.log("已通过 iOS Alert API 点击系统弹窗按钮")


@keyword("elementClick", name="判断并控件点击(mobile/wap)", category="Mobile",
         legacy_impl="MobileProductKeyword:elementClick")
def product_element_click(ctx: ExecutionContext, locator=None, timeout="5000",
                          accuracy="", **_kw) -> None:
    """控件存在且可见才点击；不存在或不可见则跳过、不报错（步骤仍 PASS）。

    iOS 系统 Alert：predicate/link 等像弹窗按钮时优先 WDA /alert/accept，不先空转 find。
    """
    timeout_ms = _to_int(timeout, 5000)
    deadline = time.time() + max(0, timeout_ms) / 1000.0
    if is_picture_locator(locator if isinstance(locator, str) else ""):
        pos = screen_locate(ctx, locator, threshold=accuracy_to_threshold(accuracy))
        if pos is None:
            ctx.log(f"【未点击】图像未匹配: {locator!r}")
            return
        tap_xy(ctx, pos[0], pos[1])
        ctx.log(f"已图像点击坐标 ({pos[0]:.0f},{pos[1]:.0f})")
        return

    mgr = get_manager(ctx)
    is_ios = mgr.platform == "ios"
    alert_hint = is_ios and ios_alert_locator_hint(locator)

    if alert_hint:
        alert_ms = ios_alert_wait_budget_ms(locator, _remaining_ms(deadline))
        if try_ios_alert_click(
            ctx, locator, alert_ms,
            wait_for_alert=ios_alert_strong_hint(locator),
        ):
            _log_ios_alert_click(ctx, locator)
            return

    el = _find_or_none(ctx, locator, _remaining_ms(deadline))
    if el is None:
        if is_ios and alert_hint and not ios_alert_strong_hint(locator):
            if try_ios_alert_click(ctx, locator, _remaining_ms(deadline),
                                   wait_for_alert=True):
                _log_ios_alert_click(ctx, locator)
                return
        ctx.log(
            f"【未点击】控件未找到（步骤 PASS 仅表示未报错，弹窗仍在请检查定位符）: {locator!r}")
        return
    if not el.is_displayed():
        ctx.log(f"【未点击】控件存在但不可见: {locator!r}")
        return
    el.click()
    ctx.log(f"已点击控件: {locator!r}")


@keyword("backToTab", name="回到tab栏展示", category="Mobile",
         legacy_impl="MobileProductKeyword:backTabActivity")
def back_to_tab(ctx: ExecutionContext, activity=".base.host.MainActivity",
                **_kw) -> None:
    """连续按返回键直到当前 Activity 等于目标，最多 10 次。"""
    drv = get_manager(ctx).driver()
    if not hasattr(drv, "current_activity"):
        raise KeywordError("当前 driver 不支持 current_activity（非 Android 会话？）")
    counts = 0
    while drv.current_activity != activity:
        if hasattr(drv, "press_keycode"):
            drv.press_keycode(4)  # KEYCODE_BACK
        elif hasattr(drv, "back"):
            drv.back()
        else:
            raise KeywordError("当前 driver 不支持返回键操作")
        time.sleep(1)
        counts += 1
        if counts > 10:
            ctx.log(f"返回失败，当前页面是：{drv.current_activity}")
            return
    ctx.log(f"返回成功，当前页面是：{drv.current_activity}")


# noinspection PyShadowingBuiltins,PyPep8Naming
@keyword("mobileProduct_app_getPrice", name="获取price", category="Mobile",
         out_params=["varName"], legacy_impl="MobileProductKeyword:getPrice")
def get_price(_ctx: ExecutionContext, str="", varName="", **_kw) -> dict:
    """去掉首个字符（货币符号如 ¥）并 trim，写回 varName。

    注意：形参名 `str` 沿用清单 param id，刻意遮蔽内建类型，函数体内不使用 str()。
    """
    s = ("" if str is None else f"{str}").strip()
    if not s:
        raise KeywordError("获取price失败：输入为空")
    return {varName: s[1:].strip()}


# =========================================================================== #
# MobileSDKergodicKeyword（1）
# =========================================================================== #
@keyword("mobile_SDK_ergodic", name="SDK按钮遍历", category="Mobile",
         legacy_impl="MobileSDKergodicKeyword:startMobileSDKergodic")
def sdk_ergodic(ctx: ExecutionContext, depth="0", **_kw) -> None:
    """控件遍历：BFS 逐层点击可点击控件，每层后返回，最多 depth 层。

    用 Appium page_source 通用实现
    （依赖 lxml 解析 UI 层级，clickable=true 的节点逐个点击），不绑专有 SDK。
    """
    from lxml import etree as _etree
    drv = get_manager(ctx).driver()
    try:
        max_depth = max(int(float(str(depth) or "1")), 1)
    except (TypeError, ValueError):
        max_depth = 1

    visited_sigs: set[str] = set()
    clicked = 0

    def clickable_nodes():
        root = _etree.fromstring(drv.page_source.encode("utf-8"))
        nodes = []
        for el in root.iter():
            if el.get("clickable") == "true":
                bnd = el.get("bounds") or ""
                sg = (el.get("resource-id") or "") + "|" + (el.get("text") or "") + "|" + bnd
                nodes.append((sg, bnd))
        return nodes

    def tap_bounds(bnd: str) -> bool:
        # bounds 形如 [x1,y1][x2,y2]
        m = re.findall(r"\d+", bnd)
        if len(m) != 4:
            return False
        x = (int(m[0]) + int(m[2])) // 2
        y = (int(m[1]) + int(m[3])) // 2
        tap_xy(ctx, x, y)
        return True

    for _level in range(max_depth):
        for sig, bounds in clickable_nodes():
            if sig in visited_sigs or not bounds:
                continue
            visited_sigs.add(sig)
            if tap_bounds(bounds):
                clicked += 1
                time.sleep(0.5)
                # noinspection PyBroadException
                try:
                    drv.back()  # 点击后返回，继续遍历同层其余控件
                except Exception:
                    pass
                time.sleep(0.3)
    ctx.log(f"控件遍历完成：点击 {clicked} 个可点击控件（最多 {max_depth} 层）")
