"""Platform Runner 远控用的 iOS 27+ CoreDevice HEVC 画面（主机不转码）。

只供本仓 ``runner.remote.ios``。设备通过 ``startmediastream`` 推 RTP/HEVC，
本模块开独立 Userspace RSD、解 RTP、产出访问单元，再由浏览器 WebCodecs 解码。
iOS 27.0 以下会返回 code 9021，会话应留在 WDA MJPEG。

本文件不属于双仓同构执行核，不放进 ``ap/``，也不引用 AutoPilot IDE。

环境变量 ``IOS_HEVC=0`` 关闭这条路径（测相机等需要独占媒体会话的场景）。
"""

from __future__ import annotations

import asyncio
import os
import struct
import threading
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from queue import Empty, Full, Queue
from typing import Any, Optional, cast

_HEVC_MIN = (27, 0, 0)
_READY_TIMEOUT = 25.0
_QUEUE_MAX = 45


def parse_ios_version(text: str) -> tuple[int, int, int]:
    parts: list[int] = []
    for raw in (text or "").split("."):
        digits = ""
        for ch in raw:
            if ch.isdigit():
                digits += ch
            else:
                break
        if not digits:
            break
        parts.append(int(digits))
    while len(parts) < 3:
        parts.append(0)
    return parts[0], parts[1], parts[2]


def hevc_supported_ios(version: str) -> bool:
    return parse_ios_version(version) >= _HEVC_MIN


def hevc_enabled_by_env() -> bool:
    raw = os.getenv("IOS_HEVC", "auto").strip().lower()
    return raw not in ("0", "false", "no", "off", "mjpeg")


def hevc_api_available() -> bool:
    """当前解释器的 pymobiledevice3 是否带 CoreDevice 屏幕流（需要 >= 11.17.0）。"""
    try:
        from pymobiledevice3.remote.core_device.screen_stream import (  # noqa: F401
            depacketize_hevc,
            hevc_codec_string_from_sps,
            hevc_decoder_configuration_record,
            open_media_receiver,
        )
        from pymobiledevice3.remote.userspace_tunnel import UserspaceRsdTunnel  # noqa: F401
    except ImportError:
        return False
    return True


def frame_access_unit(nals: list[bytes], *, key: bool, reset: bool = False) -> bytes:
    """WebCodecs 访问单元：``[uint32 BE length][uint8 type][4 字节长度前缀 NAL]``。

    type 0 = key，1 = delta，2 = 必须重置解码器的 key。
    """
    au = b"".join(len(nal).to_bytes(4, "big") + nal for nal in nals)
    if key and reset:
        type_byte = 2
    elif key:
        type_byte = 0
    else:
        type_byte = 1
    return (len(au) + 1).to_bytes(4, "big") + bytes((type_byte,)) + au


def annexb_access_unit(unit: "HevcAccessUnit") -> bytes:
    """PyAV 用的 Annex-B。关键帧补上已见过的 VPS/SPS/PPS。"""
    have = {(nal[0] >> 1) & 0x3F for nal in unit.nals if nal}
    prefix: list[bytes] = []
    if unit.vps and 32 not in have:
        prefix.append(unit.vps)
    if unit.sps and 33 not in have:
        prefix.append(unit.sps)
    if unit.pps and 34 not in have:
        prefix.append(unit.pps)
    return b"".join(b"\x00\x00\x00\x01" + nal for nal in prefix + list(unit.nals))


@dataclass
class HevcAccessUnit:
    keyframe: bool
    reset: bool
    nals: list[bytes]
    codec_string: Optional[str] = None
    description: Optional[bytes] = None
    vps: Optional[bytes] = None
    sps: Optional[bytes] = None
    pps: Optional[bytes] = None

    def webcodecs_packet(self) -> bytes:
        return frame_access_unit(self.nals, key=self.keyframe, reset=self.reset)


def build_rtcp_pli(local_ssrc: int, remote_ssrc: int) -> bytes:
    return struct.pack("!BBHII", 0x81, 0xCE, 2, local_ssrc & 0xFFFFFFFF, remote_ssrc & 0xFFFFFFFF)


