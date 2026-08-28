"""Appium 会话管理 + 元素定位（复用 Web 的 locator→By）。

appium 包懒加载：仅在创建真实会话时导入，缺失给出明确提示，
不影响导入本模块、注册关键字或在 FakeDriver 下测试。
"""

from __future__ import annotations

import logging
import os
import re
import time
from typing import Any
from urllib.parse import urlparse
from ...model.mapfile import Locator
from ...runtime.paths import join_project, to_native
from ..context import ExecutionContext
from ..registry import KeywordError, NotImplementedKeyword
from ..web.driver import locator_to_by  # 复用 Web 的 8 种 locator → By 映射
from .platform import is_ios, normalize_backend_mode, select_backend

logger = logging.getLogger("autopilot.appium")

DEFAULT_APPIUM_SERVER = "http://127.0.0.1:4723"

# KEEP_WDA 时跨用例复用（key = worker_slot:udid）
_KEEP_WDA_MANAGERS: dict[str, "AppiumManager"] = {}


def default_appium_factory(os_type: str, package: str, activity: str, server: str,
                           udid: str = "", extra_caps: dict | None = None):
    """创建真实 Appium WebDriver（懒加载 appium）。

    package/activity 为空时不强设（附着当前前台应用）；udid 指定目标设备（多设备/真机必需）；
    extra_caps 透传其它 desired capability（无 'appium:'/':' 前缀的自动补 'appium:'）。
    """

    logger.info("[Appium Create] os_type=%s package=%s activity=%s udid=%s extra_caps=%s",
                os_type, package, activity, udid, extra_caps)

    try:
        # noinspection PyUnresolvedReferences
        from appium import webdriver as appium_webdriver  # 延迟：可选 Appium extra
        # noinspection PyUnresolvedReferences
        from appium.options.android import UiAutomator2Options
        # noinspection PyUnresolvedReferences
        from appium.options.ios import XCUITestOptions
    except ImportError as e:  # pragma: no cover - 取决于环境
        raise KeywordError(
            "未安装 Appium-Python-Client，无法启动移动端会话。"
            "请 pip install Appium-Python-Client"
        ) from e

    if (os_type or "Android").lower().startswith("ios"):
        opts = XCUITestOptions()
        if package:
            opts.bundle_id = package
        # 可选：Windows 无 Mac 经 go-ios + pymobiledevice3 直连预装 WDA
        # 置环境变量 IOS_USE_GOIOS=1 时，合入 webDriverAgentUrl caps（勿 usePreinstalledWDA）
        if os.getenv("IOS_USE_GOIOS") and udid:
            from ...mobile.ios_bootstrap import build_ios_caps, DEFAULT_WDA_PORT
            if extra_caps and extra_caps.get("wdaLocalPort"):
                port = int(extra_caps["wdaLocalPort"])
            else:
                port = int(os.getenv("IOS_WDA_LOCAL_PORT", str(DEFAULT_WDA_PORT)))
            extra_caps = {**build_ios_caps(udid, port), **(extra_caps or {})}
    else:
        opts = UiAutomator2Options()
        if package:
            opts.app_package = package
        if activity:
            opts.app_activity = activity
    if udid:
        opts.udid = udid
    opts.new_command_timeout = 120
    for k, v in (extra_caps or {}).items():
        key = k if (":" in k) else f"appium:{k}"
        opts.set_capability(key, v)
    return appium_webdriver.Remote(server, options=opts)


