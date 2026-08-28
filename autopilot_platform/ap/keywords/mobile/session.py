"""移动端会话关键字。关键字 id 见 keyword_defs 定义（参考 align-mobile-appium.md）。

架构分层（Windows / macOS / Linux 三端一致）：
  - **设备层**：装/卸/检测已安装 —— 不经过 Appium driver。
      Android → adb install/uninstall（见 run_adb）；
      iOS → pymobiledevice3 InstallationProxy，失败回退 go-ios（见 ios_install_app）。
    用于「安装并启动」「卸载移动应用」及设备面板装 IPA；可在无自动化会话时执行。
  - **会话层**：元素点击、滑动、截屏等 —— 经 AppiumManager.driver()。
      Android 全平台 Appium UiAutomator2；
      iOS@Mac 可选 Appium XCUITest，iOS@Win/Linux 直连 WDA（见 platform.select_backend）。
    装/卸刻意不走 driver.install_app：Win/Linux iOS 无完整 Appium 会话，且须先装包再 create()。
"""

from __future__ import annotations

import asyncio
import base64
import os
import re
import shutil
import time
from pathlib import Path

from ..registry import keyword, KeywordError
from ..context import ExecutionContext
from .driver import get_manager, find_element
from ...mobile.adb import run_adb, adb_shell, require_android_package
from autopilot_platform.appparse.errors import PackageError
from ...mobile.xapk import ANDROID_PACKAGE_SUFFIXES, install_android_package
from ...runtime.paths import resolve_project_file
from .platform import ios_session_uses_wda
from ...mobile.ios import (
    driver_backend as ios_driver_backend,
    current_bundle_id as ios_current_bundle_id,
    get_current_url as ios_get_current_url,
    is_app_installed as ios_is_app_installed,
    launch_app as ios_launch_app,
    press_physical_key as ios_press_physical_key,
    reset_app as ios_reset_app,
    scroll_to_element as ios_scroll_to_element,
    switch_context as ios_switch_context,
)
from pymobiledevice3.exceptions import PyMobileDevice3Exception

_SCREEN_REC_FLAG = "__mobile_screen_recording__"
_SCREEN_REC_PATH = "__mobile_screen_record_path__"


def _should_skip_appium_server(ctx: ExecutionContext) -> bool:
    """iOS WDA-direct 模式不需要本机 Appium server（Win/Linux auto，或显式 wda）。"""
    mgr = get_manager(ctx)
    platform = _platform_key(ctx.get_var("__current_platform__")) or _platform_key(mgr.platform)
    if not platform:
        return False
    mode = str(ctx.get_var("__mobile_backend_mode__") or mgr.backend_mode or "")
    return ios_session_uses_wda(platform, mode=mode)


@keyword("appium_start", name="启动appium服务", category="Mobile",
         legacy_impl="MobileCommKeyword:startAppium")
def appium_start(ctx: ExecutionContext, **_kw) -> None:
    mgr = get_manager(ctx)
    server = ctx.get_var("__appium_server__")
    if server:
        mgr.server = str(server)
    caps = ctx.get_var("__appium_caps__")
    if isinstance(caps, dict):
        mgr.extra_caps.update(caps)
    if _should_skip_appium_server(ctx):
        ctx.log("iOS WDA-direct 模式，跳过 Appium 服务启动")
        return
    mgr.start_server()
    ctx.log(f"Appium 服务已就绪（{mgr.server}）")


@keyword("appium_stop", name="停止appium服务", category="Mobile",
         legacy_impl="MobileCommKeyword:stopAppium")
def appium_stop(ctx: ExecutionContext, **_kw) -> None:
    """只停止本设备绑定的 Appium 端口，不影响其它设备。"""
    get_manager(ctx).stop_server()


# noinspection PyShadowingBuiltins,PyPep8Naming
@keyword("mobile_app_start", name="启动App", category="Mobile",
         legacy_impl="MobileCommKeyword:startApp")
def app_start(ctx: ExecutionContext, type: str = "Android",
              packageName: str = "", activityName: str = "", udid: str = "",
              **_kw) -> None:
    # 目标设备：优先 udid 参数，其次 ctx 变量 __device_udid__（多设备/真机用）
    _apply_ios_backend_mode(ctx, type, **_kw)
    device = _device_for_platform(ctx, type, udid)
    get_manager(ctx).create(type, packageName, activityName, device)
    from ...engine.app_watch import remember_target_package

    remember_target_package(ctx, packageName)
    if _platform_key(type) == "ios":
        from ...mobile.ios.alert import ios_alert_after_session
        ios_alert_after_session(ctx, "after_app_start")


@keyword("mobile_app_close", name="关闭App", category="Mobile",
         legacy_impl="MobileCommKeyword:closeApp")
def app_close(ctx: ExecutionContext, **_kw) -> None:
    get_manager(ctx).close()


def _serial(ctx: ExecutionContext):
    # noinspection PyBroadException
    try:
        caps = get_manager(ctx).driver().capabilities
        return caps.get("udid") or caps.get("deviceName") or ""
    except Exception:
        return ""


def _platform_key(value: str = "") -> str:
    s = str(value or "").strip().lower()
    if s.startswith("ios"):
        return "ios"
    if s.startswith("android"):
        return "android"
    return ""


def _device_for_platform(ctx: ExecutionContext, platform: str = "",
                         explicit: str = "") -> str:
    """Pick the UDID for a mobile platform from explicit arg or run context."""
    if str(explicit or "").strip():
        return str(explicit).strip()
    key = _platform_key(platform) or _platform_key(ctx.get_var("__current_platform__"))
    by_platform = ctx.get_var("__device_udid_by_platform__")
    if key and isinstance(by_platform, dict):
        val = by_platform.get(key)
        if val:
            return str(val)
    return str(ctx.get_var("__device_udid__") or "")


def _apply_ios_backend_mode(ctx: ExecutionContext, platform: str = "", **kwargs) -> str:
    """Apply an optional iOS backend override onto the execution context."""
    if _platform_key(platform) != "ios":
        return ""
    mode = str(kwargs.get("backendMode") or kwargs.get("backend") or "").strip().lower()
    if mode in ("auto", "appium", "wda"):
        ctx.set_var("__mobile_backend_mode__", mode)
        return mode
    return str(ctx.get_var("__mobile_backend_mode__") or "")


def _app_installed(pkg: str, serial: str = "") -> bool:
    """目标包是否已安装（pm list packages 精确匹配某一行 package:<pkg>）。"""
    if not pkg:
        return False
    # noinspection PyBroadException
    try:
        out = run_adb(["shell", "pm", "list", "packages", pkg], serial=serial)
    except Exception:
        return False
    return any(ln.strip() == f"package:{pkg}" for ln in out.splitlines())


def _resumed_package_activity(serial: str = "") -> str:
    """通过 dumpsys 解析当前 resumed 'pkg/activity'。"""
    # noinspection PyBroadException
    try:
        out = adb_shell("dumpsys activity activities", serial=serial)
    except Exception:
        out = ""
    for line in out.replace("\r", "").split("\n"):
        s = line.strip()
        if s.startswith("mResumedActivity:"):
            for token in s.split():
                if "/" in token:
                    return token.rstrip(",")
    # 回退 dumpsys window mCurrentFocus
    # noinspection PyBroadException
    try:
        out2 = adb_shell("dumpsys window", serial=serial)
    except Exception:
        out2 = ""
    for line in out2.replace("\r", "").split("\n"):
        s = line.strip()
        if "mCurrentFocus" in s:
            for token in s.split():
                if "/" in token:
                    return token.rstrip("}").rstrip(",")
    return ""


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _drv(ctx: ExecutionContext):
    return get_manager(ctx).driver()


def _to_int(v, default: int = 0) -> int:
    try:
        return int(float(str(v).strip()))
    except (TypeError, ValueError):
        return default


def _to_float(v, default: float = 0.0) -> float:
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return default


def _truthy(v) -> bool:
    return str(v).strip() in ("是", "true", "True", "1", "yes", "YES")


_IOS_WEBVIEW_BROWSER_HINT = (
    " iOS 请在被测 App 内用 native_web_swith_context 切 WebView，"
    "勿使用 Android 独立浏览器会话（browserName）。"
)


def _reject_ios_android_only(ctx: ExecutionContext, keyword_id: str, hint: str = "") -> None:
    """Android 专有会话关键字：iOS（含 WDA-direct）须 lint + 运行时双拦截。"""
    plat = (get_manager(ctx).platform or "").strip().lower()
    if plat == "ios":
        raise KeywordError(
            f"{keyword_id} 仅支持 Android。"
            + (hint or _IOS_WEBVIEW_BROWSER_HINT)
        )


