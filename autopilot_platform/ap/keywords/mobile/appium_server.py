"""Appium server 生命周期管理（Android / Mac iOS Appium 会话需要）。

策略：
  - 每台设备绑定独立端口（slot0=4723，slot1=4724…），各起各的进程；
  - 该端口已在监听 → 认为是外部或本设备已起的 server，复用且**不接管、不杀**；
  - 未监听 → 自动 `appium -p <port>` 拉起，关闭时只杀这一端口上由我们起的进程；
  - 未装 appium → 抛明确错误。
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import threading
import time
from contextlib import closing
from typing import Optional

from ...mobile.android_env import apply_android_env
from ...runtime import settings
from ...runtime.subproc import popen as popen_hidden


def _augment_path() -> str:
    """把 Homebrew / 常见 npm 全局路径并入 PATH（IDE 瘦环境用）。"""
    extra = [
        "/opt/homebrew/bin",
        "/usr/local/bin",
        os.path.expanduser("~/.local/bin"),
    ]
    nvm = os.path.expanduser("~/.nvm/versions/node")
    if os.path.isdir(nvm):
        for name in sorted(os.listdir(nvm), reverse=True):
            extra.append(os.path.join(nvm, name, "bin"))
    cur = os.environ.get("PATH", "")
    parts = extra + ([p for p in cur.split(os.pathsep) if p])
    seen = set()
    out = []
    for p in parts:
        if p and p not in seen:
            seen.add(p)
            out.append(p)
    return os.pathsep.join(out)


def resolve_appium_binary() -> str:
    """定位 appium 可执行文件（which + Homebrew 等兜底）。"""
    path = _augment_path()
    appium = shutil.which("appium", path=path)
    if appium:
        return appium
    for candidate in (
        "/opt/homebrew/bin/appium",
        "/usr/local/bin/appium",
        os.path.expanduser("~/.local/bin/appium"),
    ):
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return ""


class AppiumServer:
    def __init__(self, host: str = "127.0.0.1", port: int = 4723) -> None:
        self.host = host
        self.port = port
        self._proc: Optional[subprocess.Popen] = None   # 仅当由我们启动时非空
        self._lock = threading.Lock()
        self._booting = False

    def is_running(self) -> bool:
        with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
            s.settimeout(0.4)
            return s.connect_ex((self.host, self.port)) == 0

    def started_by_us(self) -> bool:
        return self._proc is not None

    def ensure_running(self, timeout: float | None = None) -> None:
        """确保 4723 可用：已起则复用；未起则拉起并等待就绪；未装则抛错。

        ``timeout`` 为 None 时使用 ``settings.appium_startup_timeout_s()``（默认 40s）。
        """
        if timeout is None:
            timeout = settings.appium_startup_timeout_s()
        with self._lock:
            if self.is_running():
                return
            appium = resolve_appium_binary()
            if not appium:
                raise RuntimeError(
                    "未检测到 Appium。已探测 PATH 与 /opt/homebrew/bin。"
                    "请确认 `which appium` 有输出，或先 `npm i -g appium` "
                    "并 `appium driver install uiautomator2` / `xcuitest`。")
            cmd = [appium, "-a", self.host, "-p", str(self.port)]
            if appium.lower().endswith((".cmd", ".bat")):
                cmd = ["cmd", "/c"] + cmd
            env = os.environ.copy()
            env["PATH"] = _augment_path()
            # UiAutomator2 驱动在 Appium **服务进程**内读 ANDROID_HOME
            # noinspection PyBroadException
            try:
                apply_android_env()
                for key in ("ANDROID_HOME", "ANDROID_SDK_ROOT", "ANDROID_ADB"):
                    if key in os.environ:
                        env[key] = os.environ[key]
            except Exception:
                pass
            self._booting = True
            # noinspection PyBroadException
            try:
                proc = popen_hidden(cmd, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, env=env)
                self._proc = proc
                register_started_appium_server(self)
            except Exception as e:  # noqa: BLE001
                self._booting = False
                raise RuntimeError(f"启动 Appium server 失败：{e}")
            deadline = time.monotonic() + timeout
            try:
                while time.monotonic() < deadline:
                    if self.is_running():
                        return
                    if proc.poll() is not None:
                        self._proc = None
                        raise RuntimeError(
                            f"Appium server 启动后随即退出（{appium}；检查 Node/xcuitest 驱动）")
                    time.sleep(0.5)
                self._stop_unlocked()
                raise RuntimeError(f"Appium server 在 {timeout:.0f}s 内未就绪（{appium}）")
            finally:
                self._booting = False

    def stop(self) -> None:
        """只停由我们起的 server（外部已起的不动）。"""
        with self._lock:
            self._stop_unlocked()

    def _stop_unlocked(self) -> None:
        if self._booting:
            return
        if self._proc is None:
            return
        proc = self._proc
        self._proc = None
        # noinspection PyBroadException
        try:
            proc.terminate()
            # noinspection PyBroadException
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()
        except Exception:
            pass


# 按 (host, port) 隔离：一台设备一个 Appium 进程，禁止再「杀光本进程所有 server」。
_POOL_LOCK = threading.Lock()
_SERVER_POOL: dict[tuple[str, int], AppiumServer] = {}


def _norm_host(host: str) -> str:
    h = (host or "127.0.0.1").strip().lower()
    if h in {"localhost", "::1"}:
        return "127.0.0.1"
    return h or "127.0.0.1"


def acquire_local_appium(host: str = "127.0.0.1", port: int = 4723) -> AppiumServer:
    """取得该端口的 Appium 实例并 ensure_running（已在监听则复用、不接管）。"""
    key = (_norm_host(host), int(port))
    with _POOL_LOCK:
        srv = _SERVER_POOL.get(key)
        if srv is None:
            srv = AppiumServer(host=key[0], port=key[1])
            _SERVER_POOL[key] = srv
    srv.ensure_running()
    return srv


def stop_local_appium(host: str = "127.0.0.1", port: int = 4723) -> None:
    """只停这一端口上由我们拉起的进程；其它设备的 Appium 不动。"""
    key = (_norm_host(host), int(port))
    with _POOL_LOCK:
        srv = _SERVER_POOL.get(key)
    if srv is None:
        return
    srv.stop()
    with _POOL_LOCK:
        if _SERVER_POOL.get(key) is srv and not srv.started_by_us():
            _SERVER_POOL.pop(key, None)


def register_started_appium_server(server: AppiumServer) -> None:
    key = (_norm_host(server.host), int(server.port))
    with _POOL_LOCK:
        _SERVER_POOL.setdefault(key, server)


def stop_started_appium_servers(*, ports: list[int] | None = None) -> None:
    """停止本进程拉起的 Appium。

    ``ports`` 指定时只杀这些端口；省略时杀池内全部（仅测试/进程退出）。
    """
    if ports is None:
        with _POOL_LOCK:
            keys = list(_SERVER_POOL.keys())
    else:
        keys = [(_norm_host("127.0.0.1"), int(p)) for p in ports]
        keys.extend((_norm_host("localhost"), int(p)) for p in ports)
        keys = list(dict.fromkeys(keys))
    for host, port in keys:
        stop_local_appium(host, port)


def reset_appium_server_pool_for_tests() -> None:
    with _POOL_LOCK:
        _SERVER_POOL.clear()
