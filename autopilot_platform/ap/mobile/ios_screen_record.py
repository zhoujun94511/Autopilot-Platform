"""iOS 屏幕录像：优先复用已有 WDA MJPEG；否则 go-ios ``screenshot --stream``。

对齐 WebAppForIos；WDA 会话存活时**禁止** reclaim 隧道 / 强挂 DDI，避免打挂运行中会话。
资源不全时由 ``probe_ios_screen_record`` / ``start_ios_screen_record`` 抛出明确错误。
"""

from __future__ import annotations

import os
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from .ios_bootstrap import (
    AGENT_ENV,
    DEFAULT_MJPEG_PORT,
    DEFAULT_TUNNEL_INFO_PORT,
    DEFAULT_WDA_PORT,
    IosDevicePrep,
    available,
    mjpeg_alive,
    resolve_go_ios,
    wda_alive,
)

_Log = Callable[[str], None]
_SESSIONS: dict[str, "IosScreenRecordSession"] = {}


def probe_ios_screen_record() -> tuple[bool, str]:
    """资源预检。不可用时返回 (False, 原因)。"""
    if not available() or resolve_go_ios() is None:
        return False, (
            "未找到 go-ios 二进制（resources/re_go_ios/executable/<os>/ios[.exe]），"
            "iOS 屏幕录像关键字不可用"
        )
    try:
        # opencv-python-headless 提供 cv2；PyCharm 常认不出包名映射
        # noinspection PyPackageRequirements,PyUnresolvedReferences
        import cv2  # noqa: F401
        # noinspection PyPackageRequirements,PyUnresolvedReferences
        import numpy  # noqa: F401
    except ImportError as exc:
        return False, (
            f"缺少 OpenCV/numpy（{exc}），iOS 屏幕录像关键字不可用；"
            "请安装 opencv-python-headless 与 numpy"
        )
    return True, ""


def _pick_free_port(preferred: int = 3333) -> int:
    for port in range(preferred, preferred + 40):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _wait_mjpeg(
    url: str,
    *,
    proc: Optional[subprocess.Popen] = None,
    timeout: float = 15.0,
) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc is not None and proc.poll() is not None:
            return False
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                if getattr(resp, "status", resp.getcode()) == 200:
                    return True
        except (urllib.error.URLError, TimeoutError, OSError):
            pass
        time.sleep(0.5)
    return False


def _to_port(raw: Any, default: int) -> int:
    try:
        n = int(raw)
        return n if n > 0 else default
    except (TypeError, ValueError):
        return default


def _resolve_session_ports(
    *,
    info_port: Any = None,
    wda_port: Any = None,
    mjpeg_port: Any = None,
    worker_slot: Any = None,
) -> tuple[int, int, int]:
    """解析隧道 / WDA / MJPEG 端口；支持并行 slot 默认偏移。"""
    slot = None
    try:
        if worker_slot not in (None, ""):
            slot = int(worker_slot)
    except (TypeError, ValueError):
        slot = None

    info = _to_port(info_port, 0)
    wda = _to_port(wda_port, 0)
    mjpeg = _to_port(mjpeg_port, 0)
    if slot is not None and slot >= 0:
        if not info:
            info = DEFAULT_TUNNEL_INFO_PORT + slot * 10
        if not wda:
            wda = DEFAULT_WDA_PORT + slot
        if not mjpeg:
            mjpeg = DEFAULT_MJPEG_PORT + slot
    if not info:
        info = DEFAULT_TUNNEL_INFO_PORT
    if not wda:
        wda = DEFAULT_WDA_PORT
    if not mjpeg:
        mjpeg = DEFAULT_MJPEG_PORT
    return info, wda, mjpeg


def _attach_existing_mjpeg(mjpeg_port: int, log: _Log) -> Optional[str]:
    """WDA 镜像流已就绪时直接复用，避免再起 go-ios 采屏。"""
    if mjpeg_alive(mjpeg_port, timeout=2.0):
        url = f"http://127.0.0.1:{mjpeg_port}/"
        log(f"iOS 录屏：复用已有 WDA MJPEG {url}（不启 go-ios stream、不回收隧道）")
        return url
    return None