def _project_root(ctx: ExecutionContext) -> str:
    root = str(
        ctx.get_var("__project_path__")
        or ctx.get_var("__project_dir__")
        or ""
    ).strip()
    return root or os.getcwd()


def _device_path_tag(ctx: ExecutionContext) -> str:
    udid = str(ctx.get_var("__device_udid__") or "").strip()
    if udid:
        return "_" + re.sub(r"[^\w.-]+", "", udid)[-8:]
    slot = ctx.get_var("__worker_slot__")
    if slot not in (None, ""):
        return f"_slot{slot}"
    return ""


def _screen_record_path(
    ctx: ExecutionContext,
    file_name: str = "",
    select_if_timestamp: str = "是",
) -> str:
    """默认落盘 reports/evidence/*.mp4，便于 Runner 打进 evidence.zip。"""
    raw = str(file_name or "").strip()
    if raw and os.path.isabs(raw):
        base, ext = os.path.splitext(raw)
        if not ext:
            ext = ".mp4"
        if _truthy(select_if_timestamp):
            base = f"{base}_{time.strftime('%Y%m%d%H%M%S')}"
        path = os.path.abspath(base + ext)
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        return path

    name = raw or "screen_record"
    base, ext = os.path.splitext(name)
    if not ext:
        ext = ".mp4"
    if not raw:
        base = f"{base}{_device_path_tag(ctx)}"
    if _truthy(select_if_timestamp):
        base = f"{base}_{time.strftime('%Y%m%d%H%M%S')}"
    evidence = os.path.join(_project_root(ctx), "reports", "evidence")
    os.makedirs(evidence, exist_ok=True)
    return os.path.abspath(os.path.join(evidence, base + ext))


def _win_size(drv):
    sz = drv.get_window_size()
    return int(sz["width"]), int(sz["height"])


# 方向 -> 大写英文名
_DIR_MAP = {
    "上": "UP", "下": "DOWN", "左": "LEFT", "右": "RIGHT",
    "up": "UP", "down": "DOWN", "left": "LEFT", "right": "RIGHT",
}
# 幅度比例（全屏/半屏/微屏）
_SIZE_RATIO = {"全屏": 0.75, "半屏": 0.5, "微屏": 0.25}
# 安卓物理按键 keycode
_KEYCODE = {"home": 3, "back": 4, "menu": 82, "enter": 66}


def _swipe_by_ratio(drv, direction: str, cx_ratio: float, cy_ratio: float,
                    size_ratio: float, duration_ms: int = 800,
                    strategy: str = "auto") -> str | None:
    """以屏幕比例滑动；iOS WDA 走组件层分页策略，Android/Appium 走坐标 swipe。"""
    is_wda = getattr(drv, "wda_client", None) is not None or type(drv).__name__ == "WdaDriver"
    if is_wda:
        from ...mobile.ios.swipe import wda_swipe_by_ratio
        return wda_swipe_by_ratio(
            drv, direction, cx_ratio, cy_ratio, size_ratio, duration_ms,
            strategy=strategy,
        )
    w, h = _win_size(drv)
    cx, cy = int(w * cx_ratio), int(h * cy_ratio)
    d = _DIR_MAP.get(direction, "UP")
    dx = dy = 0
    if d == "UP":
        dy = -int(h * size_ratio)
    elif d == "DOWN":
        dy = int(h * size_ratio)
    elif d == "LEFT":
        dx = -int(w * size_ratio)
    elif d == "RIGHT":
        dx = int(w * size_ratio)
    ex = min(max(cx + dx, 1), w - 1)
    ey = min(max(cy + dy, 1), h - 1)
    drv.swipe(cx, cy, ex, ey, int(duration_ms))
    return None


# ---------------------------------------------------------------------------
# 降级：adb / 外部进程 / 下载安装依赖
# ---------------------------------------------------------------------------

# noinspection PyPep8Naming
def _resolve_apk_path(app_file: str, project_dir: str = "") -> str:
    """把「待测试的应用程序位置」解析成一个真实 Android 安装包路径，否则给可操作错误。

    - 空 → 提示缺路径；
    - 相对路径 / 跨机绝对路径 → 相对 project_dir（__project_path__）重定位；
    - 目录 → 找里面的 .apk/.apex/.xapk：唯一则用它，0 个或多个则提示；
    - 文件但后缀不对 → 提示 adb 只认 .apk/.apex/.xapk；
    - 不存在 → 提示路径不存在。
    """
    raw = str(app_file).strip().strip('"')
    if not raw:
        raise KeywordError(
            "缺少 apk 路径(appFile)，请在「待测试的应用程序位置」指向具体的 .apk/.xapk 文件"
        )
    p = resolve_project_file(project_dir, raw)
    if os.path.isdir(p):
        apks = [
            f for f in os.listdir(p)
            if f.lower().endswith(ANDROID_PACKAGE_SUFFIXES)
        ]
        if len(apks) == 1:
            return os.path.join(p, apks[0])
        if not apks:
            raise KeywordError(
                f"目录内没有 .apk/.xapk 文件：{p}（请指向具体的安装包文件，而不是文件夹）"
            )
        raise KeywordError(
            f"目录内有多个 Android 安装包，请指定具体文件：{p} → {apks}"
        )
    if not os.path.exists(p):
        hint = ""
        if project_dir and os.path.isabs(raw):
            hint = (
                f"；已相对工程根尝试重定位仍失败（工程={project_dir}）。"
                "请把安装包放进工程目录并用相对路径（如 apps/app.apk）"
            )
        elif project_dir and not os.path.isabs(raw):
            hint = f"（已按工程根解析：{p}）"
        raise KeywordError(f"应用文件不存在：{raw}{hint}")
    if not p.lower().endswith(ANDROID_PACKAGE_SUFFIXES):
        raise KeywordError(
            f"不是有效的 Android 安装包：{p}（请使用 .apk/.apex/.xapk）"
        )
    return p


def _resolve_ipa_path(app_file: str, project_dir: str = "") -> str:
    """Resolve a concrete .ipa path for iOS install."""
    raw = str(app_file).strip().strip('"')
    if not raw:
        raise KeywordError("缺少 ipa 路径(appFile)，请指向具体的 .ipa 文件")
    p = resolve_project_file(project_dir, raw)
    if os.path.isdir(p):
        ipas = [f for f in os.listdir(p) if f.lower().endswith(".ipa")]
        if len(ipas) == 1:
            return os.path.join(p, ipas[0])
        if not ipas:
            raise KeywordError(f"目录内没有 .ipa 文件：{p}")
        raise KeywordError(f"目录内有多个 .ipa，请指定具体文件：{p} -> {ipas}")
    if not os.path.exists(p):
        hint = ""
        if project_dir and os.path.isabs(raw):
            hint = (
                f"；已相对工程根尝试重定位仍失败（工程={project_dir}）。"
                "请把安装包放进工程目录并用相对路径（如 apps/app.ipa）"
            )
        elif project_dir and not os.path.isabs(raw):
            hint = f"（已按工程根解析：{p}）"
        raise KeywordError(f"应用文件不存在：{raw}{hint}")
    if not p.lower().endswith(".ipa"):
        raise KeywordError(f"不是有效的 .ipa 文件：{p}")
    return p