def build_rtcp_rr(local_ssrc: int, remote_ssrc: int, highest_seq: int) -> bytes:
    """RR + 空 SDES。不发 RR 时设备会停掉编码器。"""
    rr = struct.pack(
        "!BBHIIBBBBIIII",
        0x81,
        0xC9,
        7,
        local_ssrc & 0xFFFFFFFF,
        remote_ssrc & 0xFFFFFFFF,
        0,
        0,
        0,
        0,
        highest_seq & 0xFFFFFFFF,
        0,
        0,
        0,
    )
    sdes = struct.pack(
        "!BBHIBBBB",
        0x81,
        0xCA,
        2,
        local_ssrc & 0xFFFFFFFF,
        0x01,
        0x00,
        0x00,
        0x00,
    )
    return rr + sdes


def _schedule(loop: asyncio.AbstractEventLoop, callback: Callable[[], None]) -> None:
    schedule = cast(Callable[[Callable[[], None]], object], loop.call_soon_threadsafe)
    _ = schedule(callback)


async def await_until_stopped(work: Awaitable[Any], stopped: asyncio.Event) -> Any:
    """``stopped`` 先到时取消 ``work`` 并返回 None。``work`` 先结束则返回它的结果。"""
    task = asyncio.ensure_future(work)
    stop_task = asyncio.ensure_future(stopped.wait())
    _done, pending = await asyncio.wait(
        {task, stop_task},
        return_when=asyncio.FIRST_COMPLETED,
    )
    for item in pending:
        item.cancel()
    for item in pending:
        with suppress(asyncio.CancelledError):
            await item
    if task in pending:
        return None
    return task.result()