class AppiumManager:
    def __init__(self) -> None:
        self._driver = None
        self.server = DEFAULT_APPIUM_SERVER
        self.server_running = False
        self._server_mgr = None
        self.extra_caps: dict = {}   # 透传给会话的额外 desired capabilities
        self.driver_factory = default_appium_factory
        self._ios_prep = None        # iOS 直连 WDA 时的设备准备器（go-ios 隧道等）
        self.cancel_event = None     # 可选 threading.Event；检视/镜像取消时协作中断 prepare
        self._wda_udid = ""          # 当前 WDA 会话所属设备 udid
        self._wda_port = 0           # 当前 WDA 本机转发端口（0=未设，用默认）
        self._tunnel_port = 0
        self._mjpeg_port = 0
        self.platform = ""           # 当前会话平台 "android"/"ios"
        self.backend = ""
        self.backend_mode = "auto"

    @property
    def mjpeg_port(self) -> int:
        """本机 MJPEG 转发端口（0 表示使用默认）。"""
        return self._mjpeg_port

    @property
    def has_driver(self) -> bool:
        return self._driver is not None

    def optional_driver(self):
        """返回当前 driver，无会话时为 None（不抛 KeywordError）。"""
        return self._driver

    def release_driver(self) -> None:
        """仅释放 driver 引用（外部已 quit 时用）。"""
        self._driver = None

    def start_server(self) -> None:
        parsed = urlparse(self.server or DEFAULT_APPIUM_SERVER)
        host = (parsed.hostname or "").lower()
        port = parsed.port or 4723
        if host not in ("127.0.0.1", "localhost", ""):
            self.server_running = True
            return
        from .appium_server import acquire_local_appium
        try:
            self._server_mgr = acquire_local_appium(host or "127.0.0.1", port)
        except RuntimeError as e:
            raise KeywordError(str(e))
        self.server_running = True

    def stop_server(self) -> None:
        parsed = urlparse(self.server or DEFAULT_APPIUM_SERVER)
        host = (parsed.hostname or "").lower()
        port = parsed.port or 4723
        if host in ("127.0.0.1", "localhost", ""):
            from .appium_server import stop_local_appium
            stop_local_appium(host or "127.0.0.1", port)
        elif self._server_mgr is not None:
            self._server_mgr.stop()
        self._server_mgr = None
        self.server_running = False

    def _local_server_manager(self):
        parsed = urlparse(self.server or DEFAULT_APPIUM_SERVER)
        host = (parsed.hostname or "").lower()
        port = parsed.port or 4723
        if host not in ("127.0.0.1", "localhost"):
            return None
        if self._server_mgr is None or self._server_mgr.host != host or self._server_mgr.port != port:
            from .appium_server import AppiumServer
            self._server_mgr = AppiumServer(host=host, port=port)
        return self._server_mgr

    def create(self, os_type: str, package: str, activity: str, udid: str = "") -> Any:
        """按「目标平台 × 宿主系统」分支选后端：

        - Android（全平台）/ iOS@Mac → Appium；
        - iOS@Windows/Linux → 直连 WDA（go-ios 隧道/runwda + pymobiledevice3 转发）。
        """
        self.platform = "ios" if is_ios(os_type) else "android"   # 供对象库按平台解析定位符
        self.backend = select_backend(os_type, mode=self.backend_mode)
        if self.backend == "wda":
            self._driver = self._create_wda_driver(package, udid)
        else:
            if self.platform == "ios":
                self._ensure_ios_external_wda(udid)
            self._driver = self.driver_factory(os_type, package, activity, self.server,
                                               udid, self._session_caps())
        return self._driver

    def _ensure_ios_external_wda(self, udid: str) -> None:
        """Mac iOS Appium 非 managed 路径：go-ios 准备 WDA + 合入 webDriverAgentUrl caps。"""
        from ...mobile import ios_bootstrap as ib
        from ...mobile.ios_mirror import capture_active
        # 批跑 KEEP_WDA 时禁止因镜像采集强制重建隧道
        keep = (
            os.getenv("AUTOPILOT_INTENT_KEEP_WDA") or os.getenv("IOS_KEEP_WDA") or ""
        ).strip().lower() in ("1", "true", "yes", "on")
        force_rebuild = bool(capture_active()) and not keep
        if ib.prefer_appium_managed(udid):
            return
        port = self._wda_port or ib.DEFAULT_WDA_PORT
        tunnel_port = self._tunnel_port or ib.DEFAULT_TUNNEL_INFO_PORT
        mjpeg_port = self._mjpeg_port or ib.DEFAULT_MJPEG_PORT
        wda_bundle = (self.extra_caps.get("wdaBundleId")
                      or self.extra_caps.get("updatedWDABundleId") or "")
        if not (self.extra_caps.get("webDriverAgentUrl")
                or self.extra_caps.get("appium:webDriverAgentUrl")):
            self.extra_caps.update(
                ib.build_ios_caps(udid, port, extra=dict(self.extra_caps)))
        same_device = (not udid) or (udid == self._wda_udid and port == self._wda_port)
        if ib.wda_alive(port) and same_device and not force_rebuild:
            ib.ensure_mjpeg_ready(udid, mjpeg_port, prep=self._ios_prep)
            return
        for stale in (port, mjpeg_port):
            if ib.is_port_listening(stale):
                ib.kill_listeners(stale, tool_only=True)
        if self._ios_prep is not None:
            self._ios_prep.stop()
            self._ios_prep = None
        # noinspection PyBroadException
        try:
            self._ios_prep = ib.IosDevicePrep(
                udid,
                wda_bundle,
                info_port=tunnel_port,
                wda_port=port,
                mjpeg_port=mjpeg_port,
                cancel_event=self.cancel_event,
            )
            self._ios_prep.prepare(force_tunnel_rebuild=force_rebuild)
            self._wda_udid = udid
            self._wda_port = port
        except ib.PrepCancelled as e:
            raise KeywordError(str(e))
        except RuntimeError as e:
            raise KeywordError(str(e))

    def _session_caps(self) -> dict:
        """组装本次会话 caps：extra_caps 为基础；Android 且开启 Unicode 输入开关时，
        自动并入 Appium 原生 unicodeKeyboard/resetKeyboard（显式已设则不覆盖）。"""
        caps = dict(self.extra_caps)
        if self._wda_port:
            caps.setdefault("wdaLocalPort", self._wda_port)
        if self.platform == "android" and "unicodeKeyboard" not in caps:
            # noinspection PyBroadException
            try:
                from ...runtime import settings
                if settings.mobile_unicode_keyboard():
                    caps["unicodeKeyboard"] = True
                    caps["resetKeyboard"] = True
            except Exception:
                pass
        return caps

    def _create_wda_driver(self, bundle_id: str, udid: str):
        """iOS 直连 WDA：准备设备到 WDA 可达，再建 WDA session 并适配成 driver。"""
        from .wda_client import WdaClient, WdaDriver
        from ...mobile import ios_bootstrap as ib
        from ...mobile.ios_mirror import capture_active
        keep = (
            os.getenv("AUTOPILOT_INTENT_KEEP_WDA") or os.getenv("IOS_KEEP_WDA") or ""
        ).strip().lower() in ("1", "true", "yes", "on")
        force_rebuild = bool(capture_active()) and not keep
        wda_bundle = self.extra_caps.get("wdaBundleId") or self.extra_caps.get(
            "updatedWDABundleId") or ""
        wda_port = self._wda_port or ib.DEFAULT_WDA_PORT
        tunnel_port = self._tunnel_port or ib.DEFAULT_TUNNEL_INFO_PORT
        mjpeg_port = self._mjpeg_port or ib.DEFAULT_MJPEG_PORT
        wda_url = f"http://127.0.0.1:{wda_port}"
        same_device = (not udid) or (udid == self._wda_udid and wda_port == self._wda_port)
        if not (ib.wda_alive(wda_port) and same_device and not force_rebuild):
            for stale in (wda_port, mjpeg_port):
                if ib.is_port_listening(stale):
                    ib.kill_listeners(stale, tool_only=True)
            if self._ios_prep is not None:
                self._ios_prep.stop()
                self._ios_prep = None
            # noinspection PyBroadException
            try:
                self._ios_prep = ib.IosDevicePrep(
                    udid,
                    wda_bundle,
                    info_port=tunnel_port,
                    wda_port=wda_port,
                    mjpeg_port=mjpeg_port,
                    cancel_event=self.cancel_event,
                )
                wda_url = self._ios_prep.prepare(force_tunnel_rebuild=force_rebuild)
                self._wda_udid = udid
                self._wda_port = wda_port
            except ib.PrepCancelled as e:
                raise KeywordError(str(e))
            except RuntimeError as e:
                raise KeywordError(str(e))
        else:
            ib.ensure_mjpeg_ready(udid, mjpeg_port, prep=self._ios_prep)
        client = WdaClient(wda_url)
        # 会话不绑 bundleId（与控件检视器一致）：查询树含系统 Alert。
        # 再 launch 被测 App。若把 bundleId 写进 session caps，XCUITest 作用域锁在
        # App 内，SpringBoard 权限弹窗（WLAN & Cellular 等）检视器可见、用例不可点。
        client.create_session(bundle_id="")
        if bundle_id:
            # 冷启动：先 terminate 再 launch，避免 Preferences 等系统 App
            # 从上次子页（如 WLAN 详情）恢复导致首页控件找不到。
            # noinspection PyBroadException
            try:
                client.terminate_app(bundle_id)
            except Exception:
                pass
            # noinspection PyBroadException
            try:
                client.launch_app(bundle_id)
            except Exception:
                client.activate_app(bundle_id)

        def _recover_wda_session() -> None:
            client.recreate_session()
            if bundle_id:
                # noinspection PyBroadException
                try:
                    client.terminate_app(bundle_id)
                except Exception:
                    pass
                # noinspection PyBroadException
                try:
                    client.launch_app(bundle_id)
                except Exception:
                    client.activate_app(bundle_id)

        client.set_recover(_recover_wda_session)
        return WdaDriver(client, bundle_id=bundle_id)

    def driver(self) -> Any:
        if self._driver is None:
            raise KeywordError("移动端会话未创建，请先执行“启动App”(mobile_app_start)")
        return self._driver

    def close(self) -> None:
        if self._driver is not None:
            # noinspection PyBroadException
            try:
                self._driver.quit()
            except Exception:
                pass
            self._driver = None
        # 批跑/命中率：保留隧道与 WDA，避免每条用例重跑 prepare
        keep = (os.getenv("AUTOPILOT_INTENT_KEEP_WDA") or os.getenv("IOS_KEEP_WDA") or "").strip().lower()
        if keep in ("1", "true", "yes", "on"):
            self.backend = ""
            return
        # 非 keep：从复用表移除本实例
        for key, cached in list(_KEEP_WDA_MANAGERS.items()):
            if cached is self:
                _KEEP_WDA_MANAGERS.pop(key, None)
        if self._ios_prep is not None:
            self._ios_prep.stop()
            self._ios_prep = None
        self._wda_udid = ""
        self._wda_port = 0
        self.backend = ""