def _resolve_app_file_path(app_file: str, project_dir: str = "") -> tuple[str, str]:
    """解析安装包路径，返回 (具体文件路径, 'ipa' | 'apk' | 'xapk')。

    支持 .apk/.apex/.xapk/.ipa 文件，或目录内仅含唯一安装包时自动选取。
    """
    raw = str(app_file).strip().strip('"')
    if not raw:
        raise KeywordError(
            "缺少应用路径(appFile)，请指向 .apk/.apex/.xapk 或 .ipa 文件（可为含唯一安装包的目录）"
        )
    p = resolve_project_file(project_dir, raw)
    if os.path.isdir(p):
        ipas = sorted(f for f in os.listdir(p) if f.lower().endswith(".ipa"))
        apks = sorted(
            f for f in os.listdir(p) if f.lower().endswith(ANDROID_PACKAGE_SUFFIXES)
        )
        if ipas and apks:
            raise KeywordError(f"目录内同时有 .ipa 与 Android 安装包，请指定具体文件：{p}")
        if len(ipas) == 1:
            return os.path.join(p, ipas[0]), "ipa"
        if len(ipas) > 1:
            raise KeywordError(f"目录内有多个 .ipa，请指定具体文件：{p} → {ipas}")
        if len(apks) == 1:
            chosen = os.path.join(p, apks[0])
            kind = "xapk" if chosen.lower().endswith(".xapk") else "apk"
            return chosen, kind
        if len(apks) > 1:
            raise KeywordError(
                f"目录内有多个 Android 安装包，请指定具体文件：{p} → {apks}"
            )
        raise KeywordError(f"目录内没有 .apk/.xapk/.ipa 文件：{p}")
    if not os.path.exists(p):
        hint = ""
        if project_dir:
            hint = f"；请确认安装包已打进工程制品且路径相对工程根（工程={project_dir}）"
        raise KeywordError(f"应用文件不存在：{raw}{hint}")
    low = p.lower()
    if low.endswith(".ipa"):
        return p, "ipa"
    if low.endswith(".xapk"):
        return p, "xapk"
    if low.endswith((".apk", ".apex")):
        return p, "apk"
    raise KeywordError(f"无法识别安装包类型，请使用 .apk/.apex/.xapk 或 .ipa：{p}")


def _parse_apk_kw(path: str):
    """设备层 parse_apk → 关键字层 KeywordError；XAPK 会先解压取主 APK 再解析。"""
    from autopilot_platform.appparse.apk import parse_apk  # 延迟：仅 Android 安装解析
    from ...mobile.xapk import primary_apk_for_parse

    try:
        with primary_apk_for_parse(path) as parse_path:
            return parse_apk(parse_path)
    except PackageError as e:
        raise KeywordError(str(e)) from e


def _parse_ipa_kw(path: str):
    from autopilot_platform.appparse.ipa import parse_ipa  # 延迟：仅 iOS 安装解析
    try:
        return parse_ipa(path)
    except PackageError as e:
        raise KeywordError(str(e)) from e


# ---------------------------------------------------------------------------
# iOS 设备层：装/卸/检测（pymobiledevice3 优先，go-ios 回退；三端同一套，不经过 Appium）
# ---------------------------------------------------------------------------

def _ios_pmd3_run(awaitable):
    """运行 pymobiledevice3 异步 API（当前版本 install/uninstall 均为 async）。"""
    return asyncio.run(awaitable)


def _ios_app_installed(bundle_id: str, udid: str = "") -> bool:
    if not bundle_id:
        return False
    try:
        from pymobiledevice3.lockdown import create_using_usbmux
        from pymobiledevice3.services.installation_proxy import InstallationProxyService

        async def _check() -> bool:
            async with await create_using_usbmux(serial=udid or None) as lockdown:
                async with InstallationProxyService(lockdown) as svc:
                    apps = await svc.get_apps(bundle_identifiers=[bundle_id])
                    return bundle_id in apps

        return bool(_ios_pmd3_run(_check()))
    except PyMobileDevice3Exception:
        return False


def ios_install_app(ipa_path: str, udid: str = "",
                    log=None) -> str:
    """安装 iOS 应用：pymobiledevice3 优先，失败回退 go-ios。返回所用后端标识。"""
    from autopilot_platform.appparse.ipa import ipa_precheck  # 延迟：仅 iOS 安装预检

    _log = log or (lambda _m: None)
    info = _parse_ipa_kw(ipa_path)
    problems = ipa_precheck(info, udid)
    if problems:
        raise KeywordError("IPA 预检未通过：\n- " + "\n- ".join(problems))
    _log(f"预检通过：{info.bundle_id} v{info.version_name}（最低 iOS {info.minimum_os or '—'}）")
    try:
        from pymobiledevice3.lockdown import create_using_usbmux
        from pymobiledevice3.services.installation_proxy import InstallationProxyService

        async def _install() -> None:
            async with await create_using_usbmux(serial=udid or None) as lockdown:
                async with InstallationProxyService(lockdown) as svc:
                    def _progress(_pct, *_a) -> None:
                        pass  # 安装进度不打日志（pymobiledevice3 会高频回调 5/15/20…%）

                    await svc.install_from_local(Path(ipa_path), handler=_progress)

        _ios_pmd3_run(_install())
        return "pymobiledevice3"
    except Exception as pmd_err:
        from ...mobile import ios_bootstrap as ib
        if ib.available():
            ib.install_app(ipa_path, udid=udid, log=_log)
            return "go-ios"
        raise KeywordError(
            f"iOS 安装失败（pymobiledevice3 与 go-ios 均不可用）：{pmd_err}"
        ) from pmd_err

_ios_install_app = ios_install_app  # 内部/测试别名


def _ios_uninstall_app(bundle_id: str, udid: str = "",
                       log=None) -> str:
    """卸载 iOS 应用：pymobiledevice3 优先，失败回退 go-ios。返回所用后端标识。"""
    if not bundle_id:
        raise KeywordError("iOS 卸载失败：bundle id 不能为空")
    _log = log or (lambda _m: None)
    try:
        from pymobiledevice3.lockdown import create_using_usbmux
        from pymobiledevice3.services.installation_proxy import InstallationProxyService

        async def _uninstall() -> None:
            async with await create_using_usbmux(serial=udid or None) as lockdown:
                async with InstallationProxyService(lockdown) as svc:
                    await svc.uninstall(bundle_id)

        _ios_pmd3_run(_uninstall())
        return "pymobiledevice3"
    except Exception as pmd_err:
        from ...mobile import ios_bootstrap as ib
        if ib.available():
            ib.uninstall_app(bundle_id, udid=udid, log=_log)
            return "go-ios"
        raise KeywordError(
            f"iOS 卸载失败（pymobiledevice3 与 go-ios 均不可用）：{pmd_err}"
        ) from pmd_err


ios_uninstall_app = _ios_uninstall_app


# noinspection PyPep8Naming
@keyword("mobile_app_install_and_open", name="[公用]安装并启动被测应用",
         category="Mobile", legacy_impl="MobileCommKeyword:appInstallAndOpen")
