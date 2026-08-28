"""WDA MJPEG 切帧（无 Qt 依赖；对齐 AutoPilot inspector/stream/mjpeg_source.split_jpegs）。"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Optional

_log = logging.getLogger(__name__)

_SOI = b"\xff\xd8"
_EOI = b"\xff\xd9"


def split_jpegs(buf: bytes) -> tuple[list[bytes], bytes]:
    """从字节缓冲切出完整 JPEG。返回 (帧列表, 剩余缓冲)。"""
    frames: list[bytes] = []
    while True:
        s = buf.find(_SOI)
        if s < 0:
            return frames, buf[-1:] if buf[-1:] == b"\xff" else b""
        e = buf.find(_EOI, s + 2)
        if e < 0:
            return frames, buf[s:]
        frames.append(buf[s : e + 2])
        buf = buf[e + 2 :]


def jpeg_size(jpeg: bytes) -> tuple[int, int]:
    """从 JPEG SOF 粗读宽高；失败返回 (0, 0)。"""
    try:
        i = 2
        while i + 9 < len(jpeg):
            if jpeg[i] != 0xFF:
                break
            marker = jpeg[i + 1]
            if marker in (0xC0, 0xC1, 0xC2):
                h = (jpeg[i + 5] << 8) | jpeg[i + 6]
                w = (jpeg[i + 7] << 8) | jpeg[i + 8]
                return int(w), int(h)
            if marker == 0xD9 or marker == 0xDA:
                break
            length = (jpeg[i + 2] << 8) | jpeg[i + 3]
            if length < 2:
                break
            i += 2 + length
    except (IndexError, TypeError, ValueError):
        pass
    return 0, 0


class MjpegReader:
    """后台线程拉取 MJPEG，按 FPS 上限回调最新 JPEG。"""

    def __init__(
        self,
        url: str,
        on_frame: Callable[[bytes, int, int], None],
        *,
        fps: float = 10.0,
        stop_event: Optional[threading.Event] = None,
        on_unhealthy: Optional[Callable[[str], None]] = None,
        unhealthy_after: int = 3,
    ) -> None:
        self.url = url
        self._on_frame = on_frame
        self._on_unhealthy = on_unhealthy
        self._unhealthy_after = max(1, int(unhealthy_after))
        self._min_interval = 1.0 / max(0.5, float(fps))
        self._stop = stop_event or threading.Event()
        self._thread: threading.Thread | None = None
        self._fail_streak = 0

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._run, name="ios-mjpeg-reader", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def set_fps(self, fps: float) -> None:
        self._min_interval = 1.0 / max(0.5, float(fps))

    def _mark_fail(self, reason: str) -> None:
        self._fail_streak += 1
        if self._fail_streak < self._unhealthy_after:
            return
        if self._on_unhealthy is None:
            return
        try:
            self._on_unhealthy(reason)
        except Exception as exc:  # noqa: BLE001
            _log.debug("on_unhealthy: %s", exc)

    def _run(self) -> None:
        try:
            import httpx
        except ImportError as exc:
            _log.warning("httpx missing for MJPEG: %s", exc)
            self._mark_fail(f"httpx missing: {exc}")
            return

        timeout = httpx.Timeout(connect=15.0, read=10.0, write=10.0, pool=10.0)
        buf = b""
        last_emit = 0.0
        while not self._stop.is_set():
            try:
                with httpx.stream("GET", self.url, timeout=timeout) as resp:
                    resp.raise_for_status()
                    got_frame = False
                    for chunk in resp.iter_bytes():
                        if self._stop.is_set():
                            return
                        if not chunk:
                            continue
                        buf += chunk
                        if len(buf) > 8 * 1024 * 1024:
                            buf = buf[-2 * 1024 * 1024 :]
                        frames, buf = split_jpegs(buf)
                        if not frames:
                            continue
                        now = time.monotonic()
                        if now - last_emit < self._min_interval:
                            continue
                        jpg = frames[-1]
                        w, h = jpeg_size(jpg)
                        last_emit = now
                        got_frame = True
                        self._fail_streak = 0
                        try:
                            self._on_frame(jpg, w, h)
                        except Exception as exc:  # noqa: BLE001
                            _log.debug("on_frame: %s", exc)
                    if not got_frame:
                        self._mark_fail("MJPEG stream ended without frames")
            except Exception as exc:  # noqa: BLE001
                if self._stop.is_set():
                    return
                _log.warning("MJPEG stream error: %s", exc)
                self._mark_fail(str(exc))
                self._stop.wait(1.0)