def ios_session_probe(mgr: AppiumManager) -> bool:
    """探测 iOS 会话是否仍可用（避免 driver 引用在但 Appium session 已失效）。"""
    drv = mgr.optional_driver()
    if drv is None:
        return False
    # noinspection PyBroadException
    try:
        drv.get_window_size()
        return True
    except Exception:
        # 仅清 driver 引用，不 stop WDA/MJPEG（画面可继续走 9100）
        # noinspection PyBroadException
        try:
            drv.quit()
        except Exception:
            pass
        mgr.release_driver()
        return False


def _sync_manager_ports(mgr: AppiumManager, ctx: ExecutionContext) -> None:
    """从 ctx 同步并行会话端口（未设则保持 manager 默认/0）。"""
    for attr, key, cast in (
        ("_wda_port", "__wda_local_port__", int),
        ("_tunnel_port", "__tunnel_info_port__", int),
        ("_mjpeg_port", "__mjpeg_local_port__", int),
    ):
        raw = ctx.get_var(key)
        if raw not in (None, ""):
            try:
                setattr(mgr, attr, cast(raw))
            except (TypeError, ValueError):
                pass
    server = ctx.get_var("__appium_server__")
    if server:
        mgr.server = str(server)
    caps = ctx.get_var("__appium_caps__")
    if isinstance(caps, dict):
        mgr.extra_caps.update(caps)
    backend_mode = ctx.get_var("__mobile_backend_mode__") or ctx.get_var("__ios_backend_mode__")
    if backend_mode not in (None, ""):
        mgr.backend_mode = normalize_backend_mode(str(backend_mode))