def app_install_and_open(ctx: ExecutionContext, appFile: str = "",
                         keepData: str = "是", **_kw) -> None:
    # 解析包名/入口 Activity → 按 keepData 决定安装方式 → 建立 Appium 会话并启动 App
    # （建立会话是关键：后续元素点击/滑动等都依赖该会话，对齐"准备开始测试"语义）
    explicit_udid = str(_kw.get("udid") or _kw.get("deviceUdid") or "").strip()
    platform = str(_kw.get("type") or "").strip().lower()
    proj = str(ctx.variables.get("__project_path__") or "").strip()
    # 管理台批跑注入的正式应用包：覆盖用例中的 appFile（旧工程内路径仅作本地兼容）
    override = str(ctx.variables.get("__app_build_path__") or "").strip()
    if override:
        if appFile and os.path.abspath(str(appFile).strip()) != os.path.abspath(override):
            ctx.log(f"使用管理台应用资源覆盖 appFile：{override}（原={appFile}）")
        appFile = override
    low = str(appFile).lower()
    if low.endswith(".ipa"):
        platform = "ios"
    elif low.endswith(ANDROID_PACKAGE_SUFFIXES):
        platform = "android"
    elif str(appFile).strip() and not platform:
        # 相对工程目录或无后缀：先解析再建平台判断
        probed = resolve_project_file(proj, appFile).lower()
        if probed.endswith(".ipa") or os.path.isdir(probed) and any(
            f.lower().endswith(".ipa") for f in (os.listdir(probed) if os.path.isdir(probed) else [])
        ):
            platform = "ios"
        elif probed.endswith(ANDROID_PACKAGE_SUFFIXES) or (
            os.path.isdir(probed)
            and any(
                f.lower().endswith(ANDROID_PACKAGE_SUFFIXES)
                for f in os.listdir(probed)
            )
        ):
            platform = "android"
    _apply_ios_backend_mode(ctx, platform, **_kw)
    serial = _device_for_platform(ctx, platform, explicit_udid) or _serial(ctx)
    if platform == "ios":
        appFile = _resolve_ipa_path(appFile, proj)
        info = _parse_ipa_kw(appFile)
        pkg = _kw.get("packageName") or _kw.get("package") or info.bundle_id or ""
        activity = ""
        if not pkg:
            raise KeywordError(
                f"无法从 IPA 解析 Bundle ID，请检查安装包是否完整：{appFile}"
            )
        if _ios_app_installed(pkg, serial):
            backend = _ios_uninstall_app(pkg, serial, log=ctx.log)
            ctx.log(f"已卸载旧 iOS 应用：{pkg}（{backend}）")
        backend = ios_install_app(appFile, udid=serial, log=ctx.log)
        ctx.log(f"安装完成：{appFile}（{backend}）")
        device = _device_for_platform(ctx, "iOS", serial)
        ctx.log(f"准备创建 iOS Appium/WDA 会话，设备: {device or '默认'}")
        get_manager(ctx).create("iOS", pkg, activity, device)
        from ...engine.app_watch import remember_target_package

        remember_target_package(ctx, pkg)
        ctx.log(f"已启动并建立移动会话: {pkg}/{activity}" if pkg else "已建立移动会话")
        from ...mobile.ios.alert import ios_alert_after_session
        ios_alert_after_session(ctx, "after_install_and_open")
        return
    appFile = _resolve_apk_path(appFile, proj)   # 预检：相对工程根 / 目录取唯一 apk
    # 包名/入口 Activity：优先取传入参数，否则解析 apk（纯 Python，不依赖 aapt）
    pkg = _kw.get("packageName") or _kw.get("package") or ""
    activity = _kw.get("activityName") or _kw.get("activity") or ""
    if not (pkg and activity):
        info = _parse_apk_kw(appFile)
        pkg = pkg or info.package
        activity = activity or info.main_activity
    # keepData=否 且目标已安装 → 先卸载(清数据)再全新安装；keepData=是 且已安装 → 覆盖重装(-r)
    # 未安装时直接安装（不加 -r），避免把“是否保留数据”与“是否已安装”混在一起
    keep = str(keepData).strip() not in ("否", "false", "False", "no", "0")
    installed = bool(pkg and _app_installed(pkg, serial))
    if installed and not keep:
        run_adb(["uninstall", pkg], serial=serial, timeout=120)
        ctx.log(f"已卸载旧应用(不保留数据): {pkg}")
        out = install_android_package(appFile, serial=serial, replace=False)
    elif installed and keep:
        out = install_android_package(appFile, serial=serial, replace=True)
    else:
        out = install_android_package(appFile, serial=serial, replace=False)
    ctx.log(f"已安装应用: {appFile}\n{out}")
    # 建立 Appium 会话（带包名/Activity 时由 Appium 直接拉起 App），供后续元素操作使用
    typ = "Android"
    device = _device_for_platform(ctx, "Android", serial)
    ctx.log(f"准备创建 Android Appium 会话，设备: {device or '默认'}")
    get_manager(ctx).create(typ, pkg, activity, device)
    from ...engine.app_watch import remember_target_package

    remember_target_package(ctx, pkg)
    ctx.log(f"已启动并建立移动会话: {pkg}/{activity}" if pkg else "已建立移动会话")


# 解析安装包关键字：默认输出变量名（用户只需填 appFile）
APP_PACKAGE_VAR = "app_package"
APP_ACTIVITY_VAR = "app_activity"


def _emit_step_log(ctx: ExecutionContext, msg: str) -> None:
    """步骤日志：写入上下文（执行器 PASS 时写入控制台「信息」列）。"""
    ctx.log(msg)


# noinspection PyPep8Naming
@keyword("mobile_app_get_package_and_activity", name="解析安装包信息",
         category="Mobile", out_params=["package", "activity"],
         legacy_impl="MobileCommKeyword:appGetPackageAndActivity")
def app_get_package_and_activity(ctx: ExecutionContext, appFile: str = "",
                                 package: str = "", activity: str = "",
                                 **_kw) -> dict:
    # 按后缀/目录自动识别 .ipa 与 .apk/.apex/.xapk，本地解析包名或 Bundle ID。
    # 默认写入 app_package / app_activity，无需手填输出变量名。
    # 无 appFile 时回退 adb dumpsys 取当前前台应用（仅 Android）。
    out_pkg, out_act = (
        str(package).strip() or APP_PACKAGE_VAR,
        str(activity).strip() or APP_ACTIVITY_VAR,
    )
    override = str(ctx.variables.get("__app_build_path__") or "").strip()
    if override:
        appFile = override
    if str(appFile).strip():
        proj = str(ctx.variables.get("__project_path__") or "").strip()
        path, kind = _resolve_app_file_path(appFile, proj)
        if kind == "ipa":
            info = _parse_ipa_kw(path)
            pkg, act = info.bundle_id, ""
            _emit_step_log(ctx, f"app_package={pkg}（iOS Bundle ID）")
        else:
            info = _parse_apk_kw(path)
            pkg, act = info.package, info.main_activity
            _emit_step_log(ctx, f"app_package={pkg}；app_activity={act}")
        return {out_pkg: pkg, out_act: act}
    mgr = get_manager(ctx)
    if mgr.platform == "ios":
        drv = mgr.optional_driver()
        if drv is None:
            raise KeywordError(
                "iOS 未提供 appFile 时需已建自动化会话，或维护变量 app_package"
            )
        backend = ios_driver_backend(drv, mgr.backend)
        pkg = ios_current_bundle_id(drv, backend)
        if not pkg:
            from ...mobile.ios.monkey.bundle import resolve_target_bundle_id
            pkg = resolve_target_bundle_id(ctx)
        if not pkg:
            raise KeywordError(
                "iOS 无法解析 Bundle ID：请提供 appFile，或在用例中设置 app_package"
            )
        _emit_step_log(ctx, f"app_package={pkg}（iOS 当前 Bundle ID）")
        return {out_pkg: pkg, out_act: ""}
    serial = _serial(ctx)
    focus = _resumed_package_activity(serial)
    if not focus or "/" not in focus:
        raise KeywordError("未提供 appFile 且无法从 dumpsys 解析当前包名/Activity（仅 Android 支持）")
    pkg, _, act = focus.partition("/")
    if act.startswith("."):
        act = pkg + act
    _emit_step_log(ctx, f"app_package={pkg}；app_activity={act}")
    return {out_pkg: pkg, out_act: act}


# noinspection PyPep8Naming
@keyword("mobile_app_reset_saveinfo", name="重启被测应用(保存用户信息)",
         category="Mobile", legacy_impl="MobileCommKeyword:resetAppSaveInfo")
def app_reset_save_info(ctx: ExecutionContext, packageName: str = "", **_kw) -> None:
    """强制停止并重新拉起被测应用（不清数据，保留登录等用户信息）。

    经内置 adb 实现，跨平台：am force-stop + monkey LAUNCHER 重启。
    packageName 为空时取会话当前包，回退 dumpsys 解析。
    """
    serial = _serial(ctx)
    pkg = str(packageName).strip()
    if not pkg:
        # noinspection PyBroadException
        try:
            pkg = get_manager(ctx).driver().current_package or ""
        except Exception:
            pkg = ""
    if not pkg:
        focus = _resumed_package_activity(serial)
        pkg = focus.split("/")[0] if focus else ""
    if not pkg:
        raise KeywordError("无法确定被测应用包名，无法重启")

    pkg = require_android_package(pkg)
    adb_shell(f"am force-stop {pkg}", serial=serial)
    adb_shell(f"monkey -p {pkg} -c android.intent.category.LAUNCHER 1", serial=serial)
    ctx.log(f"已重启应用(保留数据): {pkg}")


# noinspection PyShadowingBuiltins,PyPep8Naming
@keyword("mobile_app_adb_uninstall", name="卸载移动应用", category="Mobile",
         legacy_impl="MobileCommKeyword:uninstallADB")
def app_adb_uninstall(ctx: ExecutionContext, type: str = "android",
                      packageName: str = "", cacheSave: str = "否", **_kw) -> None:
    if not str(packageName).strip():
        raise ValueError("卸载移动应用失败：packageName 不能为空")

    packageName = require_android_package(packageName)
    platform = str(type or "").strip().lower()
    explicit_udid = str(_kw.get("udid") or _kw.get("deviceUdid") or "").strip()
    if platform.startswith("ios"):
        serial = _device_for_platform(ctx, type, explicit_udid) or _serial(ctx)
        backend = _ios_uninstall_app(packageName, serial, log=ctx.log)
        ctx.log(f"已卸载 iOS 应用 {packageName}（{backend}）")
        return
    serial = _device_for_platform(ctx, type, explicit_udid) or _serial(ctx)
    # cacheSave=是 时保留数据/缓存目录(pm uninstall -k)
    keep = str(cacheSave).strip() in ("是", "true", "True", "1", "yes")
    args = ["shell", "pm", "uninstall"]
    if keep:
        args.append("-k")
    args.append(packageName)
    out = run_adb(args, serial=serial, timeout=120)
    ctx.log(f"卸载应用 {packageName}: {out.strip()}")


