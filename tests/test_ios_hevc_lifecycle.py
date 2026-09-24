"""iOS HEVC 开流取消、会话只释放一次、MJPEG 只建一路。不打开真机。"""

from __future__ import annotations

import asyncio
import threading
from typing import Any

from autopilot_platform.runner.remote.ios.hevc_stream import (
    IosHevcStream,
    await_until_stopped,
)
from autopilot_platform.runner.remote.ios.session import IosRemoteSession


def _post_media(_body: dict[str, Any]) -> None:
    return None


def _poll_media() -> list[dict[str, Any]]:
    return []


def _report_status(_status: str, _detail: str) -> None:
    return None


def _session() -> IosRemoteSession:
    return IosRemoteSession(
        session_id="session-123456",
        udid="udid-1",
        post_media=_post_media,
        poll_media=_poll_media,
        report_status=_report_status,
    )


def test_await_until_stopped_cancels():
    async def slow() -> str:
        await asyncio.sleep(30)
        return "late"

    async def main_async() -> str | None:
        stopped = asyncio.Event()

        async def poke() -> None:
            await asyncio.sleep(0.02)
            stopped.set()

        poker = asyncio.create_task(poke())
        result = await asyncio.wait_for(
            await_until_stopped(slow(), stopped),
            timeout=2,
        )
        await poker
        return result

    assert asyncio.run(main_async()) is None


def _install_fake_tunnel(tunnel_cls: type):
    import sys
    import types

    names = (
        "pymobiledevice3.remote.core_device",
        "pymobiledevice3.remote.core_device.screen_stream",
        "pymobiledevice3.remote.core_device.display_service",
        "pymobiledevice3.remote.userspace_tunnel",
    )
    previous = {name: sys.modules.get(name) for name in names}

    def ensure(name: str):
        module = sys.modules.get(name)
        if module is None:
            module = types.ModuleType(name)
            sys.modules[name] = module
        return module

    def _depacketize(_payload: bytes, _fu: object, _nals: list[bytes]) -> None:
        return None

    def _codec_string(_nal: bytes) -> str:
        return ""

    def _decoder_record(_nals: list[bytes]) -> bytes:
        return b""

    def _open_receiver(_service: object, _sizes: tuple[int, int]) -> tuple[None, None]:
        return None, None

    screen = ensure("pymobiledevice3.remote.core_device.screen_stream")
    screen.depacketize_hevc = _depacketize
    screen.hevc_codec_string_from_sps = _codec_string
    screen.hevc_decoder_configuration_record = _decoder_record
    screen.open_media_receiver = _open_receiver
    display = ensure("pymobiledevice3.remote.core_device.display_service")
    display.DisplayService = object
    users = ensure("pymobiledevice3.remote.userspace_tunnel")
    users.UserspaceRsdTunnel = tunnel_cls

    def restore() -> None:
        for name, module in previous.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module

    return restore


def test_stop_during_open_closes_tunnel():
    closed: list[str] = []
    opened = threading.Event()

    class _Tunnel:
        def __init__(self, serial: str = "", remotepairing_fallback: bool = False) -> None:
            self.serial = serial
            self.remotepairing_fallback = remotepairing_fallback

        @staticmethod
        async def aopen() -> object:
            opened.set()
            await asyncio.sleep(30)
            return object()

        async def aclose(self) -> None:
            closed.append(self.serial)

    restore = _install_fake_tunnel(_Tunnel)
    stream = IosHevcStream("deadbeef")
    errors: list[str] = []

    def _run_start() -> None:
        try:
            stream.start()
        except RuntimeError as exc:
            errors.append(str(exc))

    try:
        worker = threading.Thread(target=_run_start)
        worker.start()
        assert opened.wait(2)
        stream.stop()
        worker.join(timeout=3)
        assert not worker.is_alive()
        assert errors and "已取消" in errors[0]
        assert closed == ["deadbeef"]
        assert stream.thread_alive() is False
    finally:
        restore()


def test_stop_releases_runtime_once(monkeypatch):
    released: list[str] = []
    import autopilot_platform.ap.runtime.device_runtime as runtime

    def _release(udid: str) -> None:
        released.append(udid)

    monkeypatch.setattr(runtime, "release_device_runtime", _release)
    session = _session()
    session._runtime_acquired = True
    threads = [threading.Thread(target=session.stop) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=3)
    assert released == ["udid-1"]


def test_fallback_and_session_share_one_mjpeg_reader(monkeypatch):
    created: list[object] = []

    class _Reader:
        def __init__(self, url: str, on_frame, **kwargs) -> None:
            created.append(self)
            self.url = url
            self.on_frame = on_frame
            self.options = kwargs

        @staticmethod
        def start() -> None:
            return None

        @staticmethod
        def stop() -> None:
            return None

    monkeypatch.setattr(
        "autopilot_platform.runner.remote.ios.session.MjpegReader",
        _Reader,
    )
    session = _session()
    session._mjpeg_url = "http://127.0.0.1/mjpeg"
    session._video_mode = "hevc"
    session._hevc = object()
    barrier = threading.Barrier(2)

    def _fallback() -> None:
        barrier.wait(timeout=2)
        session._fallback_hevc_to_mjpeg("browser")

    def _direct() -> None:
        barrier.wait(timeout=2)
        session._start_mjpeg([False])

    threads = [
        threading.Thread(target=_fallback),
        threading.Thread(target=_direct),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=3)
    assert len(created) == 1


def test_mjpeg_stop_closes_response_and_joins() -> None:
    import threading

    from autopilot_platform.runner.remote.ios.mjpeg_reader import MjpegReader

    closed = threading.Event()
    release = threading.Event()
    started = threading.Event()

    class _Response:
        @staticmethod
        def close() -> None:
            closed.set()
            release.set()

    def _on_frame(_jpeg: bytes, _w: int, _h: int) -> None:
        return None

    reader = MjpegReader("http://127.0.0.1/mjpeg", _on_frame)

    def _block() -> None:
        reader._response = _Response()
        started.set()
        release.wait(timeout=2)

    worker = threading.Thread(target=_block)
    reader._thread = worker
    worker.start()
    assert started.wait(timeout=1)
    reader.stop()
    assert closed.is_set()
    assert not worker.is_alive()


def test_hevc_stop_closes_tunnel_socket_while_thread_blocks() -> None:
    import socket
    import threading

    from autopilot_platform.runner.remote.ios.hevc_stream import IosHevcStream

    left, right = socket.socketpair()
    released = threading.Event()

    class _Sock:
        def __init__(self, raw: socket.socket) -> None:
            self._raw = raw

        def close(self) -> None:
            self._raw.close()
            released.set()

    stream = IosHevcStream("deadbeef")
    stream._tunnel = type(
        "T",
        (),
        {"tun": type("U", (), {"_peer": _Sock(left), "_pend": _Sock(right)})()},
    )()

    def _block() -> None:
        try:
            left.recv(8)
        except OSError:
            pass

    worker = threading.Thread(target=_block)
    stream._thread = worker
    worker.start()
    stream.stop()
    assert released.is_set()
    assert not worker.is_alive()