def get_manager(ctx: ExecutionContext) -> AppiumManager:
    mgr = getattr(ctx, "appium", None)
    if mgr is None:
        keep = (
            os.getenv("AUTOPILOT_INTENT_KEEP_WDA") or os.getenv("IOS_KEEP_WDA") or ""
        ).strip().lower() in ("1", "true", "yes", "on")
        if keep:
            # 批跑每用例新建 ctx；按 slot+udid 复用 manager，否则 KEEP_WDA 名存实亡
            slot = str(ctx.get_var("__worker_slot__") if ctx.get_var("__worker_slot__") not in (None, "") else "0")
            udid = str(ctx.get_var("__device_udid__") or "").strip()
            key = f"{slot}:{udid}"
            cached = _KEEP_WDA_MANAGERS.get(key)
            if cached is not None:
                mgr = cached
            else:
                mgr = AppiumManager()
                _KEEP_WDA_MANAGERS[key] = mgr
        else:
            mgr = AppiumManager()
        ctx.appium = mgr  # type: ignore[attr-defined]
    _sync_manager_ports(mgr, ctx)
    # get_var 默认返回 ""；未注入检视取消事件时不得当成 Event
    cancel = ctx.get_var("__inspect_cancel_event__", None)
    if cancel is not None and hasattr(cancel, "is_set"):
        mgr.cancel_event = cancel
        prep = getattr(mgr, "_ios_prep", None)
        if prep is not None:
            prep.cancel_event = cancel
    return mgr