def _bundled_apks_dir() -> str:
    """内置输入法 apk 目录：<项目根>/resources/re_apks。"""
    # session.py → mobile → keywords → autopilot → <root>
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
    return os.path.join(root, "resources", "re_apks")


def _install_and_enable_ime(ctx: ExecutionContext, apk_name: str, friendly: str) -> None:
    """安装内置输入法 apk 并启用/切换为默认，供录制期中文/特殊字符输入。

    包名从 apk 解析，IME 组件从 `ime list -a -s` 里按包名匹配——不硬编码组件名。
    """
    apk_path = os.path.join(_bundled_apks_dir(), apk_name)
    if not os.path.isfile(apk_path):
        raise KeywordError(f"未找到内置输入法 apk：{apk_path}（请确认 resources/re_apks/{apk_name} 存在）")
    serial = _serial(ctx)
    out = run_adb(["install", "-r", apk_path], serial=serial, timeout=180)
    if "Success" not in out and "success" not in out.lower():
        raise KeywordError(f"{friendly} 安装失败：{out.strip()}")
    pkg = _parse_apk_kw(apk_path).package
    if not pkg:
        ctx.log(f"{friendly} 已安装，但无法解析包名，跳过启用（请手动在系统设置里启用输入法）")
        return
    # 列出所有已安装 IME（-a 含未启用；用长格式，部分 ROM 的 -s 短格式会漏列老 apk），
    # 按包名挑出本 apk 的输入法组件（组件行形如 "pkg/.Service:"，去掉尾部冒号）
    listed = adb_shell("ime list -a", serial=serial) or ""
    comp = next((ln.strip().split()[0].rstrip(":") for ln in listed.splitlines()
                 if ln.strip().startswith(pkg + "/")), "")
    if not comp:
        ctx.log(f"{friendly} 已安装（{pkg}），但未在 ime 列表中找到组件，跳过启用")
        return
    adb_shell(f"ime enable {comp}", serial=serial)
    adb_shell(f"ime set {comp}", serial=serial)
    ctx.log(f"{friendly} 已安装并设为当前输入法：{comp}")


@keyword("installUtf7Ime", name="安装中文输入法", category="Mobile",
         legacy_impl="MobileCommKeyword:installUtf7Ime")
def install_utf7_ime(ctx: ExecutionContext, **_kw) -> None:
    _install_and_enable_ime(ctx, "Utf7Ime.apk", "UTF-7 输入法")


@keyword("installAdbkeyboard", name="安装adbkeyboard输入法", category="Mobile",
         legacy_impl="MobileCommKeyword:installAdbkeyboard")
def install_adbkeyboard(ctx: ExecutionContext, **_kw) -> None:
    _install_and_enable_ime(ctx, "ADBKeyBoard.apk", "ADBKeyboard 输入法")


# noinspection PyPep8Naming
@keyword("mobile_get_device_ip", name="获取设备 WIFI IP(mobile)",
         category="Mobile", out_params=["outVar"],
         legacy_impl="MobileCommKeyword:getDeviceIp")
def get_device_ip(ctx: ExecutionContext, outVar: str = "", **_kw) -> dict:
    mgr = get_manager(ctx)
    drv = mgr.optional_driver()
    if mgr.platform == "ios":
        if drv is None:
            raise KeywordError("iOS 会话未创建，无法获取设备 IP")
        from ...mobile.ios.device_info import driver_device_info
        ip = str((driver_device_info(drv) or {}).get("ip") or "").strip()
        if not ip:
            raise KeywordError("无法从 iOS 设备状态读取 WIFI IP（WDA /status 无 ip 字段）")
        ctx.log(f"设备 WIFI IP: {ip}")
        return {outVar: ip} if outVar else {}
    serial = _serial(ctx)
    ip = ""
    # 首选 ip addr（新系统），回退 ifconfig（老系统）
    # noinspection PyBroadException
    try:
        out = adb_shell("ip -f inet addr show wlan0", serial=serial)
        m = re.search(r"inet\s+(\d+\.\d+\.\d+\.\d+)", out)
        if m:
            ip = m.group(1)
    except Exception:
        ip = ""
    if not ip:
        out = adb_shell("ifconfig wlan0", serial=serial)
        m = re.search(r"(?:inet addr:|inet\s+)(\d+\.\d+\.\d+\.\d+)", out)
        if not m:
            raise RuntimeError("WIFI 连接异常，请检查WIFI连接！")
        ip = m.group(1)
    ctx.log(f"设备 WIFI IP: {ip}")
    return {outVar: ip} if outVar else {}


def _int_pair(s) -> list:
    """把 'a,b' / 'a*b' / 'a x b' 解析成 [a, b] 整数(尽力)。"""
    nums = []
    for p in re.split(r"[,x×*\s]+", str(s or "").strip()):
        # noinspection PyBroadException
        try:
            if p.strip():
                nums.append(int(float(p)))
        except Exception:
            pass
    return nums


# noinspection PyPep8Naming
@keyword("mobile_commActionTouch", name="安卓九宫格解锁(通用)", category="Mobile",
         legacy_impl="MobileCommKeyword:androidCommActionTouch")
def comm_action_touch(ctx: ExecutionContext, resolution="", startCoordinate="",
                      deviation="", count="4", **_kw) -> None:
    """九宫格/连续手势：从 startCoordinate 起，按 deviation 递增连出 count 个点，
    手指不抬地连续滑过（真·图案解锁）。给了 resolution 则把坐标从该分辨率等比缩放到
    当前屏幕，适配不同分辨率。"""
    start = _int_pair(startCoordinate)
    dev = _int_pair(deviation)
    if len(start) < 2 or len(dev) < 2:
        raise KeywordError("需提供 startCoordinate=x,y 与 deviation=dx,dy")
    try:
        n = max(int(float(str(count) or "2")), 2)
    except (TypeError, ValueError):
        n = 2
    pts = [(start[0] + i * dev[0], start[1] + i * dev[1]) for i in range(n)]
    drv = get_manager(ctx).driver()
    res = _int_pair(resolution)
    if len(res) >= 2 and res[0] and res[1]:
        # noinspection PyBroadException
        try:
            size = drv.get_window_size()
            sx, sy = size["width"] / res[0], size["height"] / res[1]
            pts = [(int(x * sx), int(y * sy)) for x, y in pts]
        except Exception:
            pass
    # noinspection PyBroadException
    try:
        from selenium.webdriver.common.actions.action_builder import ActionBuilder
        from selenium.webdriver.common.actions.pointer_input import PointerInput
        from selenium.webdriver.common.actions import interaction
        ab = ActionBuilder(drv, mouse=PointerInput(interaction.POINTER_TOUCH, "touch"))
        ab.pointer_action.move_to_location(pts[0][0], pts[0][1]).pointer_down()
        for x, y in pts[1:]:
            ab.pointer_action.move_to_location(x, y)
        ab.pointer_action.pointer_up()
        ab.perform()
    except Exception:
        # 回退：分段 swipe（手指会抬起，非严格连续，尽力而为）
        for i in range(len(pts) - 1):
            drv.swipe(pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1], 300)
    ctx.log(f"九宫格手势路径: {pts}")


@keyword("performance_data_capture", name="性能数据捕获", category="Mobile",
         legacy_impl="MobileCommKeyword:performanceDataCapture")
def performance_data_capture(ctx: ExecutionContext, **_kw) -> dict:
    serial = _serial(ctx)
    # 目标包：参数 > dumpsys 当前前台包
    pkg = _kw.get("package") or _kw.get("packageName") or ""
    if not pkg:
        focus = _resumed_package_activity(serial)
        pkg = focus.split("/")[0] if focus else ""
    if not pkg:
        raise RuntimeError("性能采集失败：无法确定目标包名")
    meminfo = adb_shell(f"dumpsys meminfo {pkg}", serial=serial, timeout=60)
    cpuinfo = adb_shell(f"dumpsys cpuinfo {pkg}", serial=serial, timeout=60)
    # 解析 TOTAL 内存(KB)
    mem = ""
    m = re.search(r"TOTAL(?: PSS)?:?\s+(\d+)", meminfo)
    if m:
        mem = m.group(1)
    # 解析该包 CPU 占用率
    cpu = ""
    for line in cpuinfo.replace("\r", "").split("\n"):
        if pkg in line:
            c = re.search(r"([\d.]+)%", line)
            if c:
                cpu = c.group(1)
                break
    ctx.log(f"性能采集 包[{pkg}] 内存TOTAL[{mem}]KB CPU[{cpu}]%")
    result = {"package": pkg, "memory": mem, "cpu": cpu}
    out_var = _kw.get("outVar")
    return {out_var: result} if out_var else {}


