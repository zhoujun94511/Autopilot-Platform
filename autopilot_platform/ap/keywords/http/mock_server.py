"""通用 HTTP Mock Server（中性替代，不依赖任何私有桩平台）。

进程内启一个轻量 HTTP 服务：按路径登记桩响应（状态码/报文/头），并记录收到的请求体，
供 mock 类关键字登记桩、回读请求报文。与原厂私有 Mock/RSF 平台无关。
"""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional


# do_GET 等为 BaseHTTPRequestHandler 约定大写方法名；srv.stubs/received 为运行期动态挂载
# noinspection PyPep8Naming,PyUnresolvedReferences
class _Handler(BaseHTTPRequestHandler):
    # noinspection PyShadowingBuiltins
    def log_message(self, *_a) -> None:  # 静默
        pass

    def _serve(self) -> None:
        srv = self.server
        path = self.path.split("?")[0]
        length = int(self.headers.get("Content-Length", "0") or 0)
        body = self.rfile.read(length) if length else b""
        srv.received[path] = body.decode("utf-8", "replace")   # 记录请求报文
        stub = srv.stubs.get(path)
        if stub is None:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"no stub registered")
            return
        self.send_response(int(stub.get("status", 200)))
        for k, v in (stub.get("headers") or {}).items():
            self.send_header(k, str(v))
        self.end_headers()
        self.wfile.write((stub.get("body") or "").encode("utf-8"))

    def do_GET(self):     # noqa: N802
        self._serve()

    def do_POST(self):    # noqa: N802
        self._serve()

    def do_PUT(self):     # noqa: N802
        self._serve()

    def do_DELETE(self):  # noqa: N802
        self._serve()


class MockServer:
    """按路径登记桩响应 + 记录收到请求的进程内 mock 服务。"""

    def __init__(self) -> None:
        self._srv: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self.stubs: dict[str, dict] = {}
        self.received: dict[str, str] = {}
        self.mode: str = "normal"        # 桩服务模式(normal/exception/timeout…)，供 set/getMockMode

    def start(self) -> "MockServer":
        if self._srv is not None:
            return self
        # noinspection PyTypeChecker
        self._srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self._srv.stubs = self.stubs        # type: ignore[attr-defined]
        self._srv.received = self.received   # type: ignore[attr-defined]
        self._thread = threading.Thread(target=self._srv.serve_forever, daemon=True)
        self._thread.start()
        return self

    @property
    def running(self) -> bool:
        return self._srv is not None

    @property
    def port(self) -> Optional[int]:
        return self._srv.server_address[1] if self._srv else None

    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}" if self._srv else ""

    def set_stub(self, path: str, status: int = 200, body: str = "",
                 headers: Optional[dict] = None) -> str:
        if not path.startswith("/"):
            path = "/" + path
        self.stubs[path] = {"status": status, "body": body, "headers": headers or {}}
        return self.base_url() + path

    def clear(self) -> None:
        self.stubs.clear()
        self.received.clear()

    def stop(self) -> None:
        if self._srv is not None:
            self._srv.shutdown()
            self._srv.server_close()
            self._srv = None


_GLOBAL: Optional[MockServer] = None


def get_mock_server() -> MockServer:
    """返回（必要时启动）全局 mock 服务单例。"""
    global _GLOBAL
    if _GLOBAL is None:
        _GLOBAL = MockServer().start()
    elif not _GLOBAL.running:
        _GLOBAL.start()
    return _GLOBAL