def _ensure_wda_session(mgr: AppiumManager) -> None:
    """WDA-direct：定位/截图前探活 session，失效则 recover。"""
    if getattr(mgr, "backend", "") != "wda":
        return
    drv = mgr.optional_driver()
    if drv is None:
        return
    client = getattr(drv, "wda_client", None)
    if client is None:
        return
    from ...mobile.ios.health import ensure_wda_session
    bundle_id = getattr(drv, "bundle_id", "") or ""
    ensure_wda_session(client, bundle_id=bundle_id)


def _resolve_image(ctx: ExecutionContext, image_path: str) -> str:
    """解析模板图路径：接受用例中的 ``/`` 或 ``\\``，相对工程根拼接。"""
    raw = to_native(image_path)
    if os.path.isabs(raw) and os.path.exists(raw):
        return raw
    base = ctx.get_var("__project_path__") or os.getcwd()
    cand = join_project(str(base), raw)
    return cand if os.path.exists(cand) else raw


def screen_locate(ctx: ExecutionContext, image_path: str, threshold: float = 0.8):
    """移动端截屏 + opencv 模板匹配。返回 tap 用的逻辑坐标 (x,y)，未命中 None。

    image_path 可来自 'picture::名' 中的名（调用方先剥前缀）或直接路径。
    截图分辨率可能 ≠ 设备逻辑分辨率，按 window_size 换算。
    """
    from ..image_match import find_template, png_size

    mgr = get_manager(ctx)
    _ensure_wda_session(mgr)
    drv = mgr.driver()
    png = drv.get_screenshot_as_png()
    name = image_path.split("picture::")[-1] if "picture::" in image_path else image_path
    m = find_template(png, _resolve_image(ctx, name), threshold=threshold)
    if m is None:
        return None
    sw, sh = png_size(png)
    # noinspection PyBroadException
    try:
        size = drv.get_window_size()
        sx, sy = size["width"] / sw, size["height"] / sh
    except Exception:
        sx = sy = 1.0
    return m.cx * sx, m.cy * sy


def tap_xy(ctx: ExecutionContext, x: float, y: float) -> None:
    get_manager(ctx).driver().tap([(int(x), int(y))])


DEFAULT_ELEMENT_WAIT_MS = 30000    # 元素等待上限默认值（对齐参考实现 MaxWaitTime）


def _to_wait_ms(timeout) -> int:
    """把步骤传入的 timeout(可能是 ''/None/字符串) 归一成毫秒；非法/空用默认值。"""
    if timeout in (None, ""):
        return DEFAULT_ELEMENT_WAIT_MS
    try:
        return max(int(float(str(timeout))), 0)
    except (TypeError, ValueError):
        return DEFAULT_ELEMENT_WAIT_MS


def _predicate_eq(attr: str, value: str) -> str:
    """iOS NSPredicate 片段：label == \"…\"（供 predicate:: 与自动回退）。"""
    from ...mobile.ios_strategies import predicate_eq
    return predicate_eq(attr, value)


def _locator_xpath_value(locator) -> str:
    if isinstance(locator, str):
        if locator.startswith("xpath::"):
            return locator.split("::", 1)[1]
        return locator
    if hasattr(locator, "type") and getattr(locator, "type", "") == "XPATH":
        return str(getattr(locator, "value", "") or "")
    if hasattr(locator, "type") and getattr(locator, "type", "") == "PREDICATE":
        return str(getattr(locator, "value", "") or "")
    return ""