# noinspection PyPep8Naming
@keyword("intentToMiniProgram", name="通过URL Scheme跳转到小程序",
         category="Mobile", legacy_impl="MobileCommKeyword:intentToMiniProgram")
def intent_to_mini_program(ctx: ExecutionContext, urlPath: str = "", **_kw) -> None:
    """通过 adb am start 以 VIEW 意图打开 URL Scheme（如 weixin://…、alipays://…）。"""
    if not str(urlPath).strip():
        raise KeywordError("缺少 urlPath（URL Scheme），无法跳转")
    serial = _serial(ctx)
    # 转义 & (shell 特殊字符)，避免 scheme 里的查询串被截断
    safe = str(urlPath).replace("&", "\\&")
    adb_shell(f"am start -a android.intent.action.VIEW -d '{safe}'", serial=serial)
    ctx.log(f"已通过 URL Scheme 跳转: {urlPath}")


# ---------------------------------------------------------------------------
# 实现：纯 Appium
# ---------------------------------------------------------------------------

# noinspection PyPep8Naming
@keyword("mobile_app_open_and_jump", name="启动被测应用并跳转到指定界面",
         category="Mobile", legacy_impl="MobileCommKeyword:appOpenAndJump")
def app_open_and_jump(ctx: ExecutionContext, packageName: str = "",
                      route: str = "", **_kw) -> None:
    drv = _drv(ctx)
    # route 视为目标 Activity，使用 appium start_activity 拉起指定界面
    drv.start_activity(packageName, route)
    ctx.log(f"已启动 {packageName} 并跳转到 {route}")


# noinspection PyPep8Naming
@keyword("boolean_app_isInstalled", name="获取应用是否已经安装(mobile)",
         category="Mobile", out_params=["outVar"],
         legacy_impl="MobileCommKeyword:appIsInstalled")
def app_is_installed(ctx: ExecutionContext, packageName: str = "",
                     outVar: str = "", **_kw) -> dict:
    mgr = get_manager(ctx)
    drv = mgr.optional_driver()
    backend = ios_driver_backend(drv, mgr.backend) if drv else mgr.backend
    serial = _serial(ctx)
    installed = ios_is_app_installed(
        packageName,
        udid=serial,
        driver=drv,
        backend=backend,
        device_check=_ios_app_installed,
    )
    result = "YES" if installed else "NO"
    ctx.log(f"app {'has been' if installed else 'not'} installed")
    return {outVar: result} if outVar else {}


@keyword("mobile_app_reset", name="重启应用", category="Mobile",
         legacy_impl="MobileCommKeyword:resetApp")
def app_reset(ctx: ExecutionContext, **_kw) -> None:
    mgr = get_manager(ctx)
    drv = mgr.driver()
    backend = ios_driver_backend(drv, mgr.backend)
    ios_reset_app(drv, backend, ctx=ctx)
    ctx.log("应用已重启")


@keyword("mobile_app_launch", name="打开应用", category="Mobile",
         legacy_impl="MobileCommKeyword:launchApp")
def app_launch(ctx: ExecutionContext, **_kw) -> None:
    mgr = get_manager(ctx)
    drv = mgr.driver()
    backend = ios_driver_backend(drv, mgr.backend)
    ios_launch_app(drv, backend)
    ctx.log("应用已打开")


# noinspection PyPep8Naming
@keyword("mobile_app_snapshot", name="截屏(wap)", category="Mobile",
         out_params=["outVar"], legacy_impl="MobileCommKeyword:mobileSnapshot")
def app_snapshot(ctx: ExecutionContext, fileName: str = "",
                 select_if_timestamp: str = "是", outVar: str = "",
                 **_kw) -> dict:
    drv = _drv(ctx)
    name = fileName or "snapshot"
    base, ext = os.path.splitext(name)
    if not ext:
        ext = ".png"
    # 多机并行默认路径带设备标识，避免同写一个文件
    if not fileName:
        udid = str(ctx.get_var("__device_udid__") or "").strip()
        slot = ctx.get_var("__worker_slot__")
        tag = ""
        if udid:
            tag = "_" + re.sub(r"[^\w.-]+", "", udid)[-8:]
        elif slot not in (None, ""):
            tag = f"_slot{slot}"
        base = f"{base}{tag}"
    if _truthy(select_if_timestamp):
        base = f"{base}_{time.strftime('%Y%m%d%H%M%S')}"
    path = os.path.abspath(base + ext)
    drv.get_screenshot_as_file(path)
    ctx.log(f"终端截屏: {path}")
    return {outVar: path} if outVar else {}


def _start_android_screen_record(
    ctx: ExecutionContext,
    time_limit: str = "180",
    bit_rate: str = "",
) -> None:
    drv = _drv(ctx)
    if not hasattr(drv, "start_recording_screen"):
        raise KeywordError(
            "当前 driver 不支持 start_recording_screen（需要 Android Appium UiAutomator2）。"
        )
    opts: dict = {}
    tl = _to_int(time_limit, 180)
    if tl > 0:
        opts["timeLimit"] = str(tl)
    br = str(bit_rate or "").strip()
    if br:
        opts["bitRate"] = br
    try:
        if opts:
            drv.start_recording_screen(**opts)
        else:
            drv.start_recording_screen()
    except TypeError:
        drv.start_recording_screen()
    except Exception as e:
        raise KeywordError(f"开始屏幕录像失败: {e}") from e
    ctx.set_var(_SCREEN_REC_FLAG, "android")
    ctx.log(
        "已开始屏幕录像（Android Appium）"
        + (f"（timeLimit={opts.get('timeLimit')}s）" if opts.get("timeLimit") else "")
    )


def _start_ios_screen_record(ctx: ExecutionContext) -> None:
    from ...mobile.ios_screen_record import (
        probe_ios_screen_record,
        start_ios_screen_record,
    )

    ok, reason = probe_ios_screen_record()
    if not ok:
        raise KeywordError(reason)
    mgr = get_manager(ctx)
    udid = str(ctx.get_var("__device_udid__") or "").strip()
    if not udid:
        udid = str(getattr(mgr, "udid", "") or "").strip()
    if not udid:
        raise KeywordError("缺少设备 UDID，iOS 屏幕录像关键字不可用")
    path = _screen_record_path(ctx, file_name="", select_if_timestamp="是")
    # 与并行 slot / AppiumManager 端口对齐，避免录屏用错隧道或误 reclaim
    info_port = ctx.get_var("__tunnel_info_port__") or getattr(mgr, "_tunnel_port", 0)
    wda_port = ctx.get_var("__wda_local_port__") or getattr(mgr, "_wda_port", 0)
    mjpeg_port = ctx.get_var("__mjpeg_local_port__") or getattr(mgr, "_mjpeg_port", 0)
    try:
        sess = start_ios_screen_record(
            udid,
            path,
            log=ctx.log,
            info_port=info_port,
            wda_port=wda_port,
            mjpeg_port=mjpeg_port,
            worker_slot=ctx.get_var("__worker_slot__"),
        )
    except RuntimeError as e:
        raise KeywordError(str(e)) from e
    ctx.set_var(_SCREEN_REC_FLAG, "ios")
    ctx.set_var(_SCREEN_REC_PATH, path)
    src = getattr(sess, "source", "goios")
    ctx.log(f"已开始屏幕录像（iOS/{src} → {path}）")


def _stop_android_screen_record(
    ctx: ExecutionContext,
    file_name: str = "",
    select_if_timestamp: str = "是",
) -> str:
    drv = _drv(ctx)
    if not hasattr(drv, "stop_recording_screen"):
        raise KeywordError(
            "当前 driver 不支持 stop_recording_screen（需要 Android Appium UiAutomator2）。"
        )
    try:
        payload = drv.stop_recording_screen()
    except Exception as e:
        raise KeywordError(f"停止屏幕录像失败: {e}") from e
    if payload is None:
        raise KeywordError("停止屏幕录像失败: driver 未返回录像数据")
    if isinstance(payload, (bytes, bytearray)):
        data = bytes(payload)
    else:
        text = str(payload).strip()
        if not text:
            raise KeywordError("停止屏幕录像失败: 返回内容为空")
        try:
            data = base64.b64decode(text, validate=False)
        except Exception as e:
            raise KeywordError(f"停止屏幕录像失败: base64 解码错误: {e}") from e
    if not data:
        raise KeywordError("停止屏幕录像失败: 解码后文件为空")
    path = _screen_record_path(
        ctx, file_name=file_name, select_if_timestamp=select_if_timestamp
    )
    with open(path, "wb") as f:
        f.write(data)
    return path