def _prepare_for_goios_stream(
    udid: str,
    *,
    info_port: int,
    wda_port: int,
    mjpeg_port: int,
    log: _Log,
) -> None:
    """仅在需要新建 go-ios stream 时调用。

    - WDA / MJPEG 已存活：跳过隧道与 DDI（杜绝 reclaim 误伤）。
    - 隧道已在指定 info_port 运行：只复用，不 reclaim；DDI 已挂则跳过。
    - 冷启动：才允许 ensure_tunnel（内部可能 reclaim 本 info_port）。
    """
    if wda_alive(wda_port, timeout=2.0) or mjpeg_alive(mjpeg_port, timeout=1.5):
        log(
            "iOS 录屏：检测到存活 WDA/MJPEG，跳过隧道回收与 DDI 挂载"
            f"（wda={wda_port}, mjpeg={mjpeg_port}）"
        )
        return

    prep = IosDevicePrep(
        udid=udid,
        wda_bundle="",
        info_port=info_port,
        wda_port=wda_port,
        log=log,
        mjpeg_port=mjpeg_port,
    )
    if prep.tunnel_running():
        log(f"iOS 录屏：复用已有 go-ios 隧道（info_port={info_port}），不 reclaim")
    else:
        log(
            f"iOS 录屏：冷启动隧道 info_port={info_port}"
            "（无存活 WDA；可能回收该 info_port 残留）…"
        )
        if not prep.ensure_tunnel(timeout=45, force=False):
            raise RuntimeError(
                "go-ios 隧道未就绪（iOS 17+ 通常需要 --userspace）；"
                "iOS 屏幕录像关键字不可用"
            )

    # WDA 未活时才尝试 DDI；已挂载则 ensure_image 快速返回
    log("iOS 录屏：检查开发者镜像（已挂载则跳过）…")
    if not prep.ensure_image():
        detail = (getattr(prep, "_image_error", "") or "").strip()
        raise RuntimeError(
            "开发者镜像未挂载或本地无匹配 DDI，iOS 屏幕录像关键字不可用。"
            "请将匹配镜像放入 resources/re_go_ios/devimages，或联网后重试 image auto。"
            + (f"\n{detail}" if detail else "")
        )