def locator_xpath_value(locator) -> str:
    """定位符原始 xpath/predicate 字符串（供 iOS Alert 等组件层使用）。"""
    return _locator_xpath_value(locator)


def extract_ios_button_label(locator) -> str:
    """从定位符提取 iOS 按钮文案（label/name/value），供 WDA /alert/accept。"""
    raw = _locator_xpath_value(locator)
    if not raw:
        return ""
    for pat in (
        r'label\s*==\s*"([^"]+)"',
        r"label\s*==\s*'([^']+)'",
        r'value\s*==\s*"([^"]+)"',
        r"value\s*==\s*'([^']+)'",
        r'name\s*==\s*"([^"]+)"',
        r"name\s*==\s*'([^']+)'",
    ):
        m = re.search(pat, raw)
        if m:
            return m.group(1)
    for attr in ("label", "name", "value"):
        m = re.search(rf"@{attr}=([\"'])(.+?)\1", raw)
        if m:
            return m.group(2)
    return ""


def _decode_xml_entities(s: str) -> str:
    return (s.replace("&amp;", "&").replace("&quot;", '"')
            .replace("&lt;", "<").replace("&gt;", ">"))


def _ios_alert_button_labels(client) -> list[str]:
    """从 page_source 取 Alert 内按钮 label（真机 WLAN 弹窗为 WLAN &amp; Cellular 等）。"""
    from ...mobile.ios.alert.wda_adapter import alert_button_labels
    return alert_button_labels(client)


def _alert_still_open(client) -> bool:
    from ...mobile.ios.alert.wda_adapter import alert_is_open
    return alert_is_open(client)


def ios_alert_locator_hint(locator) -> bool:
    """定位符是否像 iOS 系统 Alert 按钮（应优先走 /alert/accept，勿先空转 find）。"""
    if extract_ios_button_label(locator):
        return True
    raw = _locator_xpath_value(locator)
    if not raw:
        return False
    if "XCUIElementTypeAlert" in raw:
        return True
    if re.search(r"XCUIElementTypeButton\[\d+]", raw):
        return True
    return bool(re.search(r"(?:label|name)\s*==", raw))


def ios_alert_strong_hint(locator) -> bool:
    """强 Alert 语义：应长时间轮询等弹窗（predicate / Alert 树 / 按钮序号），而非 App 内普通按钮。"""
    if hasattr(locator, "type") and getattr(locator, "type", "") == "PREDICATE":
        return True
    if isinstance(locator, str) and locator.strip().lower().startswith("predicate::"):
        return True
    raw = _locator_xpath_value(locator)
    if not raw:
        return False
    if "XCUIElementTypeAlert" in raw or re.search(r"XCUIElementTypeButton\[\d+]", raw):
        return True
    if re.search(r"(?:label|name)\s*==", raw):
        return True
    return False


def _ios_wda_client_from_driver(drv) -> Any | None:
    """从 WdaDriver（或兼容包装）取 WdaClient。"""
    client = getattr(drv, "wda_client", None)
    if client is not None:
        return client
    return getattr(drv, "_c", None)


def mirror_control_sink(_mgr: "AppiumManager", _drv: Any) -> Any | None:
    """Console Runner 无 IDE 镜像检视；保留 API，恒返回 None。"""
    return None


def ios_alert_wait_budget_ms(locator, total_ms: int) -> int:
    """Alert 轮询预算：强 hint 用满 timeout；弱 hint（如 @name='Allow'）最多 2s，留时间给 find。"""
    total_ms = max(0, int(total_ms))
    if ios_alert_strong_hint(locator):
        return total_ms
    return min(total_ms, 2000)


def try_ios_alert_click(ctx: ExecutionContext, locator, timeout_ms: int,
                        *, wait_for_alert: bool | None = None) -> bool:
    """iOS 系统 Alert：仅用 WDA POST /alert/accept（真机实测 xpath/link text 均无效）。

    前置条件：session 不得绑 bundleId，否则 Alert 不在 page_source（实测结论）。

    wait_for_alert：True 时在 timeout 内轮询等待弹窗出现；None 时按 ios_alert_locator_hint 推断。
    """
    from ...mobile.ios.alert import try_ios_alert_click as _handle_click
    return _handle_click(ctx, locator, timeout_ms, wait_for_alert=wait_for_alert)