def _stop_ios_screen_record(
    ctx: ExecutionContext,
    file_name: str = "",
    select_if_timestamp: str = "是",
) -> str:
    from ...mobile.ios_screen_record import stop_ios_screen_record

    udid = str(ctx.get_var("__device_udid__") or "").strip()
    if not udid:
        mgr = get_manager(ctx)
        udid = str(getattr(mgr, "udid", "") or "").strip()
    try:
        path = stop_ios_screen_record(udid)
    except RuntimeError as e:
        raise KeywordError(str(e)) from e
    if str(file_name or "").strip():
        dest = _screen_record_path(
            ctx, file_name=file_name, select_if_timestamp=select_if_timestamp
        )
        if os.path.abspath(dest) != os.path.abspath(path):
            os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
            shutil.move(path, dest)
            path = dest
    return path


# noinspection PyPep8Naming
@keyword(
    "mobile_start_screen_record",
    name="开始屏幕录像",
    category="Mobile",
    legacy_impl="MobileCommKeyword:mobileStartScreenRecord",
)
def start_screen_record(
    ctx: ExecutionContext,
    timeLimit: str = "180",
    bitRate: str = "",
    **_kw,
) -> None:
    """Android：Appium startRecordingScreen；iOS：go-ios screenshot --stream。"""
    plat = (get_manager(ctx).platform or "").strip().lower()
    if plat == "ios":
        _start_ios_screen_record(ctx)
        return
    if plat and plat != "android":
        raise KeywordError(f"mobile_start_screen_record 不支持平台: {plat}")
    _start_android_screen_record(ctx, time_limit=timeLimit, bit_rate=bitRate)


# noinspection PyPep8Naming
@keyword(
    "mobile_stop_screen_record",
    name="停止屏幕录像",
    category="Mobile",
    out_params=["outVar"],
    legacy_impl="MobileCommKeyword:mobileStopScreenRecord",
)
def stop_screen_record(
    ctx: ExecutionContext,
    fileName: str = "",
    select_if_timestamp: str = "是",
    outVar: str = "",
    **_kw,
) -> dict:
    """停止录像并落盘 mp4（默认 reports/evidence/）。"""
    plat = (get_manager(ctx).platform or "").strip().lower()
    mode = str(ctx.get_var(_SCREEN_REC_FLAG) or "").strip().lower()
    try:
        if mode == "ios" or (not mode and plat == "ios"):
            path = _stop_ios_screen_record(
                ctx, file_name=fileName, select_if_timestamp=select_if_timestamp
            )
        else:
            path = _stop_android_screen_record(
                ctx, file_name=fileName, select_if_timestamp=select_if_timestamp
            )
    finally:
        ctx.set_var(_SCREEN_REC_FLAG, "")
        ctx.set_var(_SCREEN_REC_PATH, "")
    ctx.log(f"屏幕录像已保存: {path} ({os.path.getsize(path)} bytes)")
    return {outVar: path} if outVar else {}


# noinspection PyPep8Naming
@keyword("mobile_set_network", name="设置网络连接状态", category="Mobile",
         legacy_impl="MobileCommKeyword:mobileSetNetwork")
def set_network(ctx: ExecutionContext, airplaneMode: str = "false",
                wifi: str = "false", data: str = "true", **_kw) -> None:
    _reject_ios_android_only(
        ctx,
        "mobile_set_network",
        " iOS 无 Appium set_network_connection；请用系统设置或设备层能力。",
    )
    drv = _drv(ctx)
    air = _truthy(airplaneMode)
    w = _truthy(wifi)
    d = _truthy(data)
    # Android NetworkConnection bitmask: airplane=1, Wi-Fi=2, data=4
    if air:
        mask = 1
    else:
        mask = (2 if w else 0) | (4 if d else 0)
    drv.set_network_connection(mask)
    ctx.log(f"设置网络连接: airplane={air}, wifi={w}, data={d} -> {mask}")


# noinspection PyPep8Naming
@keyword("mobile_presskey", name="物理按键", category="Mobile",
         legacy_impl="MobileCommKeyword:mobilePressKey")
def press_key(ctx: ExecutionContext, oKeys: str = "home", count: str = "1",
              **_kw) -> None:
    mgr = get_manager(ctx)
    drv = mgr.driver()
    backend = ios_driver_backend(drv, mgr.backend)
    n = max(1, _to_int(count, 1))
    if backend == "wda" or mgr.platform == "ios":
        ios_press_physical_key(drv, backend or "appium", oKeys, count=n)
    else:
        code = _KEYCODE.get(str(oKeys).strip().lower(), 3)
        for _ in range(n):
            drv.press_keycode(code)
            time.sleep(1)
    ctx.log(f"移动终端执行{oKeys}操作。")


@keyword("mobile_swipe_direction", name="[公用]按方向滑屏", category="Mobile",
         legacy_impl="MobileCommKeyword:mobileSwipeDirection")
def swipe_direction(ctx: ExecutionContext, direction: str = "上",
                    size: str = "全屏", count: str = "1",
                    duration: str = "1000", strategy: str = "auto",
                    **_kw) -> None:
    """按方向滑屏。iOS WDA 可选 strategy：auto|scrollview|xctest|w3c（分页 carousel 推荐 auto）。"""
    drv = _drv(ctx)
    ratio = _SIZE_RATIO.get(str(size).strip(), 0.5)
    n = max(1, _to_int(count, 1))
    dur = max(100, _to_int(duration, 1000))
    strat = (strategy or "auto").strip().lower()
    if strat not in ("auto", "scrollview", "xctest", "w3c"):
        strat = "auto"
    for i in range(n):
        time.sleep(1)
        ctx.log(f"执行滑屏swipe操作第{i + 1}次")
        used = _swipe_by_ratio(drv, direction, 0.5, 0.5, ratio, dur, strategy=strat)
        if used:
            ctx.log(f"滑屏策略: {used}")
        rest = (dur - 1000) / 1000.0
        if rest > 0:
            time.sleep(rest)


# noinspection PyPep8Naming
@keyword("mobile_define_swipe_direction",
         name="自定义起止位置按方向滑屏(mobile/wap)", category="Mobile",
         legacy_impl="MobileCommKeyword:mobileDefineSwipeDirection")
def define_swipe_direction(ctx: ExecutionContext, direction: str = "上",
                           localStationX: str = "0.5",
                           localStationY: str = "0.5", size: str = "0.25",
                           count: str = "1", **_kw) -> None:
    drv = _drv(ctx)
    cx = _to_float(localStationX, 0.5)
    cy = _to_float(localStationY, 0.5)
    ratio = _to_float(size, 0.25)
    n = max(1, _to_int(count, 1))
    for i in range(n):
        ctx.log(f"执行滑屏操作第{i + 1}次,起始:{cx},{cy},幅度:{ratio}")
        _swipe_by_ratio(drv, direction, cx, cy, ratio, 800)
        time.sleep(1)


@keyword("mobile_slip_for_element", name="[公用]滚动屏幕至目标控件",
         category="Mobile",
         legacy_impl="MobileCommKeyword:mobileSlipScreenWaitForElement")
def slip_for_element(ctx: ExecutionContext, direction: str = "上",
                     size: str = "半屏", times: str = "10",
                     locator: str = "", **_kw) -> None:
    mgr = get_manager(ctx)
    drv = _drv(ctx)
    ratio = _SIZE_RATIO.get(str(size).strip(), 0.5)
    n = max(1, _to_int(times, 10))
    backend = ios_driver_backend(drv, mgr.backend)

    def _swipe() -> None:
        _swipe_by_ratio(drv, direction, 0.5, 0.5, ratio, 800)

    if mgr.platform == "ios":
        from ...mobile.ios.scroll import scroll_until_element_found
        scroll_until_element_found(
            drv, backend,
            try_find=lambda: find_element(ctx, locator),
            swipe=_swipe,
            max_attempts=n,
        )
        ctx.log("已滚动至目标控件")
        return

    for i in range(n):
        # noinspection PyBroadException
        try:
            find_element(ctx, locator)
            ctx.log(f"已滚动至目标控件(第{i}次滑动后找到)")
            return
        except Exception:
            _swipe()
            time.sleep(0.5)
    find_element(ctx, locator)