def _spawn_screenshot_stream(udid: str, port: int) -> subprocess.Popen:
    exe = resolve_go_ios()
    assert exe is not None
    cmd = [str(exe), "--udid", udid, "screenshot", "--stream", "--port", str(port)]
    env = {**os.environ, **AGENT_ENV}
    kwargs: dict[str, Any] = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "env": env,
    }
    if os.name == "nt":
        kwargs["creationflags"] = (
            getattr(subprocess, "CREATE_NO_WINDOW", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        )
    return subprocess.Popen(cmd, **kwargs)


def _safe_fourcc(codec: str) -> int:
    # noinspection PyPackageRequirements,PyUnresolvedReferences
    import cv2

    try:
        if hasattr(cv2, "VideoWriter_fourcc"):
            return cv2.VideoWriter_fourcc(*codec)
    except (AttributeError, TypeError, ValueError):
        pass
    return 0x34766D70  # mp4v


def _record_mjpeg_to_mp4(
    mjpeg_url: str,
    mp4_path: str,
    stop_evt: threading.Event,
    fps: float = 12.0,
) -> None:
    # noinspection PyPackageRequirements,PyUnresolvedReferences
    import cv2
    # noinspection PyPackageRequirements,PyUnresolvedReferences
    import numpy as np

    target_fps = fps if 1.0 <= fps <= 60.0 else 12.0
    writer = None
    target_w = target_h = 0
    last_ts: Optional[float] = None
    frame_acc = 0.0
    try:
        req = urllib.request.Request(mjpeg_url)
        with urllib.request.urlopen(req, timeout=15.0) as resp:
            buffer = b""
            while not stop_evt.is_set():
                chunk = resp.read(4096)
                if not chunk:
                    break
                buffer += chunk
                while True:
                    start = buffer.find(b"\xff\xd8")
                    end = buffer.find(b"\xff\xd9")
                    if start == -1 or end == -1 or end <= start:
                        break
                    jpg = buffer[start : end + 2]
                    buffer = buffer[end + 2 :]
                    frame = cv2.imdecode(
                        np.frombuffer(jpg, dtype=np.uint8), cv2.IMREAD_COLOR
                    )
                    if frame is None:
                        continue
                    h, w = frame.shape[:2]
                    if writer is None:
                        target_w = w - (w % 2) or w
                        target_h = h - (h % 2) or h
                        if target_w != w or target_h != h:
                            frame = cv2.resize(frame, (target_w, target_h))
                            h, w = frame.shape[:2]
                        writer = cv2.VideoWriter(
                            mp4_path,
                            _safe_fourcc("mp4v"),
                            target_fps,
                            (w, h),
                        )
                        last_ts = time.time()
                    elif w != target_w or h != target_h:
                        frame = cv2.resize(frame, (target_w, target_h))
                    now = time.time()
                    if last_ts is None:
                        frame_acc += 1.0
                    else:
                        frame_acc += max(0.0, now - last_ts) * target_fps
                    last_ts = now
                    n = min(int(frame_acc), 5)
                    if n > 0:
                        frame_acc -= n
                        for _ in range(n):
                            writer.write(frame)
    except (urllib.error.URLError, TimeoutError, OSError):
        pass
    finally:
        if writer is not None:
            try:
                writer.release()
            except (AttributeError, OSError, RuntimeError):
                pass


@dataclass
class IosScreenRecordSession:
    udid: str
    port: int
    process: Optional[subprocess.Popen]
    stop_evt: threading.Event
    thread: threading.Thread
    path: str
    source: str = "goios"  # goios | wda_mjpeg
    prep_note: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


def start_ios_screen_record(
    udid: str,
    out_path: str,
    *,
    log: Optional[_Log] = None,
    fps: float = 12.0,
    info_port: Any = None,
    wda_port: Any = None,
    mjpeg_port: Any = None,
    worker_slot: Any = None,
) -> IosScreenRecordSession:
    """开始落盘。优先挂已有 WDA MJPEG；否则 go-ios stream。失败抛 RuntimeError。"""
    log = log or (lambda _m: None)
    ok, reason = probe_ios_screen_record()
    if not ok:
        raise RuntimeError(reason)
    udid = (udid or "").strip()
    if not udid:
        raise RuntimeError("缺少设备 UDID，iOS 屏幕录像关键字不可用")

    prev = _SESSIONS.pop(udid, None)
    if prev is not None:
        stop_ios_screen_record(udid, ignore_missing=True)

    info_p, wda_p, mjpeg_p = _resolve_session_ports(
        info_port=info_port,
        wda_port=wda_port,
        mjpeg_port=mjpeg_port,
        worker_slot=worker_slot,
    )
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)

    url = _attach_existing_mjpeg(mjpeg_p, log)
    proc: Optional[subprocess.Popen] = None
    port = mjpeg_p
    source = "wda_mjpeg"

    if url is None:
        source = "goios"
        _prepare_for_goios_stream(
            udid,
            info_port=info_p,
            wda_port=wda_p,
            mjpeg_port=mjpeg_p,
            log=log,
        )
        port = _pick_free_port(3333)
        try:
            proc = _spawn_screenshot_stream(udid, port)
        except OSError as exc:
            raise RuntimeError(f"启动 go-ios screenshot --stream 失败: {exc}") from exc
        url = f"http://127.0.0.1:{port}/"
        if not _wait_mjpeg(url, proc=proc, timeout=18.0):
            err = ""
            # noinspection PyBroadException
            try:
                if proc.poll() is not None:
                    out, errout = proc.communicate(timeout=1)
                    err = ((out or b"") + (errout or b"")).decode("utf-8", "replace")[
                        -400:
                    ]
            except Exception:
                pass
            # noinspection PyBroadException
            try:
                proc.terminate()
            except Exception:
                pass
            raise RuntimeError(
                "go-ios MJPEG 流未就绪，iOS 屏幕录像关键字不可用"
                + (f"：{err}" if err else "（请确认 USB 信任、设备解锁、DDI 已挂载）")
            )
        log(f"iOS 录屏：已启动 go-ios screenshot --stream @ {url}")

    stop_evt = threading.Event()
    th = threading.Thread(
        target=_record_mjpeg_to_mp4,
        args=(url, out_path, stop_evt, fps),
        daemon=True,
        name=f"ios-screen-rec-{udid[-8:]}",
    )
    th.start()
    sess = IosScreenRecordSession(
        udid=udid,
        port=port,
        process=proc,
        stop_evt=stop_evt,
        thread=th,
        path=out_path,
        source=source,
        prep_note=f"info={info_p},wda={wda_p},mjpeg={mjpeg_p}",
    )
    _SESSIONS[udid] = sess
    return sess


def stop_ios_screen_record(
    udid: str,
    *,
    ignore_missing: bool = False,
    join_timeout: float = 6.0,
) -> str:
    """停止录屏，返回 mp4 路径。复用 WDA MJPEG 时不杀 WDA/转发进程。"""
    udid = (udid or "").strip()
    sess = _SESSIONS.pop(udid, None)
    if sess is None:
        if ignore_missing:
            return ""
        raise RuntimeError("当前无进行中的 iOS 屏幕录像会话")

    sess.stop_evt.set()
    # 仅终止本关键字拉起的 go-ios stream；勿动 WDA / 9100 转发
    if sess.process is not None:
        # noinspection PyBroadException
        try:
            if sess.process.poll() is None:
                sess.process.terminate()
                try:
                    sess.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    sess.process.kill()
        except Exception:
            pass
    if sess.thread.is_alive():
        sess.thread.join(timeout=join_timeout)

    path = sess.path
    if not path or not os.path.isfile(path) or os.path.getsize(path) <= 0:
        raise RuntimeError(f"iOS 屏幕录像未生成有效文件: {path or '(empty)'}")
    return path
