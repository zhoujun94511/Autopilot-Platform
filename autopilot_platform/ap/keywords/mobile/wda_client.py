"""直连 WebDriverAgent 的 iOS 后端（Windows/Linux 上 Appium xcuitest 不可用时使用）。

WDA 本身是 WebDriver 风格的 HTTP 服务；本模块用 httpx 直接讲它的 JSONWire 协议，
并用 WdaDriver 适配出 mobile 关键字所需的「Appium driver」子集接口
（find_element/click/send_keys/text/screenshot/window_size/tap/back/source 等），
从而绕开 Appium 的 iOS17+ RemoteXPC 隧道（该层不支持 Windows）。
"""

from __future__ import annotations

import base64
from typing import Any, Callable, Optional

from ..registry import KeywordError
from ...mobile.ios.session_recovery import SessionRecovery, is_session_lost_error

# Selenium/Appium By → WDA "using"（见 WDA Queries wiki）
# link text 的 value 形如 "label=文案" / "name=文案"，是查 label 的官方方式。
_BY_TO_USING = {
    "id": "name",                 # iOS 无独立 id，用 name
    "name": "name",
    "accessibility id": "accessibility id",
    "xpath": "xpath",
    "class name": "class name",
    "-ios class chain": "class chain",
    "-ios predicate string": "predicate string",
    "predicate string": "predicate string",
    "link text": "link text",
    "partial link text": "partial link text",
}


def _using(by: str) -> str:
    return _BY_TO_USING.get(str(by).lower(), "xpath")


# noinspection PyProtectedMember
class WdaElement:
    """WDA 元素句柄，暴露 mobile 关键字常用的元素方法（与 WdaClient 同模块、有意紧耦合）。"""

    def __init__(self, client: "WdaClient", element_id: str) -> None:
        self._c = client
        self.id = element_id

    def click(self) -> None:
        self._c._post(f"/element/{self.id}/click", {})

    def send_keys(self, text: str) -> None:
        self._c._post(f"/element/{self.id}/value", {"value": list(str(text))})

    def clear(self) -> None:
        self._c._post(f"/element/{self.id}/clear", {})

    @property
    def text(self) -> str:
        return str(self._c._get(f"/element/{self.id}/text") or "")

    def is_displayed(self) -> bool:
        return bool(self._c._get(f"/element/{self.id}/displayed"))

    def is_enabled(self) -> bool:
        return bool(self._c._get(f"/element/{self.id}/enabled"))

    def is_selected(self) -> bool:
        return bool(self._c._get(f"/element/{self.id}/selected"))

    def get_attribute(self, name: str) -> str:
        return str(self._c._get(f"/element/{self.id}/attribute/{name}") or "")

    def scroll_into_view(self) -> None:
        """滚动使元素进入可视区域（WDA /element/{id}/scroll）。"""
        # noinspection PyBroadException
        try:
            self._c._post(f"/element/{self.id}/scroll", {"toVisible": True})
            return
        except Exception:
            pass
        self._c._post(f"/element/{self.id}/scroll", {"direction": "down"})

    @property
    def rect(self) -> dict:
        """元素位置+尺寸 {x,y,width,height}（WDA /element/{id}/rect）——
        供偏移点击/长按等按 rect 算坐标的关键字使用。"""
        r = self._c._get(f"/element/{self.id}/rect") or {}
        return {"x": int(r.get("x", 0)), "y": int(r.get("y", 0)),
                "width": int(r.get("width", 0)), "height": int(r.get("height", 0))}

    @property
    def location(self) -> dict:
        r = self.rect
        return {"x": r["x"], "y": r["y"]}

    @property
    def size(self) -> dict:
        r = self.rect
        return {"width": r["width"], "height": r["height"]}