# noinspection PyPep8Naming
@keyword("mobile_define_slip_for_element", name="[公用]自定义滚动屏幕至目标控件",
         category="Mobile",
         legacy_impl="MobileCommKeyword:mobileDefineSlipScreenWaitForElement")
def define_slip_for_element(ctx: ExecutionContext, locator: str = "",
                            direction: str = "上", localStationX: str = "0.5",
                            localStationY: str = "0.5", size: str = "0.25",
                            timeout: str = "30000", **_kw) -> None:
    mgr = get_manager(ctx)
    drv = _drv(ctx)
    cx = _to_float(localStationX, 0.5)
    cy = _to_float(localStationY, 0.5)
    ratio = _to_float(size, 0.25)
    deadline = time.time() + max(1, _to_int(timeout, 30000)) / 1000.0
    backend = ios_driver_backend(drv, mgr.backend)

    def _swipe() -> None:
        _swipe_by_ratio(drv, direction, cx, cy, ratio, 800)

    if mgr.platform == "ios":
        from ...mobile.ios.scroll import scroll_until_element_found
        scroll_until_element_found(
            drv, backend,
            try_find=lambda: find_element(ctx, locator),
            swipe=_swipe,
            max_attempts=9999,
            deadline=deadline,
        )
        ctx.log("已自定义滚动至目标控件")
        return

    while time.time() < deadline:
        # noinspection PyBroadException
        try:
            find_element(ctx, locator)
            ctx.log("已自定义滚动至目标控件")
            return
        except Exception:
            _swipe_by_ratio(drv, direction, cx, cy, ratio, 800)
            time.sleep(0.5)
    find_element(ctx, locator)


# noinspection PyPep8Naming
@keyword("mobile_tap", name="点击某个坐标(mobile)", category="Mobile",
         legacy_impl="MobileCommKeyword:mobileTap")
def tap(ctx: ExecutionContext, x: str = "", y: str = "", locator: str = "",
        tapStabilTime: str = "5", **_kw) -> None:
    drv = _drv(ctx)
    if str(x).strip() and str(y).strip():
        _tap_xy(drv, _to_int(x), _to_int(y), _to_int(tapStabilTime, 5))
    elif str(locator).strip():
        find_element(ctx, locator).click()
    else:
        raise ValueError("mobile_tap 需要 x/y 坐标或 locator 至少其一")


def _tap_xy(drv, x: int, y: int, _stabil: int = 5) -> None:
    from ...mobile.ios.gesture import tap_at
    tap_at(drv, x, y)


def _long_press_xy(drv, x: int, y: int, dur_ms: int) -> None:
    from ...mobile.ios.gesture import long_press_at
    long_press_at(drv, x, y, dur_ms)


# noinspection PyPep8Naming
@keyword("mobile_tap_auto", name="坐标兼容点击(mobile)", category="Mobile",
         legacy_impl="MobileCommKeyword:mobileTapAuto")
def tap_auto(ctx: ExecutionContext, x: str = "", y: str = "",
             screen_width: str = "", screen_height: str = "",
             tapStabilTime: str = "5", **_kw) -> None:
    drv = _drv(ctx)
    px, py = _to_int(x), _to_int(y)
    ref_w, ref_h = _to_int(screen_width), _to_int(screen_height)
    cur_w, cur_h = _win_size(drv)
    if ref_w > 0:
        px = cur_w * px // ref_w
    if ref_h > 0:
        py = cur_h * py // ref_h
    _tap_xy(drv, px, py, _to_int(tapStabilTime, 5))
    ctx.log(f"兼容点击坐标 ({px},{py})")


@keyword("mobile_longclick", name="[公用]长按操作", category="Mobile",
         legacy_impl="MobileCommKeyword:mobileLongClick")
def long_click(ctx: ExecutionContext, locator: str = "", x: str = "",
               y: str = "", duration: str = "1000", **_kw) -> None:
    drv = _drv(ctx)
    dur_ms = max(100, _to_int(duration, 1000))
    if str(locator).strip():
        el = find_element(ctx, locator)
        rect = el.rect
        px = int(rect["x"] + rect["width"] / 2)
        py = int(rect["y"] + rect["height"] / 2)
    elif str(x).strip() and str(y).strip():
        px, py = _to_int(x), _to_int(y)
    else:
        raise ValueError("mobile_longclick 需要 locator 或 x/y 坐标")
    _long_press_xy(drv, px, py, dur_ms)
    ctx.log(f"长按 ({px},{py}) {dur_ms}ms")


@keyword("mobile_move_to_element", name="移动屏幕至目标控件(wap)",
         category="Mobile", legacy_impl="MobileCommKeyword:mobileMoveToElement")
def move_to_element(ctx: ExecutionContext, locator: str = "", **_kw) -> None:
    mgr = get_manager(ctx)
    drv = mgr.driver()
    backend = ios_driver_backend(drv, mgr.backend)
    el = find_element(ctx, locator)
    ios_scroll_to_element(drv, el, backend)
    ctx.log("已移动屏幕至目标控件")


@keyword("native_web_swith_context", name="切换移动上下文(h5/wap)",
         category="Mobile",
         legacy_impl="MobileCommKeyword:androidNativeAndWebviewSwithContext")
def native_web_switch_context(ctx: ExecutionContext, swithoption: str = "NATIVE",
                              **_kw) -> None:
    mgr = get_manager(ctx)
    drv = mgr.driver()
    backend = ios_driver_backend(drv, mgr.backend)
    chosen = ios_switch_context(drv, backend, str(swithoption).strip())
    ctx.log(f"上下文切换为 {chosen}")


# noinspection PyShadowingBuiltins,PyProtectedMember
@keyword("mobile_browser_open", name="打开浏览器(wap)", category="Mobile",
         legacy_impl="MobileCommKeyword:openBrowser")
def browser_open(ctx: ExecutionContext, type: str = "Chrome", **_kw) -> None:
    _reject_ios_android_only(ctx, "mobile_browser_open")
    # 用 Appium 原生 browserName capability 起移动端浏览器会话（中性：由 Appium/uiautomator2
    # 侧管理 chromedriver，无需本工具本地部署 adb forward/chromedriver）。已有会话则复用。
    mgr = get_manager(ctx)
    if mgr.has_driver:
        ctx.log(f"浏览器会话已存在，类型 {type}")
        return
    browser = (type or "Chrome").strip() or "Chrome"
    device = _device_for_platform(ctx, "Android")
    # browserName 走会话 caps；不设 appPackage/appActivity（浏览器会话与被测 App 互斥）
    mgr.extra_caps = {**mgr.extra_caps, "browserName": browser}
    mgr.create("Android", "", "", device)
    ctx.log(f"已打开移动端浏览器会话: {browser}")


# noinspection PyProtectedMember
@keyword("mobile_browser_close", name="关闭浏览器(wap)", category="Mobile",
         legacy_impl="MobileCommKeyword:closeBrowser")
def browser_close(ctx: ExecutionContext, **_kw) -> None:
    _reject_ios_android_only(ctx, "mobile_browser_close")
    mgr = get_manager(ctx)
    drv = mgr.optional_driver()
    if drv is not None:
        drv.quit()
    mgr.release_driver()
    ctx.log("浏览器已关闭")


@keyword("mobile_browser_locate", name="浏览器地址输入(wap)", category="Mobile",
         legacy_impl="MobileCommKeyword:browserLocate")
def browser_locate(ctx: ExecutionContext, url: str = "", **_kw) -> None:
    _reject_ios_android_only(ctx, "mobile_browser_locate")
    drv = _drv(ctx)
    drv.get(url)
    ctx.log(f"浏览器打开地址: {url}")


# noinspection PyPep8Naming
@keyword("mobile_get_current_url", name="获取当前url(wap)", category="Mobile",
         out_params=["outVar"],
         legacy_impl="MobileCommKeyword:mobileGetCurrentUrl")
def get_current_url(ctx: ExecutionContext, outVar: str = "", **_kw) -> dict:
    mgr = get_manager(ctx)
    drv = mgr.driver()
    backend = ios_driver_backend(drv, mgr.backend)
    url = ios_get_current_url(drv, backend)
    ctx.log(f"当前url: {url}")
    return {outVar: url} if outVar else {}
