"""远控设备日志泵：独立子进程 + 批量 HTTP 投递，不走 media/WebRTC。"""

from __future__ import annotations

import logging
import subprocess
import threading
import time
from typing import Any, Callable

_log = logging.getLogger(__name__)

_FLUSH_LINES = 40
_FLUSH_SEC = 0.08
_MAX_LINE = 8192

ReplyFn = Callable[[dict[str, Any]], None]
PostLinesFn = Callable[[list[str]], None]

_lock = threading.Lock()
_pumps: dict[str, "_Pump"] = {}
_udid_index: dict[str, set[str]] = {}


class _Pump:
    def __init__(
        self,
        *,
        session_id: str,
        udid: str,
        platform: str,
        post_lines: PostLinesFn,
    ) -> None:
        self.session_id = session_id
        self.udid = udid
        self.platform = platform
        self.post_lines = post_lines
        self.stop = threading.Event()
        self.proc: subprocess.Popen[str] | None = None
        self.thread: threading.Thread | None = None
        self.filters: tuple[str, str] = ("I", "")


def handle_command(
    *,
    session_id: str,
    udid: str,
    platform: str,
    event: dict[str, Any],
    post_lines: PostLinesFn | None,
    reply: ReplyFn,
) -> bool:
    command = str(event.get("t") or event.get("name") or "")
    if not command.startswith("log."):
        return False

    def respond(payload: dict[str, Any]) -> None:
        request_id = str(event.get("request_id") or "")
        if request_id:
            payload.setdefault("request_id", request_id)
        reply(payload)

    try:
        if command == "log.start":
            if post_lines is None:
                raise RuntimeError("设备日志投递通道未就绪")
            start(
                session_id=session_id,
                udid=udid,
                platform=platform,
                post_lines=post_lines,
                level=str(event.get("level") or "I"),
                tag=str(event.get("tag") or ""),
            )
            respond({"t": "log.start.result", "ok": True})
        elif command == "log.stop":
            stop(session_id)
            respond({"t": "log.stop.result", "ok": True})
        elif command == "log.clear":
            ok = clear(udid, platform)
            respond({"t": "log.clear.result", "ok": ok})
        else:
            respond(
                {
                    "t": "error",
                    "for": command,
                    "error_code": "not_supported",
                    "error": f"不支持的日志命令：{command}",
                }
            )
    except (OSError, RuntimeError, ValueError) as exc:
        respond(
            {
                "t": "error",
                "for": command,
                "error_code": "io_error",
                "error": str(exc),
            }
        )
    return True


def start(
    *,
    session_id: str,
    udid: str,
    platform: str,
    post_lines: PostLinesFn,
    level: str = "I",
    tag: str = "",
) -> None:
    filters = ((level or "I").upper(), (tag or "").strip())
    with _lock:
        existing = _pumps.get(session_id)
        if existing is not None and existing.filters == filters and _alive(existing):
            return
        if existing is not None:
            _stop_locked(existing)
        pump = _Pump(
            session_id=session_id,
            udid=udid,
            platform=platform,
            post_lines=post_lines,
        )
        pump.filters = filters
        pump.proc = _spawn(platform, udid, filters[0], filters[1])
        pump.thread = threading.Thread(
            target=_read_loop,
            args=(pump,),
            name=f"device-log-{session_id[:8]}",
            daemon=True,
        )
        _pumps[session_id] = pump
        _udid_index.setdefault(udid, set()).add(session_id)
        pump.thread.start()


def stop(session_id: str) -> None:
    with _lock:
        pump = _pumps.pop(session_id, None)
        if pump is None:
            return
        indexed = _udid_index.get(pump.udid)
        if indexed is not None:
            indexed.discard(session_id)
            if not indexed:
                _udid_index.pop(pump.udid, None)
        _stop_locked(pump)


def stop_for_device(udid: str) -> None:
    with _lock:
        sids = list(_udid_index.pop(udid, set()))
        pumps = [_pumps.pop(sid) for sid in sids if sid in _pumps]
    for pump in pumps:
        _stop_locked(pump)


def clear(udid: str, platform: str) -> bool:
    if (platform or "").lower() != "android":
        return True
    from ..android.device_log import clear as android_clear

    return android_clear(udid)


def _alive(pump: _Pump) -> bool:
    thread = pump.thread
    proc = pump.proc
    if thread is None or not thread.is_alive():
        return False
    if proc is None:
        return False
    return proc.poll() is None


def _spawn(platform: str, udid: str, level: str, tag: str) -> subprocess.Popen[str]:
    if (platform or "").lower() == "ios":
        from ..ios.device_log import spawn as ios_spawn

        return ios_spawn(udid)
    from ..android.device_log import spawn as android_spawn

    return android_spawn(udid, level, tag)


def _stop_locked(pump: _Pump) -> None:
    pump.stop.set()
    proc = pump.proc
    pump.proc = None
    if proc is not None:
        _terminate(proc)
    thread = pump.thread
    if thread is not None and thread.is_alive() and thread is not threading.current_thread():
        thread.join(timeout=1.5)
    pump.thread = None


def _terminate(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is not None:
        return
    try:
        proc.terminate()
    except OSError:
        pass
    deadline = time.monotonic() + 1.5
    while time.monotonic() < deadline and proc.poll() is None:
        time.sleep(0.05)
    if proc.poll() is None:
        try:
            proc.kill()
        except OSError:
            pass
    try:
        if proc.stdout is not None:
            proc.stdout.close()
    except OSError:
        pass


def _format_line(platform: str, raw: str) -> str:
    text = (raw or "").rstrip("\r\n")
    if not text:
        return ""
    if (platform or "").lower() == "ios":
        from ..ios.device_log import readable

        text = readable(text)
    return text[:_MAX_LINE]


def _read_loop(pump: _Pump) -> None:
    proc = pump.proc
    if proc is None or proc.stdout is None:
        return
    pending: list[str] = []
    last_flush = time.monotonic()

    def flush() -> None:
        nonlocal pending, last_flush
        if not pending:
            return
        batch = pending
        pending = []
        last_flush = time.monotonic()
        try:
            pump.post_lines(batch)
        except Exception as post_err:  # noqa: BLE001
            _log.debug("post device logs: %s", post_err)

    try:
        for raw in proc.stdout:
            if pump.stop.is_set():
                break
            line = _format_line(pump.platform, raw)
            if not line:
                continue
            pending.append(line)
            if (
                len(pending) >= _FLUSH_LINES
                or time.monotonic() - last_flush >= _FLUSH_SEC
            ):
                flush()
    except (OSError, ValueError) as exc:
        _log.debug("device log read %s: %s", pump.session_id[:12], exc)
    finally:
        flush()
        _terminate(proc)
        _log.info("[device-log] stopped %s", pump.session_id[:12])