class WdaClient:
    """WebDriverAgent HTTP 客户端（管理 session + 元素/手势/截图）。"""

    def __init__(self, base_url: str, timeout: float = 60.0) -> None:
        # noinspection PyUnresolvedReferences
        import httpx
        self.base_url = base_url.rstrip("/")
        self._http = httpx.Client(base_url=self.base_url, timeout=timeout)
        self.session_id: Optional[str] = None
        self._recovery = SessionRecovery()
        self._session_caps: dict = {}

    def set_recover(self, fn: Callable[[], None]) -> None:
        self._recovery.recover = fn

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: Optional[dict] = None,
        retry: bool = True,
        timeout: Optional[float] = None,
        rooted: bool = False,
    ) -> Any:
        sp = path if rooted else self._sp(path)
        extra: dict[str, Any] = {}
        if timeout is not None:
            extra["timeout"] = timeout
        try:
            if method == "GET":
                resp = self._http.get(sp, **extra)
            elif method == "POST":
                resp = self._http.post(sp, json=json_body or {}, **extra)
            elif method == "DELETE":
                resp = self._http.delete(sp, **extra)
            else:
                raise KeywordError(f"WDA 不支持 HTTP 方法: {method}")
            return self._unwrap(resp)
        except KeywordError as e:
            if retry and self._recovery.maybe_recover(e):
                return self._request(
                    method,
                    path,
                    json_body=json_body,
                    retry=False,
                    timeout=timeout,
                    rooted=rooted,
                )
            raise

    # ---- 低层 ----
    @staticmethod
    def _unwrap(resp) -> Any:
        data = resp.json()
        if isinstance(data, dict) and "value" in data:
            val = data["value"]
            if isinstance(val, dict) and val.get("error"):
                msg = f"{val.get('error')}: {val.get('message', '')}"
                if is_session_lost_error(msg):
                    raise KeywordError(f"WDA session 失效: {msg}")
                raise KeywordError(f"WDA 错误: {msg}")
            return val
        if resp.status_code == 404 and is_session_lost_error(str(data)):
            raise KeywordError("WDA session 失效: invalid session id")
        return data

    def _post(self, path: str, body: dict, timeout: Optional[float] = None) -> Any:
        return self._request("POST", path, json_body=body, timeout=timeout)

    def _get(self, path: str) -> Any:
        return self._request("GET", path)

    def _sp(self, path: str) -> str:
        """带 session 前缀的路径（/status、/session 等顶层路径不加前缀）。"""
        if path.startswith("/session") or path in ("/status",) or self.session_id is None:
            return path
        return f"/session/{self.session_id}{path}"

    # ---- 会话 ----
    def status(self) -> dict:
        return self._get("/status")

    def create_session(self, bundle_id: str = "", caps: Optional[dict] = None) -> str:
        """创建 WDA session。

        注意：不要把被测 App 的 bundleId 写进 session caps。
        绑了 bundleId 后 XCUITest 查询作用域落在该 App，系统权限 Alert（SpringBoard）
        常不在可查层级——控件检视器能看到、用例里找不到，根因在此。
        应 create_session() 后用 launch_app/activate_app 拉起被测 App（与检视器一致）。
        """
        cap: dict = {}
        # 仅当调用方显式要求时才写入 bundleId（兼容旧路径/测试）
        if bundle_id:
            cap["bundleId"] = bundle_id
        if caps:
            cap.update(caps)
        self._session_caps = dict(cap)
        # WDA 接受 capabilities.alwaysMatch + 兼容旧 desiredCapabilities
        val = self._post("/session", {
            "capabilities": {"alwaysMatch": cap},
            "desiredCapabilities": cap,
        })
        self.session_id = val.get("sessionId") if isinstance(val, dict) else None
        if not self.session_id and isinstance(val, dict):
            self.session_id = (val.get("session_id")
                               or (val.get("value") or {}).get("sessionId"))
        if not self.session_id:
            raise KeywordError("WDA 创建 session 失败（无 sessionId）")
        return self.session_id

    def launch_app(self, bundle_id: str, arguments: Optional[list] = None,
                   environment: Optional[dict] = None) -> None:
        """启动被测 App（session 已建立、未绑 bundleId 时用）。"""
        if not bundle_id:
            return
        body: dict = {"bundleId": bundle_id}
        if arguments is not None:
            body["arguments"] = arguments
        if environment is not None:
            body["environment"] = environment
        self._post("/wda/apps/launch", body)

    def activate_app(self, bundle_id: str) -> None:
        """将已安装 App 置于前台。"""
        if not bundle_id:
            return
        self._post("/wda/apps/activate", {"bundleId": bundle_id})

    def terminate_app(self, bundle_id: str) -> None:
        """终止 App 进程。"""
        if not bundle_id:
            return
        self._post("/wda/apps/terminate", {"bundleId": bundle_id})

    def app_state(self, bundle_id: str) -> int:
        """App 状态：1 未运行 / 2 后台 / 4 前台（WDA 约定）。"""
        if not bundle_id:
            return 0
        val = self._post("/wda/apps/state", {"bundleId": bundle_id})
        try:
            return int(val)
        except (TypeError, ValueError):
            return 0

    def is_app_installed(self, bundle_id: str) -> bool:
        """WDA 查询 bundle 是否已安装（state 调用成功即视为已安装）。"""
        if not bundle_id:
            return False
        # noinspection PyBroadException
        try:
            return self.app_state(bundle_id) >= 1
        except Exception:
            return False

    def list_contexts(self) -> list[str]:
        val = self._get("/contexts") or []
        return [str(c) for c in val]

    def get_context(self) -> str:
        return str(self._get("/context") or "")

    def set_context(self, name: str) -> None:
        self._post("/context", {"name": name})

    def dismiss_keyboard(self) -> None:
        # noinspection PyBroadException
        try:
            self._post("/wda/keyboard/dismiss", {})
        except Exception:
            pass

    def execute_script(self, script: str, args: Optional[list] = None) -> Any:
        """WebDriver execute/sync（WebView JS 等）。"""
        payload_args: list = []
        for item in args or []:
            if hasattr(item, "id"):
                payload_args.append({"ELEMENT": item.id})
            else:
                payload_args.append(item)
        return self._post("/execute/sync", {"script": script, "args": payload_args})

    def alert_text(self) -> str:
        return str(self._get("/alert/text") or "")

    def alert_accept(self, button_label: str = "") -> None:
        """点系统/App Alert 按钮；button_label 非空时点指定文案按钮。"""
        body: dict = {}
        if button_label:
            body["name"] = button_label
        self._post("/alert/accept", body)

    def alert_dismiss(self, button_label: str = "") -> None:
        body: dict = {}
        if button_label:
            body["name"] = button_label
        self._post("/alert/dismiss", body)

    def alert_buttons(self) -> list:
        """当前系统弹窗按钮文案；无弹窗时返回空列表。"""
        try:
            val = self._get("/alert/buttons")
        except KeywordError:
            return []
        if isinstance(val, list):
            return [str(item) for item in val]
        return []

    def delete_session(self) -> None:
        if self.session_id:
            # noinspection PyBroadException
            try:
                self._request("DELETE", f"/session/{self.session_id}", retry=False)
            except Exception:
                pass
            self.session_id = None

    def recreate_session(self) -> str:
        """按上次 caps 重建 session（session 失效恢复用）。"""
        self.session_id = None
        return self.create_session(caps=self._session_caps)

    def update_settings(self, settings: dict) -> None:
        """POST WDA /appium/settings（调 MJPEG 帧率、关闭 idle 等待等）。

        Best-effort：失败不抛，由调用方决定是否忽略。
        """
        body = {"settings": dict(settings or {})}
        self._post("/appium/settings", body)

    # ---- 元素 / 手势 / 截图 ----
    def find_element(self, by: str, value: str) -> WdaElement:
        val = self._post("/element", {"using": _using(by), "value": value})
        eid = val.get("ELEMENT") or val.get("element-6066-11e4-a52e-4f735466cecf")
        if not eid:
            raise KeywordError(f"WDA 未找到元素: {by}={value}")
        return WdaElement(self, eid)

    def find_elements(self, by: str, value: str) -> list:
        val = self._post("/elements", {"using": _using(by), "value": value}) or []
        out = []
        for it in val:
            eid = it.get("ELEMENT") or it.get("element-6066-11e4-a52e-4f735466cecf")
            if eid:
                out.append(WdaElement(self, eid))
        return out

    def screenshot_png(self) -> bytes:
        b64 = self._get("/screenshot")
        return base64.b64decode(b64) if b64 else b""

    def window_size(self) -> dict:
        return self._get("/window/size") or {"width": 0, "height": 0}

    def tap(self, x: int, y: int) -> None:
        # W3C actions：单指点击
        self._post("/actions", {"actions": [{
            "type": "pointer", "id": "finger1",
            "parameters": {"pointerType": "touch"},
            "actions": [
                {"type": "pointerMove", "duration": 0, "x": int(x), "y": int(y)},
                {"type": "pointerDown", "button": 0},
                {"type": "pointerUp", "button": 0},
            ],
        }]})

    def swipe(self, fx: int, fy: int, tx: int, ty: int, duration_ms: int = 800) -> None:
        # W3C actions：按下→移动到终点(带时长)→抬起，即滑动/拖拽
        self._post("/actions", {"actions": [{
            "type": "pointer", "id": "finger1",
            "parameters": {"pointerType": "touch"},
            "actions": [
                {"type": "pointerMove", "duration": 0, "x": int(fx), "y": int(fy)},
                {"type": "pointerDown", "button": 0},
                {"type": "pointerMove", "duration": int(duration_ms), "x": int(tx), "y": int(ty)},
                {"type": "pointerUp", "button": 0},
            ],
        }]})

    def drag_from_to_for_duration(self, from_x: int, from_y: int, to_x: int, to_y: int,
                                  press_duration_s: float = 0.01) -> None:
        """XCTest pressForDuration:thenDragToCoordinate（分页 carousel 比 W3C drag 更可靠）。"""
        self._post("/wda/dragfromtoforduration", {
            "fromX": int(from_x), "fromY": int(from_y),
            "toX": int(to_x), "toY": int(to_y),
            "duration": float(press_duration_s),
        })

    def element_swipe(self, element_id: str, direction: str) -> None:
        """XCUIElement swipeLeft/Right/Up/Down（/wda/element/{id}/swipe）。"""
        self._post(f"/element/{element_id}/swipe", {"direction": str(direction).lower()})

    def long_press(self, x: int, y: int, duration_ms: int = 1000) -> None:
        # W3C actions：按下→原地停留 duration→抬起，即长按
        self._post("/actions", {"actions": [{
            "type": "pointer", "id": "finger1",
            "parameters": {"pointerType": "touch"},
            "actions": [
                {"type": "pointerMove", "duration": 0, "x": int(x), "y": int(y)},
                {"type": "pointerDown", "button": 0},
                {"type": "pause", "duration": int(duration_ms)},
                {"type": "pointerUp", "button": 0},
            ],
        }]})

    def source(self) -> str:
        return str(self._get("/source") or "")

    def ping(self) -> None:
        """轻量会话探活（source）。"""
        self._get("/source")

    def actions(self, actions: list) -> None:
        """W3C pointer actions（拖拽/滑动等）。"""
        self._post("/actions", {"actions": actions})

    def send_keys(self, text: str) -> None:
        """向当前聚焦控件输入文本（WDA /wda/keys）。"""
        self._post("/wda/keys", {"value": list(text)})

    def double_tap(self, x: int, y: int) -> None:
        self._post("/wda/doubleTap", {"x": int(x), "y": int(y)})

    def press_button(self, name: str) -> None:
        """硬件键：home / volumeUp / volumeDown / snapshot 等（WDA /wda/pressButton）。

        按键是瞬时 RPC：成功几百毫秒内返回，失败也会马上报错。
        跟客户端 15s 默认超时脱钩，避免 WDA 无响应时底栏空等。
        """
        self._post("/wda/pressButton", {"name": name}, timeout=3.0)

    def press_delete(self, count: int = 1) -> None:
        """向当前聚焦控件发送退格（WDA /wda/keys，WebDriver DELETE）。"""
        n = max(1, int(count or 1))
        for _ in range(n):
            self._post("/wda/keys", {"value": ["\ue003"]})

    def lock(self) -> None:
        # 对齐 WebAppFlaskauto-iOS WDAController.lock：顶层 POST /wda/lock，
        # 不走 /session/{id} 前缀；超时与 Flask httpx.Client(timeout=15) 一致。
        self._request("POST", "/wda/lock", json_body={}, timeout=15.0, rooted=True)

    def unlock(self) -> None:
        self._request("POST", "/wda/unlock", json_body={}, timeout=15.0, rooted=True)

    def locked(self) -> bool:
        return bool(self._get("/wda/locked"))

    def get_pasteboard(self) -> str:
        val = self._post("/wda/getPasteboard", {"contentType": "plaintext"})
        # noinspection PyBroadException
        try:
            return base64.b64decode(val).decode("utf-8", "replace") if val else ""
        except Exception:
            return str(val or "")

    def set_pasteboard(self, text: str) -> None:
        b64 = base64.b64encode(text.encode("utf-8")).decode("ascii")
        self._post("/wda/setPasteboard", {"content": b64, "contentType": "plaintext"})

    def home(self) -> None:
        # 对齐 WebAppFlaskauto-iOS：/wda/homescreen 在部分 WDA 上 500，pressButton 更稳。
        self.press_button("home")