class IosHevcStream:
    """一条设备的 HEVC 读流。``start`` 等到首个带 hvcC 的关键帧，或 25 秒失败。"""

    def __init__(self, udid: str):
        self.udid = udid
        self._queue: Queue[HevcAccessUnit] = Queue(maxsize=_QUEUE_MAX)
        self._stop = threading.Event()
        self._cancel = threading.Event()
        self._ready = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._async_stop: Optional[asyncio.Event] = None
        self._tunnel: object | None = None
        self._media_transport: object | None = None
        self._key_event: Optional[asyncio.Event] = None
        self._error: Optional[BaseException] = None
        self._healthy = False
        self._codec_string: Optional[str] = None
        self._description: Optional[bytes] = None
        self._vps: Optional[bytes] = None
        self._sps: Optional[bytes] = None
        self._pps: Optional[bytes] = None
        self._want_key = False
        self._highest_seq = 0

    def start(self) -> None:
        if self._cancel.is_set():
            raise RuntimeError("HEVC 已取消")
        if self._thread and self._thread.is_alive():
            return
        if not hevc_api_available():
            raise RuntimeError("pymobiledevice3 没有 CoreDevice HEVC API（需要 >= 11.17.0）")
        self._stop.clear()
        if self._cancel.is_set():
            self._stop.set()
            raise RuntimeError("HEVC 已取消")
        self._ready.clear()
        self._error = None
        self._healthy = False
        self._async_stop = None
        self._thread = threading.Thread(
            target=self._thread_main, name=f"hevc-{self.udid[:8]}", daemon=True
        )
        self._thread.start()
        if not self._ready.wait(_READY_TIMEOUT):
            self.stop()
            raise RuntimeError("HEVC 在时限内没有关键帧")
        if self._cancel.is_set() or self._stop.is_set():
            self.stop()
            raise RuntimeError("HEVC 已取消")
        if self._error is not None:
            err = self._error
            self.stop()
            raise RuntimeError(f"HEVC 开流失败: {err}") from err

    def _release_blockers(self) -> None:
        """从 stop 线程关掉已拿到的隧道套接字和媒体口，唤醒库里不看取消的阻塞读。"""
        tunnel = self._tunnel
        tun = getattr(tunnel, "tun", None) if tunnel is not None else None
        for sock in (
            getattr(tun, "_peer", None),
            getattr(tun, "_pend", None),
        ):
            if sock is None:
                continue
            closer = getattr(sock, "close", None)
            if not callable(closer):
                continue
            # noinspection PyBroadException
            try:
                closer()
            except Exception:
                pass
        transport = self._media_transport
        if transport is None:
            return
        closer = getattr(transport, "close", None)
        if not callable(closer):
            return
        # noinspection PyBroadException
        try:
            closer()
        except Exception:
            pass

    def stop(self) -> None:
        self._cancel.set()
        self._stop.set()
        self._healthy = False
        self._release_blockers()
        loop = self._loop
        if loop is not None and loop.is_running():
            def _poke() -> None:
                ev = self._async_stop
                if ev is not None and not ev.is_set():
                    ev.set()

            # noinspection PyBroadException
            try:
                _schedule(loop, _poke)
            except RuntimeError:
                pass
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=5)
        if thread is None or not thread.is_alive():
            self._thread = None

    def thread_alive(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def read(self, timeout: float = 0.5) -> Optional[HevcAccessUnit]:
        if self._stop.is_set() and self._queue.empty():
            return None
        try:
            return self._queue.get(timeout=timeout)
        except Empty:
            return None

    def health(self) -> bool:
        alive = self._thread is not None and self._thread.is_alive()
        return bool(self._healthy and alive and not self._stop.is_set())

    def request_keyframe(self) -> None:
        loop = self._loop
        ev = self._key_event
        if loop is None or ev is None or not loop.is_running():
            self._want_key = True
            return

        def _ask() -> None:
            ev.set()

        _schedule(loop, _ask)

    def _fail(self, exc: BaseException) -> None:
        self._error = exc
        self._healthy = False
        self._ready.set()

    def _thread_main(self) -> None:
        try:
            asyncio.run(self._run())
        except Exception as exc:  # noqa: BLE001
            self._fail(exc)
        finally:
            self._healthy = False
            self._ready.set()

    async def _watch_stop(self) -> None:
        while not self._stop.is_set():
            await asyncio.sleep(0.05)
        ev = self._async_stop
        if ev is not None and not ev.is_set():
            ev.set()

    async def _run(self) -> None:
        from pymobiledevice3.remote.core_device.display_service import DisplayService
        from pymobiledevice3.remote.core_device.screen_stream import open_media_receiver
        from pymobiledevice3.remote.userspace_tunnel import UserspaceRsdTunnel

        self._loop = asyncio.get_running_loop()
        self._key_event = asyncio.Event()
        self._async_stop = asyncio.Event()
        if self._stop.is_set():
            self._async_stop.set()
        watcher = asyncio.create_task(self._watch_stop())
        tunnel = None
        try:
            if self._stop.is_set():
                return
            tunnel = UserspaceRsdTunnel(serial=self.udid, remotepairing_fallback=False)
            self._tunnel = tunnel
            rsd = await await_until_stopped(tunnel.aopen(), self._async_stop)
            if rsd is None or self._stop.is_set():
                return
            await await_until_stopped(
                self._stream(rsd, DisplayService, open_media_receiver),
                self._async_stop,
            )
        finally:
            watcher.cancel()
            with suppress(asyncio.CancelledError):
                await watcher
            if tunnel is not None:
                with suppress(Exception):
                    await tunnel.aclose()

    async def _stream(self, rsd, display_cls, open_media_receiver) -> None:
        sender_ip = rsd.service.address[0]
        async with display_cls(rsd) as service:
            transport, receiver_ip = open_media_receiver(
                service, (8 * 1024 * 1024, 4 * 1024 * 1024)
            )
            self._media_transport = transport
            try:
                answer = await service.start_video_stream(
                    receiver_ip=receiver_ip,
                    receiver_port=transport.port,
                    sender_ip=sender_ip,
                    display_id=1,
                )
                cfg = (answer.get("connection") or {}).get("streamConfig") or {}
                source_port = int(cfg.get("SourcePort") or 0)
                local_ssrc = int(cfg.get("RemoteSSRC") or 0)
                remote_ssrc = int(cfg.get("LocalSSRC") or 0)
                rtcp_dest = (sender_ip, source_port) if source_port else None
                self._healthy = True
                rtcp_task = None
                if rtcp_dest and local_ssrc and remote_ssrc:
                    rtcp_task = asyncio.create_task(
                        self._rtcp_loop(transport, rtcp_dest, local_ssrc, remote_ssrc)
                    )
                try:
                    await self._recv_loop(transport, rtcp_dest, local_ssrc, remote_ssrc)
                finally:
                    if rtcp_task is not None:
                        rtcp_task.cancel()
                        with suppress(asyncio.CancelledError):
                            await rtcp_task
            finally:
                with suppress(Exception):
                    await display_cls.stop_all_streams(rsd)
                with suppress(Exception):
                    transport.close()

    async def _rtcp_loop(self, transport, dest, local_ssrc: int, remote_ssrc: int) -> None:
        while not self._stop.is_set():
            await asyncio.sleep(1.0)
            if self._stop.is_set():
                return
            seq = self._highest_seq
            if not seq:
                continue
            with suppress(Exception):
                await transport.sendto(build_rtcp_rr(local_ssrc, remote_ssrc, seq), *dest)

    async def _recv_loop(self, transport, rtcp_dest, local_ssrc: int, remote_ssrc: int) -> None:
        from pymobiledevice3.remote.core_device.screen_stream import (
            depacketize_hevc,
            hevc_codec_string_from_sps,
            hevc_decoder_configuration_record,
        )

        fu = bytearray()
        current: list[bytes] = []
        au_key = False
        au_corrupt = False
        reset_next_key = False
        last_seq: Optional[int] = None
        while not self._stop.is_set():
            if self._want_key or (self._key_event is not None and self._key_event.is_set()):
                self._want_key = False
                if self._key_event is not None:
                    self._key_event.clear()
                reset_next_key = True
                await self._send_pli(transport, rtcp_dest, local_ssrc, remote_ssrc)
            try:
                data = await asyncio.wait_for(transport.recv(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            except Exception as exc:  # noqa: BLE001
                self._fail(exc)
                return
            if len(data) < 12:
                continue
            pt = data[1] & 0x7F
            if 64 <= pt <= 95:
                continue
            marker = (data[1] >> 7) & 1
            cc = data[0] & 0x0F
            header_len = 12 + cc * 4
            if data[0] & 0x10 and header_len + 4 <= len(data):
                ext_len = int.from_bytes(data[header_len + 2 : header_len + 4], "big")
                header_len += 4 + ext_len * 4
            if header_len > len(data):
                continue
            payload = data[header_len:]
            seq = int.from_bytes(data[2:4], "big")
            self._highest_seq = seq
            if last_seq is not None and seq != ((last_seq + 1) & 0xFFFF):
                forward = ((seq - last_seq) & 0xFFFF) < 0x8000
                if forward:
                    fu.clear()
                    au_corrupt = True
                    reset_next_key = True
                    await self._send_pli(transport, rtcp_dest, local_ssrc, remote_ssrc)
            if last_seq is None or ((seq - last_seq) & 0xFFFF) < 0x8000:
                last_seq = seq
            nals: list[bytes] = []
            depacketize_hevc(payload, fu, nals)
            for nal in nals:
                if not nal:
                    continue
                nt = (nal[0] >> 1) & 0x3F
                if nt == 32:
                    self._vps = nal
                elif nt == 33:
                    self._sps = nal
                    if self._codec_string is None:
                        with suppress(Exception):
                            self._codec_string = hevc_codec_string_from_sps(nal)
                elif nt == 34:
                    self._pps = nal
                if nt in (19, 20, 21):
                    au_key = True
                current.append(nal)
            if not marker:
                continue
            if au_corrupt or not current:
                current = []
                au_key = False
                au_corrupt = False
                continue
            if (
                self._vps
                and self._sps
                and self._pps
                and self._description is None
                and self._codec_string
            ):
                with suppress(Exception):
                    self._description = hevc_decoder_configuration_record(
                        self._vps, self._sps, self._pps
                    )
            reset = bool(au_key and reset_next_key)
            if au_key and reset:
                reset_next_key = False
            unit = HevcAccessUnit(
                keyframe=au_key,
                reset=reset,
                nals=current,
                codec_string=self._codec_string,
                description=self._description,
                vps=self._vps,
                sps=self._sps,
                pps=self._pps,
            )
            current = []
            au_key = False
            self._enqueue(unit)
            if unit.keyframe and unit.description and unit.codec_string:
                self._ready.set()

    def _arm_resync(self) -> None:
        self._want_key = True
        if self._key_event is not None:
            self._key_event.set()

    def _enqueue(self, unit: HevcAccessUnit) -> None:
        if self._queue.full():
            if not unit.keyframe:
                self._arm_resync()
                return
            with suppress(Empty):
                self._queue.get_nowait()
            unit.reset = True
        try:
            self._queue.put_nowait(unit)
        except Full:
            self._arm_resync()

    @staticmethod
    async def _send_pli(transport, dest, local_ssrc: int, remote_ssrc: int) -> None:
        if not dest or not local_ssrc or not remote_ssrc:
            return
        with suppress(Exception):
            await transport.sendto(build_rtcp_pli(local_ssrc, remote_ssrc), *dest)