def _mobile_locator_to_by(loc: Locator) -> tuple[str, str]:
    if loc.type == "PREDICATE":
        return "-ios predicate string", loc.value
    if loc.type in ("CLASS_CHAIN", "CLASS-CHAIN"):
        return "-ios class chain", loc.value
    if loc.type == "TEXT" and "=" in (loc.value or ""):
        return "link text", loc.value
    return locator_to_by(loc)


def _ios_find_strategies(loc: Locator, backend: str = "") -> list[tuple[str, str]]:
    """iOS 定位策略（对齐 WDA Queries / 旧版 NameLocator→xpath @name）。"""
    from ...mobile.ios_strategies import (
        attr_find_strategies, dedupe_strategies, text_find_strategies, use_wda_order,
    )

    primary = _mobile_locator_to_by(loc)
    wda = use_wda_order(backend)
    extras: list = []

    if loc.type == "NAME" and loc.value:
        extras = text_find_strategies(loc.value, wda_first=wda)
    elif loc.type == "XPATH" and loc.value:
        for attr in ("name", "label", "value"):
            m = re.search(rf"@{attr}=([\"'])(.+?)\1", loc.value)
            if m:
                extras.extend(text_find_strategies(m.group(2), wda_first=wda))
    elif loc.type == "PREDICATE" and loc.value:
        m = re.search(r'(label|name)\s*==\s*"([^"]+)"', loc.value)
        if not m:
            m = re.search(r"(label|name)\s*==\s*'([^']+)'", loc.value)
        if m:
            extras = attr_find_strategies(m.group(1), m.group(2), wda_first=wda)

    out: list[tuple[str, str]] = [primary]
    seen = {primary}
    for s in dedupe_strategies(extras):
        key = (s.by, s.value)
        if key not in seen:
            seen.add(key)
            out.append(key)
    return out


def _find_strategies(loc: Locator, platform: str, backend: str = "") -> list[tuple[str, str]]:
    plat = (platform or "").lower()
    if plat == "ios":
        return _ios_find_strategies(loc, backend)
    return [_mobile_locator_to_by(loc)]


def find_element(ctx: ExecutionContext, locator, timeout=None):
    """定位元素，带显式等待：在 timeout(ms) 内轮询直到找到再返回，超时抛原生异常。

    移动端 UI 异步渲染，元素常晚出现——不等待会瞬间失败(flaky)。找到即刻返回，
    timeout 只是上限（默认 30s）。Android(Appium)/iOS(WDA) 的 find_element 均适用。
    """
    if isinstance(locator, str):
        if "picture::" in locator:
            raise NotImplementedKeyword(
                "picture:: 不返回元素，请用图像点击/校验分支（screen_locate）")
        loc = Locator(type="XPATH", value=locator)
    else:
        loc = locator
    if not isinstance(loc, Locator):
        raise KeywordError(f"无效的元素定位: {locator!r}")
    mgr = get_manager(ctx)
    _ensure_wda_session(mgr)
    drv = mgr.driver()
    strategies = _find_strategies(loc, mgr.platform, mgr.backend)
    wait_ms = _to_wait_ms(timeout)

    def _fail(exc: Exception | None):
        detail = f"{exc}" if exc else ""
        backend_hint = f" [{mgr.platform}/{mgr.backend or 'appium'}]" if mgr.platform else ""
        if backend_hint:
            detail = f"{backend_hint}{detail}"
        raise KeywordError(
            f"未找到元素: {locator!r}"
            + (f"（已尝试 {len(strategies)} 种策略）{detail}" if detail else "")
        ) from exc

    if wait_ms <= 0:
        last_err: Exception | None = None
        for by, value in strategies:
            # noinspection PyBroadException
            try:
                return drv.find_element(by, value)
            except Exception as e:
                last_err = e
        _fail(last_err)
    deadline = time.monotonic() + wait_ms / 1000.0
    last_err = None
    while True:
        for by, value in strategies:
            # noinspection PyBroadException
            try:
                return drv.find_element(by, value)
            except Exception as e:
                last_err = e
        if time.monotonic() >= deadline:
            _fail(last_err)
        time.sleep(0.3)