class _WdaSwitchTo:
    def __init__(self, driver: "WdaDriver") -> None:
        self._driver = driver

    @property
    def context(self) -> str:
        return self._driver.get_context()

    @context.setter
    def context(self, name: str) -> None:
        self._driver.set_context(name)


class WdaDriver:
    """把 WdaClient 适配成 mobile 关键字所需的「driver」子集接口。

    iOS 不适用的 Android 专有方法（current_activity / press_keycode 等）抛 KeywordError。
    """

    def __init__(self, client: WdaClient, bundle_id: str = "") -> None:
        self._c = client
        self._bundle_id = bundle_id or ""
        self.capabilities = {
            "platformName": "iOS",
            "automationName": "WDA-Direct",
            "bundleId": self._bundle_id,
        }

    @property
    def wda_client(self) -> WdaClient:
        return self._c

    @property
    def bundle_id(self) -> str:
        return self._bundle_id

    def find_element(self, by, value):
        return self._c.find_element(by, value)

    def find_elements(self, by, value):
        return self._c.find_elements(by, value)

    def activate_app(self, bundle_id: str = "") -> None:
        self._c.activate_app(bundle_id or self._bundle_id)

    def launch_app(self, bundle_id: str = "") -> None:
        self._c.launch_app(bundle_id or self._bundle_id)

    def terminate_app(self, bundle_id: str = "") -> None:
        self._c.terminate_app(bundle_id or self._bundle_id)

    def is_app_installed(self, bundle_id: str = "") -> bool:
        return self._c.is_app_installed(bundle_id or self._bundle_id)

    @property
    def current_package(self) -> str:
        return self._bundle_id

    @property
    def contexts(self) -> list[str]:
        return self._c.list_contexts()

    @property
    def switch_to(self) -> _WdaSwitchTo:
        return _WdaSwitchTo(self)

    def press_button(self, name: str) -> None:
        self._c.press_button(name)

    def press_delete(self, count: int = 1) -> None:
        self._c.press_delete(count)

    def dismiss_keyboard(self) -> None:
        self._c.dismiss_keyboard()

    def get_context(self) -> str:
        return self._c.get_context()

    def set_context(self, name: str) -> None:
        self._c.set_context(name)

    def execute_script(self, script: str, *args):
        return self._c.execute_script(script, list(args))

    @property
    def current_url(self) -> str:
        # noinspection PyBroadException
        try:
            return str(self.execute_script("return window.location.href;") or "")
        except Exception:
            return ""

    def get_screenshot_as_png(self) -> bytes:
        return self._c.screenshot_png()

    def get_screenshot_as_file(self, path: str) -> bool:
        with open(path, "wb") as f:
            f.write(self._c.screenshot_png())
        return True

    def get_window_size(self) -> dict:
        return self._c.window_size()

    def device_info(self) -> dict:
        """从 WDA /status 归一出常用设备信息（供 mobile_get_deviceinfo 的 iOS 分支）。"""
        from ...mobile.ios.device_info import wda_status_to_device_info
        return wda_status_to_device_info(self._c.status() or {})

    # noinspection PyUnusedLocal
    def tap(self, positions, duration=None):
        x, y = positions[0]
        self._c.tap(x, y)

    # noinspection PyUnusedLocal
    def swipe(self, start_x, start_y, end_x, end_y, duration=800):
        self._c.swipe(start_x, start_y, end_x, end_y, int(duration or 800))

    def long_press(self, x, y, duration_ms=1000):
        self._c.long_press(x, y, int(duration_ms or 1000))

    def back(self) -> None:
        self._c.home()           # iOS 无系统返回键，回主屏作为近似

    @property
    def page_source(self) -> str:
        return self._c.source()

    def quit(self) -> None:
        self._c.delete_session()

    def _unsupported(self, name: str):
        raise KeywordError(f"iOS 直连 WDA 后端不支持该操作: {name}（Android 专有/Appium 专有）")

    def __getattr__(self, name):
        # 兜底：未实现的 Appium/Android 专有方法 → 明确报不支持，而非 AttributeError
        def _missing(*_a, **_k):
            self._unsupported(name)
        return _missing
